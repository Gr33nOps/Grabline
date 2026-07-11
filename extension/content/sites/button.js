// Grabline Connect - shared site-module hover button.
//
// Every site module is just a matcher: given a hovered element, return the
// element to anchor the ⬇ button to and the URL to grab, or null. This file
// owns the rest - the shadow-root button, the show dwell (no flicker while
// scanning a grid), the rect keep-alive (players that spawn *over* the
// anchor steal the hover; as long as the pointer stays inside the anchor's
// box the button survives), and the per-site off switch.
//
// Loaded before each content/sites/*.js via the manifest.

(() => {
  const api = globalThis.browser ?? globalThis.chrome;
  const SHOW_DELAY_MS = 150;
  const RECT_MARGIN = 8;
  const BUTTON_SIZE = 30;
  // The in-page quality panel (F1.3). Labels the app resolves at download
  // time (same trick as playlist batches) - instant, no metadata fetch.
  const QUALITY_LABELS = ["Best", "1080p", "720p", "480p", "MP3", "M4A"];

  // Which corner of the hovered element the ⬇ sits in - user-settable in
  // the popup (some sites put their own controls exactly where we default).
  let corner = "top-right";
  api.storage.local.get("buttonCorner").then(({ buttonCorner = "top-right" }) => {
    corner = buttonCorner;
  });
  api.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && changes.buttonCorner) {
      corner = changes.buttonCorner.newValue ?? "top-right";
    }
  });

  function buttonPosition(rect, size) {
    const left = corner.endsWith("left") ? rect.left + 8 : rect.right - size - 8;
    const top = corner.startsWith("bottom") ? rect.bottom - size - 6 : rect.top + 6;
    return {
      left: Math.min(Math.max(4, left), window.innerWidth - size - 4),
      top: Math.min(Math.max(4, top), window.innerHeight - size - 4),
    };
  }

  globalThis.grablineSiteButton = ({ resolve, qualityPanel = false }) => {
    let enabled = true;
    let hoverGlobal = true; // master switch (popup): hover buttons off everywhere
    api.storage.local.get(["disabledSites", "hoverButtons"]).then(
      ({ disabledSites = [], hoverButtons = true }) => {
        if (disabledSites.includes(location.hostname)) enabled = false;
        hoverGlobal = hoverButtons;
      },
    );
    api.storage.onChanged.addListener((changes, area) => {
      if (area !== "local") return;
      if (changes.disabledSites) {
        enabled = !(changes.disabledSites.newValue ?? []).includes(location.hostname);
        if (!enabled) hide();
      }
      if (changes.hoverButtons) {
        hoverGlobal = changes.hoverButtons.newValue !== false;
        if (!hoverGlobal) hide();
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

    const panel = document.createElement("div");
    panel.style.cssText = [
      "position: fixed",
      "z-index: 2147483647",
      "display: none",
      "flex-direction: column",
      "gap: 2px",
      "padding: 6px",
      "border-radius: 10px",
      "background: rgba(17,24,39,.96)",
      "box-shadow: 0 4px 14px rgba(0,0,0,.45)",
    ].join(";");
    shadow.appendChild(panel);
    let panelOpen = false;

    let currentUrl = null;
    let currentRect = null;
    // A show that is waiting out the dwell. Tracked with its own rect so DOM
    // churn under the pointer (YouTube spawns preview chips the moment you
    // hover) cannot cancel it while the pointer is still on the thumbnail.
    let pendingUrl = null;
    let pendingRect = null;
    let hideTimer = 0;
    let showTimer = 0;

    function attachHost() {
      if (document.body && !host.isConnected) document.body.appendChild(host);
    }

    function clearPending() {
      clearTimeout(showTimer);
      pendingUrl = null;
      pendingRect = null;
    }

    function hide() {
      clearPending();
      button.style.display = "none";
      closePanel();
      currentUrl = null;
      currentRect = null;
    }

    function closePanel() {
      panel.style.display = "none";
      panelOpen = false;
    }

    function feedback(reply) {
      button.textContent = reply?.type === "error" ? "!" : "✓";
      button.style.background = reply?.type === "error" ? "#b91c1c" : "#15803d";
      setTimeout(hide, 900);
    }

    function openPanel() {
      panel.textContent = "";
      const url = currentUrl;
      for (const label of [...QUALITY_LABELS, "More options…"]) {
        const choice = document.createElement("button");
        choice.textContent = label;
        choice.style.cssText = [
          "border: none",
          "border-radius: 6px",
          "padding: 5px 14px",
          "background: transparent",
          "color: #fff",
          "font: 500 12px/1.2 system-ui, sans-serif",
          "cursor: pointer",
          "text-align: left",
        ].join(";");
        choice.addEventListener("mouseenter", () => (choice.style.background = "#2563eb"));
        choice.addEventListener("mouseleave", () => (choice.style.background = "transparent"));
        choice.addEventListener("click", async (event) => {
          event.preventDefault();
          event.stopPropagation();
          closePanel();
          // "More options…" sends no quality: the desktop panel opens instead.
          const quality = QUALITY_LABELS.includes(label) ? label : null;
          feedback(await api.runtime.sendMessage({ cmd: "grab", url, quality }));
        });
        panel.appendChild(choice);
      }
      const rect = button.getBoundingClientRect();
      panel.style.left = `${Math.max(4, Math.min(rect.left, window.innerWidth - 130))}px`;
      panel.style.top = `${rect.bottom + 4}px`;
      panel.style.display = "flex";
      // Flip above the button when there is no room below (bottom corners,
      // play bars at the bottom of the window).
      const height = panel.getBoundingClientRect().height;
      if (rect.bottom + 4 + height > window.innerHeight - 4) {
        panel.style.top = `${Math.max(4, rect.top - height - 4)}px`;
      }
      panelOpen = true;
    }

    // A click anywhere outside the button/panel dismisses the panel. Events
    // inside the closed shadow root retarget to `host`, so this stays simple.
    document.addEventListener(
      "mousedown",
      (event) => {
        if (panelOpen && event.target !== host) hide();
      },
      { capture: true },
    );

    function scheduleHide() {
      clearTimeout(hideTimer);
      hideTimer = setTimeout(hide, 300);
    }

    function insideRect(event, rect) {
      return (
        rect !== null &&
        event.clientX >= rect.left - RECT_MARGIN &&
        event.clientX <= rect.right + RECT_MARGIN &&
        event.clientY >= rect.top - RECT_MARGIN &&
        event.clientY <= rect.bottom + RECT_MARGIN
      );
    }

    function showFor(anchor, url) {
      attachHost();
      const rect = anchor.isConnected ? anchor.getBoundingClientRect() : pendingRect;
      clearPending();
      if (rect === null) return; // anchor re-rendered away and we lost it
      currentUrl = url;
      currentRect = rect;
      const position = buttonPosition(rect, BUTTON_SIZE);
      button.style.left = `${position.left}px`;
      button.style.top = `${position.top}px`;
      button.style.display = "block";
      button.style.background = "#2563eb";
      button.textContent = "⬇";
    }

    document.addEventListener(
      "mouseover",
      (event) => {
        if (!enabled || !hoverGlobal || panelOpen || !(event.target instanceof Element)) return;
        let hit = null;
        try {
          hit = resolve(event.target);
        } catch {
          hit = null; // a matcher must never break the page
        }
        if (!hit) {
          // Pointer still inside the shown or pending target's box: the
          // "miss" is just an overlay/preview stealing the hover - hold on.
          if (insideRect(event, currentRect) || insideRect(event, pendingRect)) return;
          clearPending();
          if (currentUrl) scheduleHide();
          return;
        }
        clearTimeout(hideTimer);
        if (hit.url === currentUrl) return; // already shown for this target
        if (hit.url === pendingUrl) return; // dwell in progress - let it fire
        clearPending();
        pendingUrl = hit.url;
        pendingRect = hit.anchor.getBoundingClientRect();
        showTimer = setTimeout(() => showFor(hit.anchor, hit.url), SHOW_DELAY_MS);
      },
      { passive: true },
    );
    document.addEventListener("scroll", hide, { passive: true, capture: true });
    // Switching tab or window must not leave a stale button behind.
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) hide();
    });
    window.addEventListener("blur", hide);

    button.addEventListener("mouseenter", () => clearTimeout(hideTimer));
    button.addEventListener("mouseleave", () => {
      if (!panelOpen) scheduleHide();
    });
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!currentUrl) return;
      if (qualityPanel) {
        if (panelOpen) closePanel();
        else openPanel();
        return;
      }
      feedback(await api.runtime.sendMessage({ cmd: "grab", url: currentUrl }));
    });
  };
})();
