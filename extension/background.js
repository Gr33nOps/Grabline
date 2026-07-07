// Grabline Connect — background (MV3 service worker / Firefox event page).
//
// Deliberately thin and stateless: detect, decorate, deliver. Every download
// happens in the desktop app; this file only relays URLs over Native
// Messaging and keeps a small per-tab list of sniffed media in session
// storage (the service worker can die at any time — nothing lives here).

const api = globalThis.browser ?? globalThis.chrome;
const HOST_NAME = "dev.grabline.host";
const MENU_ID = "grabline-download";
const MAX_ITEMS_PER_TAB = 30;

// ---------------------------------------------------------------- native

async function sendToGrabline(url, tab) {
  const message = {
    type: "download",
    url,
    pageUrl: tab?.url ?? null,
    pageTitle: tab?.title ?? null,
    source: "extension",
  };
  try {
    const reply = await api.runtime.sendNativeMessage(HOST_NAME, message);
    await api.storage.session.set({ lastNativeError: null });
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

// ----------------------------------------------------- context menu (F1.6)

api.runtime.onInstalled.addListener(() => {
  api.contextMenus.create({
    id: MENU_ID,
    title: "Download with Grabline",
    contexts: ["link", "image", "video", "audio", "page", "selection"],
  });
});

api.contextMenus.onClicked.addListener(async (info, tab) => {
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
// Off by default; toggle lives in the popup. chrome.downloads based — the
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

api.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.cmd === "grab") {
    sendToGrabline(message.url, sender.tab).then(sendResponse);
    return true; // async response
  }
  if (message?.cmd === "ping") {
    pingGrabline().then(sendResponse);
    return true;
  }
  return false;
});
