# Grabline Connect

The thin, auditable browser extension (MV3, one codebase for Chrome / Edge /
Brave / Firefox). It detects, decorates, and delivers — **every download,
merge, and conversion happens in the desktop app.** The whole extension is
readable in one sitting; that is a design goal.

## What it does

- **Right-click → "Download with Grabline"** on any link, image, video,
  audio, selection, or page (F1.6)
- **Hover ⬇ button** on videos, audio, and images ≥ 200×200 (F1.2);
  per-site off switch in the popup
- **Toolbar popup** with everything the network sniffer saw in this tab —
  streams (.m3u8/.mpd) and media files, one-click download each (F1.4)
- **Optional download takeover** (off by default): browser downloads of
  media/archive types are cancelled and re-dispatched to Grabline for
  segmented downloading (F1.5)

It talks to the desktop app over **Native Messaging only** — the browser
launches Grabline's host process and pipes JSON over stdio. There is no
localhost server and no open port, and the host manifests pin the extension
IDs allowed to connect (S3).

## Pairing (two steps)

1. **Register the native host** (writes per-browser manifest files):

   ```bash
   python -m app.native_host.install
   ```

2. **Load the extension:**
   - **Chrome / Edge / Brave:** `chrome://extensions` → enable *Developer
     mode* → *Load unpacked* → select this `extension/` folder. The manifest
     pins a stable ID, so pairing works no matter where the folder lives.
   - **Firefox:** `about:debugging#/runtime/this-firefox` → *Load Temporary
     Add-on* → select `extension/manifest.json`.

Open the toolbar popup: it should say **connected**. If it says *not paired*,
re-run step 1 and reload the extension. If it says *app not running*, that's
fine — handed-off URLs queue in the database and the app picks them up the
moment it starts.

## How a URL travels

```
right-click / ⬇ / popup → background.js → Native Messaging host
    → handoffs table (SQLite) → desktop app polls → resolver
    → quality panel (Smart Engine) or straight into the queue
```

## Still to come in this phase

- YouTube site module: thumbnail/player-bar buttons + in-page quality panel
  (F1.3) — isolated in `content/sites/youtube/` when it lands
- Playlist selection UI (F1.7)
