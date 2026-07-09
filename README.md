# Grabline

**The open-source download manager: a ⬇ button on any media, anywhere -
with a real quality picker where one exists, and IDM-grade segmented
downloading everywhere else.**

Paste a link or click the button in your browser - a YouTube video, a
SoundCloud track, a streaming lecture, a plain file - and Grabline downloads
it fast: a quality panel (4K → 144p, MP3/M4A with tags and cover art) on the
1000+ sites its Smart Engine knows, multi-connection resumable downloading
for everything else, and FFmpeg stream reassembly in between. Free, no ads,
no telemetry, AGPL-3.0.

## Highlights

- **One button in the browser** - hover ⬇ on videos and thumbnails (YouTube,
  YouTube Music, SoundCloud, Vimeo, X), pick the quality right on the page,
  watch a live progress pill in the corner. Right-click → *Download with
  Grabline* works on anything, everywhere.
- **Serious downloading** - up to 16 parallel connections per file,
  crash-proof checkpointed resume (survives kill -9 and power loss), a queue
  you can reorder and prioritize, pause/resume, per-download and global speed
  limits with a nightly "full speed" schedule, automatic reconnect with
  backoff, and auto-sorting into Video/Music/Images/Documents/Archives.
- **The whole yt-dlp toolbox, no terminal** - curated quality list with size
  estimates, MP3/M4A extraction with tags and cover art, subtitles (manual or
  auto, .srt or embedded), clip trimming, playlists with checkbox selection.
- **Streams** - HLS/DASH manifests are reassembled into clean .mp4 by FFmpeg,
  with master-playlist quality picking and automatic retry. The per-tab
  sniffer in the extension catches streams the page loads.
- **Extras** - download every image or every link on a page (thumbnail grid
  and a filterable link picker), convert any downloaded video to a GIF,
  import a whole list of links at once, grab URLs from the clipboard, a
  dark/light theme, dashboard tabs (Active / Completed / Failed), and start
  minimized in the tray on login.

---

## Install

### Windows

