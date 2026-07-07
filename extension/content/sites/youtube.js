// Grabline Connect — YouTube site module (F1.3, first slice).
//
// Adds a hover ⬇ to video thumbnails (home, search, channels, sidebar,
// playlists, Shorts shelf) so a video can be grabbed without opening it.
// Clicking hands the watch URL to the desktop app, which pops its quality
// panel. On watch pages the generic overlay already covers the player
// (blob video → page URL → Smart Engine).
//
// DELIBERATELY ISOLATED: every selector lives in THUMBNAIL_ANCHORS below.
// When YouTube's DOM churns, this file is the whole blast radius — worst
// case the thumbnail button pauses while right-click and paste still work.

(() => {
  const api = globalThis.browser ?? globalThis.chrome;

  // Anchors that wrap a video thumbnail, oldest → newest YouTube layouts.
  const THUMBNAIL_ANCHORS = [
    "a#thumbnail[href*='/watch']",
    "a.yt-lockup-view-model-wiz__content-image[href*='/watch']",
    "a.yt-simple-endpoint[href^='/shorts/']",
    "a.reel-item-endpoint[href^='/shorts/']",
  ].join(", ");

  let enabled = true;
  api.storage.local.get("disabledSites").then(({ disabledSites = [] }) => {
    if (disabledSites.includes(location.hostname)) enabled = false;
  });

  const host = document.createElement("div");
  const shadow = host.attachShadow({ mode: "closed" });
  const button = document.createElement("button");
  button.textContent = "⬇";
  button.title = "Download with Grabline";
  button.style.cssText = [
    "position: fixed",
    "z-index: 2147483647",
    "display: none",
    "width: 30px",
    "height: 30px",
    "border: none",
    "border-radius: 15px",
    "background: #2563eb",
    "color: #fff",
    "font: 700 14px/1 system-ui, sans-serif",
    "cursor: pointer",
    "box-shadow: 0 2px 6px rgba(0,0,0,.4)",
  ].join(";");
  shadow.appendChild(button);

  let currentUrl = null;
  let hideTimer = 0;

  function attachHost() {
    if (document.body && !host.isConnected) document.body.appendChild(host);
  }

  function hide() {
    button.style.display = "none";
    currentUrl = null;
  }

  function scheduleHide() {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hide, 300);
  }

  document.addEventListener(
    "mouseover",
    (event) => {
      if (!enabled || !(event.target instanceof Element)) return;
      const anchor = event.target.closest(THUMBNAIL_ANCHORS);
      if (!anchor) {
        if (currentUrl) scheduleHide();
        return;
      }
      const href = anchor.getAttribute("href");
      if (!href) return;
      clearTimeout(hideTimer);
      attachHost();
      const rect = anchor.getBoundingClientRect();
      currentUrl = new URL(href, location.origin).toString();
      button.style.left = `${Math.max(4, rect.right - 38)}px`;
      button.style.top = `${Math.max(4, rect.top + 6)}px`;
      button.style.display = "block";
      button.style.background = "#2563eb";
      button.textContent = "⬇";
    },
    { passive: true },
  );
  document.addEventListener("scroll", hide, { passive: true, capture: true });

  button.addEventListener("mouseenter", () => clearTimeout(hideTimer));
  button.addEventListener("mouseleave", scheduleHide);
  button.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (!currentUrl) return;
    const reply = await api.runtime.sendMessage({ cmd: "grab", url: currentUrl });
    button.textContent = reply?.type === "error" ? "!" : "✓";
    button.style.background = reply?.type === "error" ? "#b91c1c" : "#15803d";
    setTimeout(hide, 900);
  });
})();
