// Grabline Connect — toolbar popup (F1.4): pairing status, per-tab sniffed
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

function shortName(url) {
  try {
    const parsed = new URL(url);
    const leaf = parsed.pathname.split("/").filter(Boolean).pop();
    return leaf || parsed.hostname;
  } catch {
    return url;
  }
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
  const items = stored[key] ?? [];
  if (!items.length) return;
  list.textContent = "";
  for (const item of items) {
    const row = document.createElement("li");
    const kind = document.createElement("span");
    kind.className = "kind";
    kind.textContent = item.kind;
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = shortName(item.url);
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
  const overlay = document.getElementById("toggle-overlay");
  const images = document.getElementById("toggle-images");
  const { intercept: interceptOn = false } = await api.storage.local.get("intercept");
  intercept.checked = interceptOn;
  intercept.addEventListener("change", () => {
    void api.storage.local.set({ intercept: intercept.checked });
  });

  const { overlayImages = false } = await api.storage.local.get("overlayImages");
  images.checked = overlayImages;
  images.addEventListener("change", () => {
    void api.storage.local.set({ overlayImages: images.checked });
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
