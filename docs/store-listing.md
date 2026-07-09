# Grabline Connect - store listing kit (F2.5)

Everything needed to submit the extension to the Chrome Web Store and
addons.mozilla.org. Build the upload zips first:

```bash
python scripts/package_extension.py     # → dist/grabline-connect-{chrome,firefox}-<version>.zip
```

## Identity

| | |
|---|---|
| Name | **Grabline Connect** |
| Category | Productivity → Tools (CWS) / Download Management (AMO) |
| Homepage | https://github.com/Gr33nOps/Grabline |
| Support | https://github.com/Gr33nOps/Grabline/issues |
| Privacy policy URL | https://github.com/Gr33nOps/Grabline/blob/main/PRIVACY.md |
| Firefox add-on ID | `grabline@grabline.dev` (pinned in the manifest) |

> The Chrome Web Store assigns the published extension a **new ID** (the
> store rejects manifests with a `key`). After first publication, add the
> store-assigned ID to `CHROME_EXTENSION_IDS` in `app/native_host/__init__.py`
> and re-run `python -m app.native_host.install`, so paired hosts accept it.

## Summary (short description)

> The connector for the Grabline download manager: right-click download,
> hover ⬇ buttons on media, quality picking for 1000+ sites - every download
> runs in the open-source desktop app, not the browser.

## Description (long)

> Grabline Connect pairs your browser with **Grabline**, the free and
> open-source download manager (AGPL-3.0). The extension is deliberately
> thin - it detects and delivers, the desktop app downloads:
>
> - **Right-click → "Download with Grabline"** on any link, image, video, or page
> - **Hover ⬇ button** on videos, audio, and large images
> - **Per-tab media list**: every stream (.m3u8/.mpd) and media file the page loaded
> - **Download all images** on a page into a selection grid
> - **Optional download takeover** (off by default)
>
> On sites the Smart Engine knows (YouTube and 1000+ more), the app opens a
> quality panel: 4K → 144p, MP3/M4A extraction, subtitles, clip trimming.
> Everywhere else you get segmented, resumable multi-connection downloading.
>
> **Requires the free Grabline desktop app** (Windows/macOS/Linux):
> https://github.com/Gr33nOps/Grabline - the extension talks to it over
> Native Messaging only. No account, no cloud, no telemetry, no ads.
>
> Grabline does not bypass DRM or logins.

## Permission justifications

| Permission | Why |
|---|---|
| `nativeMessaging` | The single purpose of the extension: hand URLs to the local Grabline app. Nothing else can do this. |
| `contextMenus` | The "Download with Grabline" / "Download all images" right-click entries. |
| `storage` | User toggles (per-site overlay off-switch, interception opt-in) and the per-tab sniffed-media list (`storage.session`, gone when the tab closes). |
| `webRequest` + `<all_urls>` | Observe-only response headers to list a tab's media/streams in the popup. No request is modified or blocked; nothing leaves the browser. |
| `downloads` | The **opt-in** takeover feature cancels a starting browser download and re-dispatches it to the app. Off by default. |
| `tabs` | Page URL/title accompany a handed-off URL so the app can name files sensibly. |
| Content scripts on `<all_urls>` | The hover ⬇ button and the image collector must run where the media is. They render one button in a closed shadow root and send nothing anywhere except the local app. |

**Single purpose statement (CWS):** connect the browser to the locally
installed Grabline download manager.

**Data use disclosures:** the extension collects nothing, transmits nothing
off-device, and has no remote code. All traffic is stdio to the local native
host. See PRIVACY.md.

## Reviewer notes (AMO "notes to reviewer" / CWS review field)

> This extension requires its native-host counterpart, the open-source
> Grabline desktop app: https://github.com/Gr33nOps/Grabline
> Install: `pip install -e .` then `python -m app.native_host.install`
> (registers the Native Messaging manifest), then load the extension.
> Without the app, the extension idles with a "not paired" popup status.
> The whole source is in the repo above; the zip is built unminified by
> `scripts/package_extension.py`.

## Assets still needed before submission

- [ ] 1-5 screenshots, 1280×800 (queue window + quality panel + popup)
- [ ] CWS promo tile 440×280 (optional but recommended)
- [ ] Developer accounts: CWS one-time $5, AMO free
