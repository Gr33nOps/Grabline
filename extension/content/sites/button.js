// Grabline Connect — shared site-module hover button.
//
// Every site module is just a matcher: given a hovered element, return the
// element to anchor the ⬇ button to and the URL to grab, or null. This file
// owns the rest — the shadow-root button, the show dwell (no flicker while
// scanning a grid), the rect keep-alive (players that spawn *over* the
// anchor steal the hover; as long as the pointer stays inside the anchor's
// box the button survives), and the per-site off switch.
//
// Loaded before each content/sites/*.js via the manifest.

(() => {
  const api = globalThis.browser ?? globalThis.chrome;
  const SHOW_DELAY_MS = 150;
  const RECT_MARGIN = 8;

  globalThis.grablineSiteButton = ({ resolve }) => {
    let enabled = true;
    api.storage.local.get("disabledSites").then(({ disabledSites = [] }) => {
      if (disabledSites.includes(location.hostname)) enabled = false;
    });
    api.storage.onChanged.addListener((changes, area) => {
      if (area === "local" && changes.disabledSites) {
        enabled = !(changes.disabledSites.newValue ?? []).includes(location.hostname);
        if (!enabled) hide();
      }
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
    let currentRect = null;
    let hideTimer = 0;
    let showTimer = 0;

    function attachHost() {
      if (document.body && !host.isConnected) document.body.appendChild(host);
    }

    function hide() {
      clearTimeout(showTimer);
      button.style.display = "none";
      currentUrl = null;
      currentRect = null;
    }

    function scheduleHide() {
      clearTimeout(hideTimer);
      hideTimer = setTimeout(hide, 300);
    }

    function insideCurrentRect(event) {
      return (
        currentRect !== null &&
        event.clientX >= currentRect.left - RECT_MARGIN &&
        event.clientX <= currentRect.right + RECT_MARGIN &&
        event.clientY >= currentRect.top - RECT_MARGIN &&
        event.clientY <= currentRect.bottom + RECT_MARGIN
      );
    }

    function showFor(anchor, url) {
      attachHost();
      const rect = anchor.getBoundingClientRect();
      currentUrl = url;
      currentRect = rect;
      button.style.left = `${Math.max(4, rect.right - 38)}px`;
      button.style.top = `${Math.max(4, rect.top + 6)}px`;
      button.style.display = "block";
      button.style.background = "#2563eb";
      button.textContent = "⬇";
    }

    document.addEventListener(
      "mouseover",
      (event) => {
        if (!enabled || !(event.target instanceof Element)) return;
        let hit = null;
        try {
          hit = resolve(event.target);
        } catch {
          hit = null; // a matcher must never break the page
        }
        if (!hit) {
          if (currentUrl && insideCurrentRect(event)) return;
          clearTimeout(showTimer);
          if (currentUrl) scheduleHide();
          return;
        }
        clearTimeout(hideTimer);
        clearTimeout(showTimer);
        if (hit.url === currentUrl) return; // already shown for this target
        showTimer = setTimeout(() => showFor(hit.anchor, hit.url), SHOW_DELAY_MS);
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
  };
})();