1. Download the latest `Grabline-windows.zip` from the
   [Releases page](https://github.com/Gr33nOps/Grabline/releases) and unzip.
2. Run `Grabline.exe`. If SmartScreen objects (the build is not code-signed),
   click *More info → Run anyway*.

### macOS

1. Download `Grabline-macos.zip` from the
   [Releases page](https://github.com/Gr33nOps/Grabline/releases) and unzip.
2. Move `Grabline.app` to Applications. First launch: **right-click → Open**
   (the build is not notarized), then confirm.

### Linux

1. Download `Grabline-linux.tar.gz` from the
   [Releases page](https://github.com/Gr33nOps/Grabline/releases), extract,
   and run `./Grabline`.
2. The first run adds Grabline to your application menu - launch it from
   there (or pin it to the dock) from then on.

### From source - Linux / macOS

Needs Python 3.12+ and git:

```bash
git clone https://github.com/Gr33nOps/Grabline.git && cd Grabline
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m app
```

### From source - Windows

Install Python from [python.org](https://www.python.org/downloads/) -
**not** the Microsoft Store (the Store build is sandboxed and hides the
browser-pairing files from your browsers; Grabline detects this and refuses).
Then, in PowerShell:

```powershell
git clone https://github.com/Gr33nOps/Grabline.git; cd Grabline
py -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m app
```

The `.venv\Scripts\python -m …` style needs no activation and is immune to
other Pythons on your PATH (MSYS2, Store aliases, and friends). If you have
several Pythons, pick one explicitly: `py -3.12 -m venv .venv`.

Debian/Ubuntu only: if the window doesn't appear
(*"Could not load the Qt platform plugin xcb"*), install Qt's system
libraries first: `sudo apt install libxcb-cursor0 libegl1 libxkbcommon0`.

---

## First-time setup (two minutes)

1. **FFmpeg** - open **Settings**. If FFmpeg shows *Not found*, click
   **Install FFmpeg**: Grabline downloads an official build over HTTPS and
   verifies it against pinned SHA-256 checksums before installing. (Needed
   for MP3 extraction, stream saving, and merging high qualities.)
2. **Pair your browsers** - in **Settings**, click **Pair browsers**. This
   registers Grabline with Chrome, Chromium, Edge, Brave, and Firefox in one
   click (per-user, no admin rights).
3. **Install the extension (Grabline Connect):**
   - **Chrome / Edge / Brave:** open `chrome://extensions`, enable
     *Developer mode*, click *Load unpacked*, and select the `extension/`
     folder. This install is permanent.
   - **Firefox:** see [extension/README.md](extension/README.md) - the
     short version: get the zip signed for free on addons.mozilla.org
     (unlisted) and install the resulting `.xpi` permanently, or use
     `about:debugging` → *Load Temporary Add-on* for a quick session-only try.
4. Click the Grabline toolbar icon - the popup should say **connected**.

Optional but recommended: in **Settings**, tick **"Start Grabline when I log
in"** - it will sit minimized in the tray, always ready for the browser,
exactly like IDM. Closing the window keeps it in the tray; *Quit* lives in
the tray menu.

---

## Everyday use

| You do | Grabline does |
|---|---|
| Hover a video or thumbnail → click **⬇** | In-page panel: Best / 1080p / 720p / 480p / MP3 / M4A - downloading starts immediately, a progress pill tracks it in the corner |
| Right-click anything → *Download with Grabline* | Link, image, video, audio, or the page itself - routed to the best engine |
| Right-click a page → *Download all images* | Every big-enough image in a checkable thumbnail grid |
| Click the toolbar icon | Everything the page's network traffic loaded - streams (.m3u8/.mpd) and media files, one click each |
| Paste a playlist URL | Fast listing → checkboxes → one quality for the batch |
| **Import Links** in the app | Paste anything with URLs in it (or load a .txt) - all of it queues at sensible defaults |
| Right-click a finished video row | Open it, open its folder, re-download - or **Convert to GIF…** with clip range, fps, and width |
| Copy a URL anywhere | An unobtrusive "Download with Grabline?" offer (can be turned off) |

Popup toggles: hover button on/off per site, hover button on images (off by
default), button position (any corner), download takeover (off by default).

## Music

SoundCloud, Bandcamp, YouTube Music, Mixcloud, and every other non-DRM
music site yt-dlp knows: hover ⬇ → MP3, tagged with cover art. Spotify
tracks, Apple Music, TIDAL, Deezer, and Amazon Music are **DRM-protected
and are refused with a clear message** - Grabline does not and will not
bypass DRM. (Spotify *podcasts* are not DRM-protected and download fine.)

## The CLI

The same engines, headless:

```bash
python -m app.cli "https://…" ~/Downloads --list-formats
python -m app.cli "https://…" ~/Downloads --quality 1080p
python -m app.cli "https://…" ~/Downloads --quality mp3
python -m app.cli "https://…/playlist" ~/Downloads --playlist --limit 10
```

## Honest limits

- **No DRM circumvention** - Netflix, Prime Video, Disney+, Spotify tracks
  and friends are refused with a clear message, not a workaround.
- **No login bypass** - the optional *"Use my browser session"* setting uses
  *your* login for *your* content; cookies are read per download, kept in
  memory only, never stored or transmitted.
- You are responsible for the terms of service of the sites you use and for
  your local law.

## For developers

```
app/
├── core/       resolver, segmented downloader, queue manager, settings,
│               rate limiter, GIF tools, desktop integration, FFmpeg manager
├── engines/    smart.py (yt-dlp in-process) · hls.py (FFmpeg) · manifest.py
├── db/         SQLite: jobs, segment checkpoints, handoffs (WAL, crash-safe)
├── ui/         PySide6: queue window, quality/playlist/gallery panels, tray
├── native_host/ Native Messaging host + per-browser registration
└── tests/      failure-simulating media server, engine tests, kill -9 milestone
extension/      Grabline Connect (MV3, Chrome + Firefox, readable in a sitting)
packaging/      PyInstaller spec; installers built on release tags
scripts/        FFmpeg pin updater, extension store packaging
```

Run what CI runs: `ruff check . && ruff format --check . && mypy app && pytest`
(200 tests, including an 8-connection download killed with SIGKILL and
resumed to a verified checksum). Security ground rules: no `shell=True`
anywhere (CI-enforced), Native Messaging only - never an open port, FFmpeg
fetched only against pinned checksums.

Store packaging for the extension: `python scripts/package_extension.py`
builds Chrome Web Store and Firefox (AMO) zips; the listing kit lives in
[docs/store-listing.md](docs/store-listing.md).

## License

[AGPL-3.0](LICENSE). yt-dlp (Unlicense) and PySide6 (LGPL) are compatible
dependencies; FFmpeg is fetched by the user's machine on first run and never
distributed with releases. Privacy: [PRIVACY.md](PRIVACY.md) - nothing is
collected, ever.
