# Grabline

**A fast, free, open-source download manager - the modern, cross-platform
answer to IDM. Accelerated multi-connection downloads, a real browser button,
and a proper quality picker for video and audio, all in one app.**

Grabline downloads everything: a plain file, a 4K video, a whole folder of
links, a streaming lecture. Point it at a URL - paste it, drop it on the
window, or click the ⬇ button in your browser - and it downloads fast with up
to 16 accelerated connections, crash-proof resume, and a queue you actually
control. On the 1000+ sites it knows (YouTube, SoundCloud and friends) you
also get a quality panel: 4K → 144p, MP3/M4A with tags and cover art,
subtitles, and clip trimming. Windows, macOS, and Linux. No ads, no
telemetry, no paid tier. AGPL-3.0.

## Why Grabline

A real download-accelerator core, a browser button that just works, and the
video/audio tooling of yt-dlp - without the terminal, the ads, or the price.

**Accelerated engine**
- Up to 16 parallel connections per file, with **dynamic segmentation** -
  free connections steal work from the slowest one so no thread sits idle.
- **Crash-proof resume**: checkpointed to survive kill -9 and power loss.
- Global **and** per-download speed limits, plus a nightly "full speed" window.
- Automatic reconnect with exponential backoff; optional HTTP/SOCKS **proxy**.

**A queue you control**
- Reorder and prioritize, pause/resume/cancel, dashboard tabs
  (Active / Completed / Failed), search, a live speed graph.
- **Timed schedule**: only download between the hours you choose (run it
  overnight), and *notify / quit / sleep / shut down* when the queue finishes.
- Auto-sort into Video / Music / Images / Documents / Archives.
- Import/export your download list; back it up or move it to another machine.

**One button in the browser** (Chrome / Edge / Brave / Firefox)
- Hover ⬇ on videos and thumbnails (YouTube, YouTube Music, SoundCloud,
  Vimeo, X), pick the quality right on the page, watch a live progress pill.
- Right-click → *Download with Grabline* on anything. **Grab all links** or
  **all images** on a page, or crawl a whole site a few levels deep.
- A per-tab sniffer catches the streams a page loads. Native Messaging only -
  no open ports, no localhost server.

**Video & audio done right** (1000+ sites, powered by yt-dlp, no terminal)
- Quality picker 4K → 144p with size estimates, **MP3/M4A** with tags and
  cover art, subtitles (manual or auto, .srt or embedded), clip trimming,
  and playlists with checkbox selection.
- HLS/DASH streams reassembled into a clean .mp4 by FFmpeg, with quality
  picking and automatic retry.

**Nice touches**
- URL patterns like `file[1-100].jpg`, drag-and-drop URLs, checksum
  verification, auto-extract archives, video → GIF, a dark/light theme,
  start-minimized-in-the-tray on login, and an update check.

**Honest by design**: no DRM circumvention, no login bypass, no telemetry.

---

## Download & install

Grab the installer for your system from the
[**latest release**](https://github.com/Gr33nOps/Grabline/releases/latest)
— no Python needed. After installing, Grabline shows up in your
Start Menu / Spotlight / app grid like any other program, and pairs itself
with your browsers on first launch (then install the extension below).

| System | File | How |
|---|---|---|
| **Windows** | `Grabline-Setup-*.exe` | Run it → Grabline installs and appears in the Start Menu |
| **macOS** | `Grabline-*.dmg` | Open it, drag **Grabline** to Applications |
| **Linux** | `Grabline-*-x86_64.AppImage` | `chmod +x` it and run; it adds itself to your app grid |

> The installers are **not code-signed yet**, so the OS warns on first launch:
> - **Windows:** SmartScreen → *More info* → *Run anyway*.
> - **macOS:** right-click the app → *Open* → *Open* (or System Settings →
>   Privacy & Security → *Open Anyway*).
>
> This is normal for open-source apps without a paid signing certificate.

**Browser extension:** after installing the app, add **Grabline Connect**
(Firefox now; Chrome/Edge/Brave coming). See
[extension/README.md](extension/README.md). The app already registered the
native host, so the extension's popup should say *connected*.

## Install from source

Prefer to run from source? You need **Python 3.12+** and **git**.

### Linux / macOS

```bash
git clone https://github.com/Gr33nOps/Grabline.git && cd Grabline
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m app
```

The first launch adds Grabline to your application menu, so after that you can
start it from the app grid/dock (no terminal).

Debian/Ubuntu only: if the window doesn't appear
(*"Could not load the Qt platform plugin xcb"*), install Qt's system
libraries first: `sudo apt install libxcb-cursor0 libegl1 libxkbcommon0`.

### Windows

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

---

## First-time setup

The **Browser Setup** wizard opens on first launch (also under **File →
Browser Setup**) and does the browser side for you: it pairs the native host
with one click and stages the extension at a stable folder it shows you.

- **Chrome / Edge / Brave:** click *Open folder* in the wizard, then in
  `chrome://extensions` enable *Developer mode* → *Load unpacked* → pick that
  folder. Permanent. (Fully automatic install needs the Chrome Web Store; the
  free path is this one manual step.)
- **Firefox:** `about:debugging` → *Load Temporary Add-on* → `manifest.json`
  in that folder. A permanent install comes with the free
  [AMO signing](extension/README.md).

Then, for MP3/streams, open **Settings** and click **Install FFmpeg** if it
shows *Not found* (Grabline fetches an official build over HTTPS and verifies
a pinned SHA-256). Click the Grabline toolbar icon in the browser - the popup
should say **connected**.

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
| Right-click a page → *Download all images / all links* | Every image or file link on the page, in a checkable, filterable picker |
| Click the toolbar icon | Everything the page's network traffic loaded - streams (.m3u8/.mpd) and media files, one click each |
| Paste a playlist URL | Fast listing → checkboxes → one quality for the batch |
| **File → Grab Site…** | Crawl a page a few levels deep and pick from every file it finds |
| **File → Import / Export List** | Save your whole queue to a file, or restore it on another machine |
| **Import Links** in the app | Paste anything with URLs (or `file[1-100].jpg` patterns) - all of it queues |
| Drag a URL onto the window | Queued instantly |
| Right-click a finished row | Open it, open its folder, re-download, **verify checksum**, **extract**, or **Convert to GIF…** |
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
scripts/        FFmpeg pin updater, extension store packaging
```

Run what CI runs: `ruff check . && ruff format --check . && mypy app && pytest`
(225 tests, including an 8-connection download killed with SIGKILL and
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
