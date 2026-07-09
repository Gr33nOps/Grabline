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
  // Images are opt-in (popup toggle): a ⬇ on every profile picture and chat
  // thumbnail is noise, and right-click + the gallery grabber cover images.
  let imagesEnabled = false;
  let currentTarget = null;
  let hideTimer = 0;

  // Which corner of the hovered element the ⬇ sits in (popup setting).
  let corner = "top-right";

  api.storage.local.get(["disabledSites", "overlayImages", "buttonCorner"]).then(
    ({ disabledSites = [], overlayImages = false, buttonCorner = "top-right" }) => {
      if (disabledSites.includes(location.hostname)) enabled = false;
      imagesEnabled = overlayImages;
      corner = buttonCorner;
    },
  );
  api.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") return;
    if (changes.disabledSites) {
      enabled = !(changes.disabledSites.newValue ?? []).includes(location.hostname);
      if (!enabled) hideButton();
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
    "background: #2563eb",
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

  function showButtonFor(element) {
    attachHost();
    const rect = element.getBoundingClientRect();
    if (rect.width < 40 || rect.height < 40) return;
    currentTarget = element;
    const size = 34;
    const left = corner.endsWith("left") ? rect.left + 8 : rect.right - size - 8;
    const top = corner.startsWith("bottom") ? rect.bottom - size - 8 : rect.top + 8;
    button.style.left = `${Math.min(Math.max(4, left), window.innerWidth - size - 4)}px`;
    button.style.top = `${Math.min(Math.max(4, top), window.innerHeight - size - 4)}px`;
    button.style.display = "block";
    button.style.background = "#2563eb";
    button.textContent = "⬇";
  }

  function hideButton() {
    button.style.display = "none";
    currentTarget = null;
  }

  function scheduleHide() {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hideButton, HIDE_DELAY_MS);
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

  api.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.cmd === "collectImages") {
      sendResponse({ urls: collectImages() });
    } else if (message?.cmd === "progress" && Array.isArray(message.items)) {
      renderProgress(message.items);
    }
    return false;
  });

  document.addEventListener(
    "mouseover",
    (event) => {
      if (!enabled) return;
      const element = event.target;
      if (element === button) return;
      if (eligible(element)) {
        clearTimeout(hideTimer);
        showButtonFor(element);
      } else if (currentTarget && !currentTarget.contains(element)) {
        scheduleHide();
      }
    },
    { passive: true },
  );
  document.addEventListener("scroll", hideButton, { passive: true, capture: true });

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
