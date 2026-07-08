// Grabline Connect — element sniffer + hover ⬇ button (F1.2).
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
      videos: /^\/(watch|shorts\/|live\/)/,
      images: true,
    },
    {
      hosts: /(^|\.)(x|twitter)\.com$/,
      videos: /^$/, // never — the x.js module handles every tweet video
      images: false,
    },
  ];

  function siteRule() {
    return SITE_RULES.find((rule) => rule.hosts.test(location.hostname)) ?? null;
  }

  let enabled = true;
  let currentTarget = null;
  let hideTimer = 0;

  api.storage.local.get("disabledSites").then(({ disabledSites = [] }) => {
    if (disabledSites.includes(location.hostname)) enabled = false;
  });
  api.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && changes.disabledSites) {
      enabled = !(changes.disabledSites.newValue ?? []).includes(location.hostname);
      if (!enabled) hideButton();
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
    // blob:/data: sources can't be fetched outside the page; the page URL
    // routes to the Smart Engine / network sniffer instead.
    if (!src || !/^https?:/.test(src)) return location.href;
    return src;
  }

  function eligible(element) {
    const rule = siteRule();
    if (element instanceof HTMLMediaElement) {
      if (rule) return rule.videos.test(location.pathname);
      return true;
    }
    if (element instanceof HTMLImageElement) {
      if (rule?.images) return false;
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
    button.style.left = `${Math.max(4, rect.right - 42)}px`;
    button.style.top = `${Math.max(4, rect.top + 8)}px`;
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
          /* unparsable href — keep the img src */
        }
      }
      if (seen.has(url)) continue;
      seen.add(url);
      urls.push(url);
    }
    return urls;
  }

  api.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.cmd === "collectImages") {
      sendResponse({ urls: collectImages() });
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
    const reply = await api.runtime.sendMessage({
      cmd: "grab",
      url: mediaUrlFor(currentTarget),
    });
    // Quick inline feedback, then fade away.
    button.textContent = reply?.type === "error" ? "!" : "✓";
    button.style.background = reply?.type === "error" ? "#b91c1c" : "#15803d";
    setTimeout(hideButton, 900);
  });
})();
