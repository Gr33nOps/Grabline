// Grabline Connect - element sniffer + hover ⬇ button (F1.2).
//
// One floating button, hosted in a closed shadow root so page CSS can't touch
// it. Shown when the pointer rests on a <video>, <audio>, or big-enough
// <img>; clicking hands the media URL (or the page URL for blob-backed
// players, which the Smart Engine usually understands) to the desktop app.

(() => {
  const api = globalThis.browser ?? globalThis.chrome;
  const MIN_IMAGE_SIZE = 200;
  const HIDE_DELAY_MS = 350;
  // Hosts where a site module (content/sites/*.js) owns the media UI. On
  // those hosts the generic overlay stands back: browse pages run inline
  // preview <video>s whose blob src would fall back to the *page* URL (= the
  // feed, not the video), and site thumbnails already have their own button.
  // videos: the generic overlay only decorates <video> on matching paths
  // (the real player page). images: skipped entirely when true.
  const SITE_RULES = [
    {
      hosts: /(^|\.)youtube\.com$/,
      videos: /^$/, // never - youtube.js owns thumbnails AND the player button
      images: true,
    },
    {
      hosts: /(^|\.)(x|twitter)\.com$/,
      videos: /^$/, // never - the x.js module handles every tweet video
      images: false,
    },
  ];

  function siteRule() {
    return SITE_RULES.find((rule) => rule.hosts.test(location.hostname)) ?? null;
  }

  let enabled = true;
  // Master switch (popup): turn hover buttons off everywhere. Right-click and
  // the toolbar popup still work.
  let hoverGlobal = true;
  // Images are opt-in (popup toggle): a ⬇ on every profile picture and chat
  // thumbnail is noise, and right-click + the gallery grabber cover images.
  let imagesEnabled = false;
  let currentTarget = null;
  let hideTimer = 0;

  // Which corner of the hovered element the ⬇ sits in (popup setting).
  let corner = "top-right";

  api.storage.local.get(["disabledSites", "overlayImages", "buttonCorner", "hoverButtons"]).then(
    ({ disabledSites = [], overlayImages = false, buttonCorner = "top-right", hoverButtons = true }) => {
      if (disabledSites.includes(location.hostname)) enabled = false;
      imagesEnabled = overlayImages;
      corner = buttonCorner;
      hoverGlobal = hoverButtons;
    },
  );
  api.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") return;
    if (changes.disabledSites) {
      enabled = !(changes.disabledSites.newValue ?? []).includes(location.hostname);
      if (!enabled) hideButton();
    }
    if (changes.hoverButtons) {
      hoverGlobal = changes.hoverButtons.newValue !== false;
      if (!hoverGlobal) hideButton();
    }
    if (changes.overlayImages) {
      imagesEnabled = Boolean(changes.overlayImages.newValue);
      if (!imagesEnabled) hideButton();
    }
    if (changes.buttonCorner) {
      corner = changes.buttonCorner.newValue ?? "top-right";
    }
  });

  // ------------------------------------------------------------- button

  const host = document.createElement("div");
  const shadow = host.attachShadow({ mode: "closed" });
  const button = document.createElement("button");
  button.textContent = "⬇";
  button.title = "Download with Grabline";
  button.style.cssText = [
    "position: fixed",
    "z-index: 2147483647",
    "display: none",
    "width: 34px",
    "height: 34px",
    "border: none",
    "border-radius: 17px",
    "background: #0170fd",
    "color: #fff",
    "font: 700 16px/1 system-ui, sans-serif",
    "cursor: pointer",
    "box-shadow: 0 2px 8px rgba(0,0,0,.35)",
    "opacity: .92",
  ].join(";");
  shadow.appendChild(button);

  function attachHost() {
    if (document.body && !host.isConnected) document.body.appendChild(host);
  }

  function mediaUrlFor(element) {
    let src = null;
    if (element instanceof HTMLImageElement) src = element.currentSrc || element.src;
    else if (element instanceof HTMLMediaElement) {
      src = element.currentSrc || element.src;
      if (!src) src = element.querySelector("source")?.src ?? null;
    }
    // blob:/data: sources can't be fetched outside the page. Send the page
    // URL (the Smart Engine may know the site) and flag it so the background
    // attaches the streams the sniffer saw in this tab as fallbacks - on
    // no-name streaming sites the sniffed .m3u8 IS the movie.
    if (!src || !/^https?:/.test(src)) return { url: location.href, fromPage: true };
    return { url: src, fromPage: false };
  }

  function eligible(element) {
    const rule = siteRule();
    if (element instanceof HTMLMediaElement) {
      if (rule) return rule.videos.test(location.pathname);
      return true;
    }
    if (element instanceof HTMLImageElement) {
      if (!imagesEnabled || rule?.images) return false;
      return (
        element.naturalWidth >= MIN_IMAGE_SIZE && element.naturalHeight >= MIN_IMAGE_SIZE
      );
    }
    return false;
  }

  const BUTTON_SIZE = 34;

  function placeButton(rect) {
    const size = BUTTON_SIZE;
    const left = corner.endsWith("left") ? rect.left + 8 : rect.right - size - 8;
    const top = corner.startsWith("bottom") ? rect.bottom - size - 8 : rect.top + 8;
    button.style.left = `${Math.min(Math.max(4, left), window.innerWidth - size - 4)}px`;
    button.style.top = `${Math.min(Math.max(4, top), window.innerHeight - size - 4)}px`;
  }

  function showButtonFor(element) {
    attachHost();
    const rect = element.getBoundingClientRect();
    if (rect.width < 40 || rect.height < 40) return;
    currentTarget = element;
    placeButton(rect);
    button.style.display = "block";
    button.style.background = "#0170fd";
    button.textContent = "⬇";
    startFollowing();
  }

  function hideButton() {
    clearTimeout(hideTimer);
    stopFollowing();
    button.style.display = "none";
    currentTarget = null;
  }

  function scheduleHide() {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hideButton, HIDE_DELAY_MS);
  }

  // Keep the button glued to its media while shown. Native scrolling fires
  // "scroll", but reels/shorts feeds move with CSS transforms that don't - so
  // we re-read the target's box every frame. The loop stops the instant the
  // button hides, so it only runs during an actual hover.
  let followId = 0;

  function reposition() {
    if (!currentTarget) return;
    if (!currentTarget.isConnected) return hideButton();
    const rect = currentTarget.getBoundingClientRect();
    const offscreen =
      rect.bottom < 0 ||
      rect.top > window.innerHeight ||
      rect.right < 0 ||
      rect.left > window.innerWidth;
    if (offscreen || rect.width < 40 || rect.height < 40) return hideButton();
    placeButton(rect);
  }

  function startFollowing() {
    if (!followId) followId = requestAnimationFrame(followFrame);
  }

  function stopFollowing() {
    if (followId) cancelAnimationFrame(followId);
    followId = 0;
  }

  function followFrame() {
    followId = 0;
    if (button.style.display === "none") return;
    reposition();
    if (button.style.display !== "none") followId = requestAnimationFrame(followFrame);
  }

  // ------------------------------------------------- gallery grab (F2.2)
  // The background script asks for every big-enough image on the page; a
  // wrapping <a> that links straight to an image wins over the (often
  // thumbnail-sized) <img> src.

  const IMAGE_HREF = /\.(jpe?g|png|gif|webp|avif|bmp)(\?|$)/i;
  const MAX_GALLERY_ITEMS = 200;

  function collectImages() {
    const urls = [];
    const seen = new Set();
    for (const img of document.images) {
      if (urls.length >= MAX_GALLERY_ITEMS) break;
      const src = img.currentSrc || img.src;
      if (!src || !/^https?:/.test(src)) continue;
      if (img.naturalWidth < MIN_IMAGE_SIZE && img.naturalHeight < MIN_IMAGE_SIZE) continue;
      let url = src;
      const href = img.closest("a")?.getAttribute("href");
      if (href) {
        try {
          const full = new URL(href, location.href).toString();
          if (IMAGE_HREF.test(full)) url = full;
        } catch {
          /* unparsable href - keep the img src */
        }
      }
      if (seen.has(url)) continue;
      seen.add(url);
      urls.push(url);
    }
    return urls;
  }

  // ------------------------------------------------ progress pill (F1.3)
  // The background script polls the app (over Native Messaging) for every
  // download grabbed from this tab and forwards updates here. One stack of
  // pills, bottom-right; finished downloads linger briefly, then fade.

  const pillHost = document.createElement("div");
  const pillShadow = pillHost.attachShadow({ mode: "closed" });
  const pillStack = document.createElement("div");
  pillStack.style.cssText = [
    "position: fixed",
    "right: 16px",
    "bottom: 16px",
    "z-index: 2147483647",
    "display: none",
    "flex-direction: column",
    "align-items: flex-end",
    "gap: 6px",
  ].join(";");
  pillShadow.appendChild(pillStack);
  const pillRows = new Map(); // url -> { row, timer }

  function humanBytes(count) {
    const units = ["B", "KB", "MB", "GB"];
    let value = count;
    let index = 0;
    while (value >= 1024 && index < units.length - 1) {
      value /= 1024;
      index += 1;
    }
    return `${value.toFixed(index ? 1 : 0)} ${units[index]}`;
  }

  function pillRowFor(url) {
    let entry = pillRows.get(url);
    if (!entry) {
      const row = document.createElement("div");
      row.style.cssText = [
        "max-width: 340px",
        "padding: 8px 14px",
        "border-radius: 999px",
        "background: rgba(17,24,39,.94)",
        "color: #fff",
        "font: 500 12px/1.3 system-ui, sans-serif",
        "box-shadow: 0 2px 8px rgba(0,0,0,.35)",
        "overflow: hidden",
        "text-overflow: ellipsis",
        "white-space: nowrap",
      ].join(";");
      pillStack.appendChild(row);
      entry = { row, timer: 0 };
      pillRows.set(url, entry);
    }
    return entry;
  }

  function dropPill(url, delayMs) {
    const entry = pillRows.get(url);
    if (!entry) return;
    clearTimeout(entry.timer);
    entry.timer = setTimeout(() => {
      entry.row.remove();
      pillRows.delete(url);
      if (!pillRows.size) pillStack.style.display = "none";
    }, delayMs);
  }

  function pillText(job) {
    const name = job.name ?? "download";
    if (job.status === "completed") return `✓ ${name}`;
    if (job.status === "failed") return `✗ failed - ${name}`;
    if (job.total && job.downloaded != null) {
      return `⬇ ${Math.min(100, Math.round((job.downloaded / job.total) * 100))}% · ${name}`;
    }
    if (job.downloaded) return `⬇ ${humanBytes(job.downloaded)} · ${name}`;
    return `⬇ starting · ${name}`;
  }

  function renderProgress(items) {
    if (document.body && !pillHost.isConnected) document.body.appendChild(pillHost);
    for (const job of items) {
      if (job.status === "cancelled") {
        dropPill(job.url, 0);
        continue;
      }
      const entry = pillRowFor(job.url);
      entry.row.textContent = pillText(job);
      entry.row.title = job.url;
      if (job.status === "completed") dropPill(job.url, 5000);
      if (job.status === "failed") dropPill(job.url, 8000);
    }
    if (pillRows.size) pillStack.style.display = "flex";
  }

  // Every http(s) link on the page, most-downloadable first. The desktop
  // app's picker filters and routes them; here we just gather and dedupe.
  const MAX_LINKS = 300;
  const FILE_LINK =
    /\.(mp4|mkv|webm|mov|avi|m4v|mp3|m4a|flac|wav|ogg|opus|aac|zip|rar|7z|tar|gz|xz|iso|pdf|docx?|xlsx?|pptx?|epub|apk|exe|dmg|appimage|deb|rpm|jpe?g|png|gif|webp|svg)(\?|$)/i;

  function collectLinks() {
    const withExt = [];
    const rest = [];
    const seen = new Set();
    for (const anchor of document.links) {
      if (seen.size >= MAX_LINKS) break;
      const href = anchor.href;
      if (!href || !/^https?:/.test(href) || seen.has(href)) continue;
      seen.add(href);
      (FILE_LINK.test(href) ? withExt : rest).push(href);
    }
    // File-looking links first so the picker's default selection is useful.
    return [...withExt, ...rest].slice(0, MAX_LINKS);
  }

  // Everything downloadable inside the user's text selection: links, images,
  // and playing media that the highlighted region touches. The app's picker
  // then filters by type, so one gesture covers "download the selected
  // links / images / videos / documents".
  function collectSelection() {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) return [];
    const urls = [];
    const seen = new Set();
    const push = (url) => {
      if (url && /^https?:/.test(url) && !seen.has(url) && urls.length < MAX_LINKS) {
        seen.add(url);
        urls.push(url);
      }
    };
    for (const anchor of document.links) {
      if (selection.containsNode(anchor, true)) push(anchor.href);
    }
    for (const img of document.images) {
      if (selection.containsNode(img, true)) push(img.currentSrc || img.src);
    }
    for (const media of document.querySelectorAll("video, audio")) {
      if (!selection.containsNode(media, true)) continue;
      push(media.currentSrc || media.src || media.querySelector("source")?.src);
    }
    return urls;
  }

  api.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.cmd === "collectImages") {
      sendResponse({ urls: collectImages() });
    } else if (message?.cmd === "collectLinks") {
      sendResponse({ urls: collectLinks() });
    } else if (message?.cmd === "collectSelection") {
      sendResponse({ urls: collectSelection() });
    } else if (message?.cmd === "progress" && Array.isArray(message.items)) {
      renderProgress(message.items);
    }
    return false;
  });

  // Find a <video>/<audio> under the pointer even when the site paints its own
  // controls or a click-catching layer on top (reels, shorts, live players):
  // elementsFromPoint returns the whole stack at that spot, including elements
  // sitting *behind* others. That's what makes the button appear on media the
  // page covers, which plain event.target matching misses.
  function mediaUnderPointer(x, y) {
    for (const el of document.elementsFromPoint(x, y)) {
      if (el === host) continue;
      if (el instanceof HTMLMediaElement) return el;
    }
    return null;
  }

  document.addEventListener(
    "mouseover",
    (event) => {
      if (!enabled || !hoverGlobal || event.target === host) return;
      // Videos (incl. streams/reels) win, found even when covered; images stay
      // opt-in and are only taken from the direct target (never through a layer).
      let media = mediaUnderPointer(event.clientX, event.clientY);
      if (!media && event.target instanceof HTMLImageElement) media = event.target;
      if (media && eligible(media)) {
        clearTimeout(hideTimer);
        showButtonFor(media);
      } else if (currentTarget && !currentTarget.contains(event.target)) {
        scheduleHide();
      }
    },
    { passive: true },
  );
  document.addEventListener("scroll", reposition, { passive: true, capture: true });
  window.addEventListener("resize", reposition, { passive: true });
  // Switching tab or window must not leave a stale button stuck on the page.
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) hideButton();
  });
  window.addEventListener("blur", hideButton);

  button.addEventListener("mouseenter", () => clearTimeout(hideTimer));
  button.addEventListener("mouseleave", scheduleHide);
  button.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (!currentTarget) return;
    const media = mediaUrlFor(currentTarget);
    const reply = await api.runtime.sendMessage({
      cmd: "grab",
      url: media.url,
      sniff: media.fromPage,
    });
    // Quick inline feedback, then fade away.
    button.textContent = reply?.type === "error" ? "!" : "✓";
    button.style.background = reply?.type === "error" ? "#b91c1c" : "#15803d";
    setTimeout(hideButton, 900);
  });
})();
