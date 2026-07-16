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
const LINKS_MENU_ID = "grabline-links";
const SELECTION_MENU_ID = "grabline-selection";
const MAX_ITEMS_PER_TAB = 12;

// ---------------------------------------------------------------- native

// The cookies a request to `url` would carry, as a Cookie header. Lets the app
// fetch a login-gated file that the browser could reach.
async function cookieHeaderFor(url) {
  try {
    const cookies = await api.cookies.getAll({ url });
    return cookies.map((c) => `${c.name}=${c.value}`).join("; ");
  } catch {
    return "";
  }
}

async function sendToGrabline(
  url,
  tab,
  { quality = null, fallbackUrls = [], credentials = false, title = null } = {},
) {
  const message = {
    type: "download",
    url,
    pageUrl: tab?.url ?? null,
    pageTitle: title ?? tab?.title ?? null,
    source: "extension",
    quality,
    fallbackUrls,
    referer: tab?.url ?? null,
    userAgent: navigator.userAgent,
    // Cookies only for file downloads (interception / right-click a link),
    // never for media grabs - yt-dlp handles logins its own way there.
    cookie: credentials ? await cookieHeaderFor(url) : "",
  };
  try {
    const reply = await api.runtime.sendNativeMessage(HOST_NAME, message);
    await api.storage.session.set({ lastNativeError: null });
    if (typeof reply?.appRunning === "boolean") noteAppRunning(reply.appRunning);
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
    if (typeof reply?.appRunning === "boolean") noteAppRunning(reply.appRunning);
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

function registerMenus() {
  // removeAll first so re-registration never trips "duplicate id" errors.
  api.contextMenus.removeAll(() => {
    void api.runtime.lastError; // ignore - removeAll on empty is fine
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
    api.contextMenus.create({
      id: LINKS_MENU_ID,
      title: "Download all links with Grabline",
      contexts: ["page"],
    });
    // Highlight part of a page, right-click: every link, image, and playing
    // media inside the selection goes to the app's checkable picker.
    api.contextMenus.create({
      id: SELECTION_MENU_ID,
      title: "Download selected links & media with Grabline",
      contexts: ["selection"],
    });
  });
}

// MV3 backgrounds restart often, and Firefox event pages drop menus with
// them - registering only on onInstalled made "Download with Grabline"
// vanish until a reinstall. Register on install, on browser startup, AND on
// every background evaluation.
api.runtime.onInstalled.addListener(registerMenus);
api.runtime.onStartup.addListener(registerMenus);
registerMenus();

// -------------------------------------------- collect images / links grab

async function sendCollection(tab, collectCmd, hostType) {
  if (!tab?.id) return;
  let reply = null;
  try {
    reply = await api.tabs.sendMessage(tab.id, { cmd: collectCmd });
  } catch {
    return; // no content script on this page (browser UI, store pages …)
  }
  const urls = reply?.urls ?? [];
  if (!urls.length) return;
  try {
    await api.runtime.sendNativeMessage(HOST_NAME, {
      type: hostType,
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
    await sendCollection(tab, "collectImages", "gallery");
    return;
  }
  if (info.menuItemId === LINKS_MENU_ID) {
    await sendCollection(tab, "collectLinks", "links");
    return;
  }
  if (info.menuItemId === SELECTION_MENU_ID) {
    await sendCollection(tab, "collectSelection", "links");
    return;
  }
  if (info.menuItemId !== MENU_ID) return;
  const selected = (info.selectionText ?? "").trim();
  const url =
    info.linkUrl ??
    info.srcUrl ??
    (/^https?:\/\/\S+$/.test(selected) ? selected : null) ??
    info.pageUrl;
  // A right-clicked link may be a login-gated file, so pass cookies along.
  if (url) await sendToGrabline(url, tab, { credentials: Boolean(info.linkUrl) });
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
  // Name the media by what the tab is showing right now - the URL leaf of a
  // stream is usually a meaningless hash, but the tab title is the video.
  try {
    const tab = await api.tabs.get(tabId);
    item.title = tab?.title || null;
  } catch {
    item.title = null;
  }
  const key = `tab:${tabId}`;
  const stored = await api.storage.session.get(key);
  // Dedupe by URL but move it back to the top with a fresh timestamp: media
  // that's still being fetched (the reel you're watching, the stream that's
  // playing) stays current, while things you scrolled past sink and fall off
  // the small cap - so the list reflects what's playing now, not a history.
  const items = (stored[key] ?? []).filter((existing) => existing.url !== item.url);
  items.unshift(item);
  const trimmed = items.slice(0, MAX_ITEMS_PER_TAB);
  await api.storage.session.set({ [key]: trimmed });
  updateBadge(tabId, trimmed.length);
}

function updateBadge(tabId, count) {
  api.action.setBadgeText({ tabId, text: count ? String(count) : "" });
  api.action.setBadgeBackgroundColor({ tabId, color: "#0170fd" });
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
// On by default (toggle lives in the popup), but only fires when the app is
// running - see the listener below. chrome.downloads based: the download is
// cancelled the moment it starts and the app re-requests it.

function shouldIntercept(item) {
  // Take over every real download regardless of type (exe, torrent, any
  // extension) - true IDM behavior. The only ones we must leave alone are
  // URLs the app can't re-fetch: blob:/data:/filesystem: downloads are
  // generated in the page and exist only inside the browser, and a
  // browser-initiated download URL (item.finalUrl) beats the shelf's url.
  const url = item.finalUrl || item.url || "";
  return /^https?:/i.test(url);
}

// While we're taking downloads over, hide Chromium's download shelf/bubble so
// the intercepted download doesn't flash in the browser UI before Grabline
// picks it up. Feature-detected: needs the downloads.ui/downloads.shelf
// permissions (present in the Chrome store build; a no-op on Firefox, which
// has neither API - a momentary flash there is unavoidable with the
// downloads-API takeover). Re-shown whenever interception is off or the app
// isn't running, so native browser downloads stay visible.
let lastAppRunning = false;

async function updateDownloadUi() {
  const { intercept = true } = await api.storage.local.get("intercept");
  const visible = !(intercept && lastAppRunning);
  try {
    if (api.downloads.setUiOptions) await api.downloads.setUiOptions({ enabled: visible });
    else if (api.downloads.setShelfEnabled) api.downloads.setShelfEnabled(visible);
  } catch {
    /* permission not granted in this build - keep the browser UI as is */
  }
}

function noteAppRunning(running) {
  if (running !== lastAppRunning) {
    lastAppRunning = running;
    void updateDownloadUi();
  }
}

api.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.intercept) void updateDownloadUi();
});

api.downloads.onCreated.addListener(async (item) => {
  // On by default, but only take a download away from the browser when the
  // Grabline app is actually running to receive it - otherwise the file would
  // just vanish. If the app is off, the browser download proceeds normally.
  const { intercept = true } = await api.storage.local.get("intercept");
  if (!intercept || !shouldIntercept(item)) return;
  const pong = await pingGrabline();
  if (!pong || !pong.appRunning) return;
  try {
    await api.downloads.cancel(item.id);
    await api.downloads.erase({ id: item.id });
  } catch {
    return; // too late to take over; let the browser finish it
  }
  // A synthetic tab carries the referring page AND a human name: the page
  // title (the movie/video the user is looking at), else the filename the
  // browser had chosen. Without this the app only has the URL leaf, which on
  // CDNs is a random hash - the "downloads named random numbers" report.
  const [active] = await api.tabs.query({ active: true, lastFocusedWindow: true });
  const chosenName = (item.filename || "").split(/[\\/]/).pop() || null;
  await sendToGrabline(
    item.finalUrl || item.url,
    { url: item.referrer || active?.url || null, title: active?.title || chosenName },
    { credentials: true },
  );
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
      return sendToGrabline(message.url, tab, {
        quality: message.quality ?? null,
        fallbackUrls,
        title: message.title ?? null,
      });
    })().then(sendResponse);
    return true; // async response
  }
  if (message?.cmd === "ping") {
    pingGrabline().then(sendResponse);
    return true;
  }
  return false;
});
