// Grabline Connect - background (MV3 service worker / Firefox event page).
//
// Deliberately thin and stateless: detect, decorate, deliver. Every download
// happens in the desktop app; this file only relays URLs over Native
// Messaging and keeps a small per-tab list of sniffed media in session
// storage (the service worker can die at any time - nothing lives here).

const api = globalThis.browser ?? globalThis.chrome;
const HOST_NAME = "dev.grabline.host";
const MENU_ID = "grabline-download";
const GALLERY_MENU_ID = "grabline-gallery";
const MAX_ITEMS_PER_TAB = 30;

// ---------------------------------------------------------------- native

async function sendToGrabline(url, tab, quality = null, fallbackUrls = []) {
  const message = {
    type: "download",
    url,
    pageUrl: tab?.url ?? null,
    pageTitle: tab?.title ?? null,
    source: "extension",
    quality,
    fallbackUrls,
  };
  try {
    const reply = await api.runtime.sendNativeMessage(HOST_NAME, message);
    await api.storage.session.set({ lastNativeError: null });
    if (reply?.type === "queued" && tab?.id != null) track(url, tab.id);
    return reply ?? { type: "error", message: "empty reply from host" };
  } catch (error) {
    const detail = error?.message ?? String(error);
    await api.storage.session.set({ lastNativeError: detail });
    return { type: "error", message: detail, notPaired: true };
  }
}

async function pingGrabline() {
  try {
    const reply = await api.runtime.sendNativeMessage(HOST_NAME, { type: "ping" });
    await api.storage.session.set({ lastNativeError: null });
    return reply;
  } catch (error) {
    const detail = error?.message ?? String(error);
    await api.storage.session.set({ lastNativeError: detail });
    return null;
  }
}

// ------------------------------------------------ progress tracking (F1.3)
// Every URL grabbed from a tab is polled over a persistent native-messaging
// port (the host answers straight from the jobs table) and the progress is
// forwarded to that tab's content script, which renders the pill. The open
// port keeps the service worker alive while downloads run; the tracked map
// is mirrored to storage.session so a worker restart picks it back up.

const TRACK_LIMIT = 20;
const TRACK_TTL_MS = 30 * 60 * 1000;
const FINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);
const tracked = new Map(); // url -> { tabId, addedAt }
let pollTimer = null;
let statusPort = null;

api.storage.session.get("trackedDownloads").then(({ trackedDownloads }) => {
  for (const [url, info] of trackedDownloads ?? []) tracked.set(url, info);
  if (tracked.size) schedulePoll();
});

function saveTracked() {
  void api.storage.session.set({ trackedDownloads: [...tracked.entries()] });
}

function track(url, tabId) {
  if (tracked.size >= TRACK_LIMIT && !tracked.has(url)) return;
  tracked.set(url, { tabId, addedAt: Date.now() });
  saveTracked();
  schedulePoll();
}

function schedulePoll() {
  if (pollTimer == null && tracked.size) pollTimer = setTimeout(pollStatus, 1000);
}

function statusPortFor() {
  if (!statusPort) {
    statusPort = api.runtime.connectNative(HOST_NAME);
    statusPort.onMessage.addListener(onStatusReply);
    statusPort.onDisconnect.addListener(() => {
      statusPort = null;
    });
  }
  return statusPort;
}

function stopPolling() {
  if (statusPort) {
    statusPort.disconnect();
    statusPort = null;
  }
}

function pollStatus() {
  pollTimer = null;
  const now = Date.now();
  for (const [url, info] of tracked) {
    if (now - info.addedAt > TRACK_TTL_MS) tracked.delete(url);
  }
  if (!tracked.size) {
    saveTracked();
    stopPolling();
    return;
  }
  try {
    statusPortFor().postMessage({ type: "status", urls: [...tracked.keys()] });
  } catch {
    statusPort = null;
    tracked.clear();
    saveTracked();
    return;
  }
  schedulePoll();
}

function onStatusReply(reply) {
  if (reply?.type !== "status") return;
  const byTab = new Map();
  let changed = false;
  for (const job of reply.jobs ?? []) {
    const info = tracked.get(job.url);
    if (!info) continue;
    if (FINAL_STATUSES.has(job.status)) {
      tracked.delete(job.url); // the final state still reaches the pill below
      changed = true;
    }
    const list = byTab.get(info.tabId) ?? [];
    list.push(job);
    byTab.set(info.tabId, list);
  }
  for (const [tabId, items] of byTab) {
    api.tabs.sendMessage(tabId, { cmd: "progress", items }).catch(() => {});
  }
  if (changed) saveTracked();
  if (!tracked.size) stopPolling();
}

// ----------------------------------------------------- context menu (F1.6)

api.runtime.onInstalled.addListener(() => {
  api.contextMenus.create({
    id: MENU_ID,
    title: "Download with Grabline",
    contexts: ["link", "image", "video", "audio", "page", "selection"],
  });
  api.contextMenus.create({
    id: GALLERY_MENU_ID,
    title: "Download all images with Grabline",
    contexts: ["page", "image"],
  });
});

// ---------------------------------------------------- gallery grab (F2.2)

async function sendGallery(tab) {
  if (!tab?.id) return;
  let reply = null;
  try {
    reply = await api.tabs.sendMessage(tab.id, { cmd: "collectImages" });
  } catch {
    return; // no content script on this page (browser UI, store pages …)
  }
  const urls = reply?.urls ?? [];
  if (!urls.length) return;
  try {
    await api.runtime.sendNativeMessage(HOST_NAME, {
      type: "gallery",
      urls,
      pageUrl: tab.url ?? null,
      pageTitle: tab.title ?? null,
    });
    await api.storage.session.set({ lastNativeError: null });
  } catch (error) {
    await api.storage.session.set({ lastNativeError: error?.message ?? String(error) });
  }
}

