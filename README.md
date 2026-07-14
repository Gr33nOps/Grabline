<div align="center">

<img src="extension/icons/icon128.png" width="104" height="104" alt="Grabline logo" />

# Grabline

**The modern, cross-platform, open-source answer to IDM.**

Accelerated multi-connection downloads · a real browser button · a full quality picker for video & audio.

[![Download][download-badge]][releases]
[![License: AGPL-3.0][license-badge]][license]
![Platforms][platform-badge]
![Python][python-badge]
[![Tests][ci-badge]][ci]

### [⬇&nbsp; Download for Windows · macOS · Linux][releases]

[Website](https://gr33nops.github.io/Grabline/) · [Features](#-why-grabline) · [Install](#-download--install) · [Everyday use](#-everyday-use) · [Browser extension](extension/README.md)

<!-- Tip: drop a screenshot at docs/screenshots/queue.png and uncomment the line below -->
<!-- <img src="docs/screenshots/queue.png" width="840" alt="Grabline queue window" /> -->

</div>

[releases]: https://github.com/Gr33nOps/Grabline/releases/latest
[license]: LICENSE
[ci]: https://github.com/Gr33nOps/Grabline/actions/workflows/ci.yml
[download-badge]: https://img.shields.io/github/v/release/Gr33nOps/Grabline?label=Download&color=2ea44f&sort=semver
[license-badge]: https://img.shields.io/badge/License-AGPL--3.0-blue
[platform-badge]: https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey
[python-badge]: https://img.shields.io/badge/Python-3.12%2B-3776ab
[ci-badge]: https://img.shields.io/github/actions/workflow/status/Gr33nOps/Grabline/ci.yml?branch=main&label=tests

---

Grabline downloads everything: a plain file, a 4K video, a whole folder of
links, a streaming lecture, a torrent, a file off your SFTP box. Point it at a
URL - paste it, drop it on the window, or click the ⬇ button in your browser -
and it downloads fast with accelerated connections, crash-proof resume, and a
queue you actually control. On the 1000+ sites it knows (YouTube, SoundCloud
and friends) you also get a quality panel: 4K → 144p, MP3/M4A/FLAC with tags
and cover art, subtitles, and clip trimming. Magnets, .torrent files, and
cloud (SFTP/FTP/S3/WebDAV + Drive/Dropbox share links) all open right in the
app. Windows, macOS, and Linux. No ads, no telemetry, no paid tier. AGPL-3.0.

## ✨ Why Grabline

A real download-accelerator core, a browser button that just works, and the
video/audio tooling of yt-dlp - without the terminal, the ads, or the price.

**Accelerated engine**
- Up to **128 parallel connections** per file (default 8), with **dynamic
  segmentation** - free connections steal work from the slowest one so no
  thread sits idle. Pin connections per download from its right-click menu.
- **HTTP/2** where the server offers it; IPv6 out of the box.
- **Crash-proof resume**: checkpointed to survive kill -9, power loss, and
  reboots; downloads keep retrying through internet drops and VPN reconnects.
- Global **and** per-download speed limits, plus a nightly "full speed" window.
- Smart reconnect: exponential backoff (or **retry forever**), error-aware -
  rate limits back off and retry, dead links (404) don't spin. If a page
  offered alternate streams, a failed URL **fails over to its mirrors**.
- Optional HTTP/SOCKS **proxy**.

**A queue manager, not just a queue**
- **Unlimited named queues / download groups**, each with its own rules:
  **sequential mode** (one at a time, in order), **parallel mode** with a
  per-queue cap, pause, its own **schedule window**, and a place in the
  running order (queue priorities).
- **Queue dependencies**: make queue B wait until queue A has finished - and
  per-download *Start after…* holds one file until another completes
  ("download B only after A finishes"). Cycles are detected and refused.
- **Category queues**: tie a queue to Video / Music / Documents / … and new
  downloads of that type join it automatically.
- Reorder and prioritize, pause/resume/cancel, dashboard tabs
  (Active / Completed / Failed), search, a live speed graph.
- **Scheduler**: only download between the hours you choose, on the days you
  choose (weekend-only works), *Start at…* a specific date and time per
  download, and a nightly full-speed window. **Battery mode** pauses on
  battery and resumes on AC; **wait-for-internet** resumes the instant the
  connection returns.
- **When it finishes**: notification, a completion sound, run your own
  command (the file's path is passed to it), and when the queue empties -
  quit / sleep / **hibernate** / shut down / **lock** the computer.
- Auto-sort into Video / Music / Images / Documents / Archives / Programs /
  Games / Torrents.
- Import/export your download list; back it up or move it to another machine.

**One button in the browser** (Chrome / Firefox / Edge / Brave / Vivaldi / Opera / Arc)
- Hover ⬇ on videos and thumbnails (YouTube, YouTube Music, SoundCloud,
  Vimeo, X), pick the quality right on the page, watch a live progress pill.
- Right-click → *Download with Grabline* on anything. **Grab all links**,
  **all images**, or just the **links & media inside your text selection** -
  or crawl a whole site a few levels deep.
- A per-tab sniffer catches the streams a page loads. Native Messaging only -
  no open ports, no localhost server.

**Video & audio done right** (1000+ sites, powered by yt-dlp, no terminal)
- Quality picker 4K → 144p with size estimates, **MP3/M4A/FLAC** with tags and
  cover art, subtitles (manual or auto, .srt or embedded), clip trimming,
  and playlists with checkbox selection.
- **SponsorBlock** (mark or cut sponsor/self-promo segments), keep chapter
  marks, save the thumbnail and full metadata (.info.json) as sidecars, and a
  cookies.txt field for login-gated or age-restricted videos.
- Sites yt-dlp has no dedicated extractor for still work: a best-effort
  page scrape finds embedded `<video>` / og:video / m3u8 media before
  Grabline gives up.
- HLS/DASH streams reassembled into a clean .mp4 by FFmpeg, with quality
  picking and automatic retry.

**Archive manager** (ZIP / TAR / GZIP / BZIP2 / XZ built in; RAR / 7Z via 7-Zip)
- Preview an archive's contents and extract only the files you pick.
- Extract automatically after download, with saved passwords tried in
  order - a password you type once is remembered for next time.
- Optional virus scan before extraction, using a scanner already on the
  machine (Windows Defender or ClamAV) - Grabline never pretends to scan
  when none is installed.

**Torrent client** (powered by libtorrent - the engine behind qBittorrent)
- Magnet links and .torrent files: paste them, click them on websites,
  double-click a downloaded .torrent, or drag one onto the window - all of
  it opens in Grabline (no need for a separate torrent app).
- DHT, Peer Exchange, and UPnP/NAT-PMP port mapping out of the box; web
  seeds honored automatically.
- Pick the save location and the files you want before it starts;
  sequential (stream-friendly) mode with first/last-piece priority lets a
  video play while it downloads.
- Seeding with a ratio limit (or forever, or off), a session upload cap,
  and the same bandwidth scheduler as every other download.
- Create your own torrents (trackers, web seeds, private flag), subscribe
  to RSS feeds that auto-queue matching releases, and search from the app
  via your preferred search site.

**Cloud & file servers**
- Paste an **sftp://, ftp://, ftps://, scp://, s3:// or webdav://** address
  (File → Add Cloud Download) and it downloads with resume - FTP `REST`,
  an SFTP seek, or an HTTP `Range`, whichever the protocol offers.
- Public **Google Drive / Dropbox / OneDrive / Nextcloud** share links,
  pasted into Add URL, are turned into direct downloads - full speed, no
  account needed.
- **Saved logins** for the credentialed protocols, kept in your OS keychain
  (Windows Credential Manager / macOS Keychain / Linux Secret Service);
  several accounts per host, the right one chosen automatically.
- **Download a whole remote folder** (FTP/SFTP/S3): list it, tick the files
  you want, queue them together.
- Honest about the rest: Mega and Proton Drive are end-to-end encrypted and
  iCloud has no public API, so Grabline says so instead of failing cryptically.

**File management**
- Smart filenames (junk like `videoplayback.mp4` becomes the page title),
  illegal characters stripped, and `file (1).bin` version numbering instead
  of silent overwrites.
- Your own rename rules (`find -> replace`) applied to every new download.
- Duplicate detection - adding a URL twice asks first, and *Find Duplicate
  Files* hash-compares finished downloads and deletes the extra copies
  (always keeping one).
- Favorite folders in the right-click *Move to* menu, plus per-download
  tags/labels and notes - both searchable from the search box.

**Download Inspector** (right-click → *Inspect…*, or File → *Inspect URL…*)
- Everything about a link from one live probe: the resolved **IP** and
  reverse DNS, the **CDN** (Cloudflare, CloudFront, Fastly, Akamai, …), the
  **server**, **MIME type**, **response time**, the full **HTTP headers** and
  **Set-Cookie**s, the **redirect chain**, the **TLS certificate** (issuer,
  validity, protocol, cipher), the job's **mirrors**, and the finished file's
  **SHA-256**.
- No telemetry: IP/DNS/CDN come from your own lookup - the address is never
  sent to a geo-location service.

**Live dashboard** (File → *Dashboard…*)
- **Current / average / peak** download speed, live **ETA**, and how many
  downloads are active.
- **Downloaded today / this week / this month / lifetime**, total files, and
  **per-server** and **per-category** breakdowns.
- Scrolling **graphs**: download speed, torrent upload, whole-machine network,
  CPU, and disk throughput.

**Security** (advisory - it warns, it never blocks or deletes)
- **Checksums** in MD5, SHA-1, SHA-256, SHA-512, and CRC32. Paste any of
  them into *Verify checksum* and Grabline figures out which and confirms it;
  *Security check* shows all five at once.
- **Virus scanning** using a scanner already on the machine (Windows Defender
  or ClamAV), plus optional **VirusTotal** (opt-in, your own API key, and only
  the file's hash is sent - never its contents).
- **HTTPS enforcement** (warn before an unencrypted-HTTP download) and
  optional **Safe Browsing** URL checks (opt-in, your own Google key).
  **TLS certificates are always validated** - a bad-cert HTTPS download fails
  on its own.
- Executables and installers get an extra heads-up. Everything here is a
  *heads-up*: a flagged file stays saved and usable, and **you decide** -
  because antivirus false positives are common and shouldn't cost you a file.

**Nice touches**
- URL patterns like `file[1-100].jpg`, drag-and-drop URLs, video → GIF,
  a dark/light theme, start-minimized-in-the-tray on login, and an update
  check.

**Honest by design**: no DRM circumvention, no login bypass, no telemetry
(the VirusTotal/Safe Browsing checks are opt-in and use *your* API keys).

---

## ⬇️ Download & install

Grab the installer for your system from the
[**latest release**](https://github.com/Gr33nOps/Grabline/releases/latest)
— no Python needed. After installing, Grabline shows up in your
Start Menu / Spotlight / app grid like any other program, and pairs itself
with your browsers on first launch (then install the extension below).

| System | File | How |
|---|---|---|
| **Windows** | `Grabline-Setup-*.exe` | Run it → Grabline installs and appears in the Start Menu |
| **macOS** | `Grabline-*.dmg` | Open it, drag **Grabline** to Applications |
| **Linux** | `Grabline-*-x86_64.AppImage` | `chmod +x` it and run; it adds itself to your app grid. No FUSE? Use the `.tar.gz` — extract and run `./grabline/grabline` |

> The installers are **not code-signed yet**, so the OS warns on first launch:
> - **Windows:** SmartScreen → *More info* → *Run anyway*.
> - **macOS:** right-click the app → *Open* → *Open* (or System Settings →
>   Privacy & Security → *Open Anyway*).
>
> This is normal for open-source apps without a paid signing certificate.

## 🚀 First run

Grabline sets itself up — no config files, no terminal:

1. **It pairs with your browsers automatically** on first launch.
2. The **Browser Setup** window (also under **File → Browser Setup**) shows a
   one-click **Add Grabline to \<your browser\>** button — click it, then click
   **Add** in the browser. Done. (The extension ships inside the app, so
   there's nothing to download separately.)
3. For MP3 and streams, open **Settings → Tools** and click **Install FFmpeg**
   if it says *Not found* — Grabline fetches an official build over HTTPS and
   verifies a pinned checksum.

The toolbar button's popup should say **connected**. Optional: in **Settings**,
tick **Start Grabline when I log in** so it waits in the tray, always ready —
like IDM.

## 🎯 Everyday use

| You do | Grabline does |
|---|---|
| Hover a video or thumbnail → click **⬇** | In-page panel: Best / 1080p / 720p / 480p / MP3 / M4A / FLAC - downloading starts immediately, a progress pill tracks it in the corner |
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
default), button position (any corner), download takeover (on by default - it only takes over while the app is running).

## 🎵 Music

SoundCloud, Bandcamp, YouTube Music, Mixcloud, and every other non-DRM
music site yt-dlp knows: hover ⬇ → MP3, tagged with cover art. Spotify
tracks, Apple Music, TIDAL, Deezer, and Amazon Music are **DRM-protected
and are refused with a clear message** - Grabline does not and will not
bypass DRM. (Spotify *podcasts* are not DRM-protected and download fine.)

## ⌨️ The CLI

The same engines, headless:

```bash
python -m app.cli "https://…" ~/Downloads --list-formats
python -m app.cli "https://…" ~/Downloads --quality 1080p
python -m app.cli "https://…" ~/Downloads --quality mp3
python -m app.cli "https://…/playlist" ~/Downloads --playlist --limit 10
```

## ⚖️ Honest limits

- **No DRM circumvention** - Netflix, Prime Video, Disney+, Spotify tracks
  and friends are refused with a clear message, not a workaround.
- **No login bypass** - the optional *"Use my browser session"* setting uses
  *your* login for *your* content; cookies are read per download, kept in
  memory only, never stored or transmitted.
- You are responsible for the terms of service of the sites you use and for
  your local law.

## 🧑‍💻 For developers

Run from source (Python 3.12+ and git):

```bash
git clone https://github.com/Gr33nOps/Grabline.git && cd Grabline
python3 -m venv .venv && source .venv/bin/activate   # Windows: py -m venv .venv
pip install -e .
python -m app
```

On Windows use Python from [python.org](https://www.python.org/downloads/), not
the Microsoft Store (its sandbox hides the browser-pairing files). On Debian/
Ubuntu, if the window doesn't appear:
`sudo apt install libxcb-cursor0 libegl1 libxkbcommon0`.

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
packaging/      PyInstaller spec + per-OS installers (Windows/macOS/Linux)
scripts/        FFmpeg pin updater, extension store packaging
```

Run what CI runs: `ruff check . && ruff format --check . && mypy app && pytest`
(401 tests, including an 8-connection download killed with SIGKILL and
resumed to a verified checksum). Security ground rules: no `shell=True`
anywhere (CI-enforced), Native Messaging only - never an open port, FFmpeg
fetched only against pinned checksums.

Store packaging for the extension: `python scripts/package_extension.py`
builds Chrome Web Store and Firefox (AMO) zips; the listing kit lives in
[docs/store-listing.md](docs/store-listing.md). Desktop installers for all
three OSes are built by GitHub Actions on a version tag - see
[packaging/README.md](packaging/README.md).

## 📄 License

[AGPL-3.0](LICENSE). yt-dlp (Unlicense) and PySide6 (LGPL) are compatible
dependencies; FFmpeg is fetched by the user's machine on first run and never
distributed with releases. Privacy: [PRIVACY.md](PRIVACY.md) - nothing is
collected, ever.
