// Grabline Connect - toolbar popup (F1.4): pairing status, per-tab sniffed
// media list, interception and per-site overlay toggles.

const api = globalThis.browser ?? globalThis.chrome;

function humanBytes(count) {
  if (!count) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = count;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index ? 1 : 0)} ${units[index]}`;
}

// Generic stream/segment leaf names that carry no meaning - fall back to the
// page title for these (master.m3u8, videoplayback, a hex hash, ...).
const UGLY_LEAF =
  /^(master|index|playlist|manifest|chunklist|videoplayback|video|audio|media|stream|init|segment|seg|frag|output|dash|hls|prog)\b/i;

function cleanTitle(title) {
  // Drop a trailing " - YouTube" / " • Instagram" / " | Site" suffix.
  return (title || "")
    .replace(
      /\s*[-|•·—–]\s*(YouTube|Instagram|Vimeo|TikTok|Twitter|X|Facebook|Dailymotion|Twitch|SoundCloud|Reddit)\s*$/i,
      "",
    )
    .trim();
}

// A human name for a sniffed media item: the real filename when the URL has
// one, otherwise the page/video title (a movie stream's URL is usually a hash).
function mediaName(item, tab) {
  try {
    const leaf = decodeURIComponent(
      new URL(item.url).pathname.split("/").filter(Boolean).pop() || "",
    );
    const base = leaf.replace(/\.[a-z0-9]{2,4}$/i, "");
    const named = leaf && base.length >= 3 && !UGLY_LEAF.test(base) && !/^[0-9a-f]{12,}$/i.test(base);
    if (named) return leaf;
  } catch {
    /* unparsable URL - fall through to the title */
  }
  return cleanTitle(tab?.title) || item.kind || "media";
}

async function activeTab() {
  const [tab] = await api.tabs.query({ active: true, currentWindow: true });
  return tab ?? null;
}

async function renderStatus() {
  const status = document.getElementById("status");
  const help = document.getElementById("pairing-help");
  const reply = await api.runtime.sendMessage({ cmd: "ping" });
  if (!reply) {
    status.textContent = "not paired";
    status.className = "status bad";
    help.hidden = false;
  } else if (reply.appRunning) {
    status.textContent = "connected";
    status.className = "status ok";
  } else {
    status.textContent = "app not running";
    status.className = "status warn";
    status.title = "Downloads are queued and start when you open Grabline.";
  }
}

async function renderMediaList(tab) {
  const list = document.getElementById("media-list");
  const key = `tab:${tab.id}`;
  const stored = await api.storage.session.get(key);
  const all = stored[key] ?? [];
  if (!all.length) return;
  // Most-recent first (what's playing now), and only a handful - not the last
  // 20 reels you already scrolled past.
  const items = [...all].sort((a, b) => (b.seenAt ?? 0) - (a.seenAt ?? 0)).slice(0, 6);
  list.textContent = "";
  for (const item of items) {
    const row = document.createElement("li");
    const kind = document.createElement("span");
    kind.className = "kind";
    kind.textContent = item.kind;
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = mediaName(item, tab);
    name.title = item.url;
    const size = document.createElement("span");
    size.className = "size";
    size.textContent = humanBytes(item.size);
    const grab = document.createElement("button");
    grab.textContent = "Download";
    grab.addEventListener("click", async () => {
      grab.disabled = true;
      grab.textContent = "Sent ✓";
      const reply = await api.runtime.sendMessage({ cmd: "grab", url: item.url, tabId: tab.id });
      if (reply?.type === "error") {
        grab.textContent = "Failed";
        grab.disabled = false;
      }
    });
    row.append(kind, name, size, grab);
    list.appendChild(row);
  }
}

async function wireToggles(tab) {
  const intercept = document.getElementById("toggle-intercept");
  const hover = document.getElementById("toggle-hover");
  const overlay = document.getElementById("toggle-overlay");
  const images = document.getElementById("toggle-images");
  const { intercept: interceptOn = true } = await api.storage.local.get("intercept");
  intercept.checked = interceptOn;
  intercept.addEventListener("change", () => {
    void api.storage.local.set({ intercept: intercept.checked });
  });

  // Master switch for all hover buttons; when off, the per-site and images
  // toggles below it have nothing to act on, so grey them out.
  const { hoverButtons = true } = await api.storage.local.get("hoverButtons");
  hover.checked = hoverButtons;
  const reflectHover = () => {
    overlay.disabled = images.disabled = !hover.checked;
  };
  reflectHover();
  hover.addEventListener("change", () => {
    void api.storage.local.set({ hoverButtons: hover.checked });
    reflectHover();
  });

  const { overlayImages = false } = await api.storage.local.get("overlayImages");
  images.checked = overlayImages;
  images.addEventListener("change", () => {
    void api.storage.local.set({ overlayImages: images.checked });
  });

  const cornerSelect = document.getElementById("button-corner");
  const { buttonCorner = "top-right" } = await api.storage.local.get("buttonCorner");
  cornerSelect.value = buttonCorner;
  cornerSelect.addEventListener("change", () => {
    void api.storage.local.set({ buttonCorner: cornerSelect.value });
  });

  const hostname = tab?.url ? new URL(tab.url).hostname : null;
  if (!hostname) {
    overlay.disabled = true;
    return;
  }
  const { disabledSites = [] } = await api.storage.local.get("disabledSites");
  overlay.checked = !disabledSites.includes(hostname);
  overlay.addEventListener("change", async () => {
    const { disabledSites: current = [] } = await api.storage.local.get("disabledSites");
    const next = current.filter((site) => site !== hostname);
    if (!overlay.checked) next.push(hostname);
    await api.storage.local.set({ disabledSites: next });
  });
}

(async () => {
  const tab = await activeTab();
  await renderStatus();
  if (tab) await renderMediaList(tab);
  await wireToggles(tab);
})();