api.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === GALLERY_MENU_ID) {
    await sendGallery(tab);
    return;
  }
  if (info.menuItemId !== MENU_ID) return;
  const selected = (info.selectionText ?? "").trim();
  const url =
    info.linkUrl ??
    info.srcUrl ??
    (/^https?:\/\/\S+$/.test(selected) ? selected : null) ??
    info.pageUrl;
  if (url) await sendToGrabline(url, tab);
});

// ------------------------------------------------- network sniffer (F1.4)
// Observe-only webRequest (MV3 removed blocking; we never wanted it).

const MEDIA_CONTENT_TYPES =
  /^(video\/|audio\/|application\/(vnd\.apple\.mpegurl|x-mpegurl|dash\+xml))/i;
const MEDIA_URL_PATTERN = /\.(m3u8|mpd|mp4|webm|mkv|mp3|m4a|flac|ogg|opus|wav|mov)(\?|$)/i;
// Segment fetches (one every few seconds) would flood the list; the
// manifest is the useful thing to grab, so segments are skipped.
const SEGMENT_PATTERN = /\.(ts|m4s|aac)(\?|$)|(^video\/mp2t$)/i;

function headerValue(headers, name) {
  const found = (headers ?? []).find((h) => h.name.toLowerCase() === name);
  return found?.value ?? null;
}

function classify(details) {
  const contentType = (headerValue(details.responseHeaders, "content-type") ?? "").split(";")[0];
  const url = details.url;
  if (SEGMENT_PATTERN.test(url) || SEGMENT_PATTERN.test(contentType)) return null;
  const isManifest = /mpegurl|dash\+xml/i.test(contentType) || /\.(m3u8|mpd)(\?|$)/i.test(url);
  if (isManifest) return { kind: "stream" };
  if (MEDIA_CONTENT_TYPES.test(contentType) || MEDIA_URL_PATTERN.test(url)) {
    const length = Number(headerValue(details.responseHeaders, "content-length"));
    return { kind: contentType.startsWith("audio/") ? "audio" : "video", size: length || null };
  }
  return null;
}

async function recordMedia(tabId, item) {
  const key = `tab:${tabId}`;
  const stored = await api.storage.session.get(key);
  const items = stored[key] ?? [];
  if (items.some((existing) => existing.url === item.url)) return;
  items.unshift(item);
  await api.storage.session.set({ [key]: items.slice(0, MAX_ITEMS_PER_TAB) });
  updateBadge(tabId, Math.min(items.length, MAX_ITEMS_PER_TAB));
}

function updateBadge(tabId, count) {
  api.action.setBadgeText({ tabId, text: count ? String(count) : "" });
  api.action.setBadgeBackgroundColor({ tabId, color: "#2563eb" });
}

api.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (details.tabId < 0) return;
    const media = classify(details);
    if (!media) return;
    void recordMedia(details.tabId, {
      url: details.url,
      kind: media.kind,
      size: media.size ?? null,
      seenAt: Date.now(),
    });
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"],
);

api.tabs.onRemoved.addListener((tabId) => {
  void api.storage.session.remove(`tab:${tabId}`);
});

// Navigating a tab to a new page starts a fresh list.
api.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading" && changeInfo.url) {
    void api.storage.session.remove(`tab:${tabId}`);
    updateBadge(tabId, 0);
  }
});

// --------------------------------------------------- interception (F1.5)
// Off by default; toggle lives in the popup. chrome.downloads based - the
// download is cancelled after it starts and the app re-requests it.

const INTERCEPT_EXTENSIONS =
  /\.(mp4|mkv|webm|mov|avi|mp3|m4a|flac|wav|zip|rar|7z|iso|tar|gz|xz|pdf|exe|dmg|appimage)(\?|$)/i;

api.downloads.onCreated.addListener(async (item) => {
  const { intercept = false } = await api.storage.local.get("intercept");
  if (!intercept) return;
  if (!/^https?:/.test(item.url)) return;
  const name = item.filename || item.url;
  if (!INTERCEPT_EXTENSIONS.test(name)) return;
  try {
    await api.downloads.cancel(item.id);
    await api.downloads.erase({ id: item.id });
  } catch {
    return; // too late to take over; let the browser finish it
  }
  await sendToGrabline(item.finalUrl || item.url, null);
});

// ------------------------------------------------------------- messages

async function tabForMessage(sender, message) {
  if (sender.tab) return sender.tab;
  if (message.tabId == null) return null; // popup passes the active tab's id
  try {
    return await api.tabs.get(message.tabId);
  } catch {
    return null;
  }
}

// The streams/media the sniffer saw in a tab, best candidates first -
// attached as fallbacks when a blob-backed player forced a page-URL grab.
async function sniffedUrlsFor(tabId) {
  if (tabId == null) return [];
  const key = `tab:${tabId}`;
  const stored = await api.storage.session.get(key);
  const items = stored[key] ?? [];
  const streams = items.filter((item) => item.kind === "stream");
  const rest = items.filter((item) => item.kind !== "stream");
  return [...streams, ...rest].slice(0, 3).map((item) => item.url);
}

api.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.cmd === "grab") {
    (async () => {
      const tab = await tabForMessage(sender, message);
      const fallbackUrls = message.sniff ? await sniffedUrlsFor(tab?.id) : [];
      return sendToGrabline(message.url, tab, message.quality ?? null, fallbackUrls);
    })().then(sendResponse);
    return true; // async response
  }
  if (message?.cmd === "ping") {
    pingGrabline().then(sendResponse);
    return true;
  }
  return false;
});
