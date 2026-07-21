<div align="center">

<img src="website/assets/logo.png" width="104" height="104" alt="GrabLine logo" />

# GrabLine

**A modern, cross-platform, open-source download manager. The IDM you can read the source of.**

Accelerated multi-connection downloads, a real browser button, and a full quality picker for video and audio.

[![Download][download-badge]][releases]
[![Firefox Add-on][amo-badge]][amo]
[![License: AGPL-3.0][license-badge]][license]
![Platforms][platform-badge]
[![Tests][ci-badge]][ci]

### [Download for Windows · macOS · Linux][releases]

**Browser extension:** [Firefox Add-ons][amo] (official), or pair Chrome/Edge/Brave from inside the app.

[Website](https://gr33nops.github.io/GrabLine/) · [Features](#what-you-get) · [Install](#download--install) · [Everyday use](#everyday-use) · [Extension docs](extension/README.md)

<!-- Add a screenshot at docs/screenshots/queue.png and uncomment the line below. A download manager should show its window. -->
<!-- <img src="docs/screenshots/queue.png" width="840" alt="GrabLine main window" /> -->

</div>

[releases]: https://github.com/Gr33nOps/GrabLine/releases/latest
[amo]: https://addons.mozilla.org/en-US/firefox/addon/grabline-connect/
[license]: LICENSE
[ci]: https://github.com/Gr33nOps/GrabLine/actions/workflows/ci.yml
[download-badge]: https://img.shields.io/github/v/release/Gr33nOps/GrabLine?label=Download&color=0170fd&sort=semver
[amo-badge]: https://img.shields.io/amo/v/grabline-connect?label=Firefox%20Add-on&color=ff7139
[license-badge]: https://img.shields.io/badge/License-AGPL--3.0-blue
[platform-badge]: https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey
[ci-badge]: https://img.shields.io/github/actions/workflow/status/Gr33nOps/GrabLine/ci.yml?branch=main&label=tests

---

GrabLine downloads everything: a plain file, a 4K video, a page full of links, a
streaming lecture, a torrent, a file off your SFTP box. Point it at a URL by
pasting it, dropping it on the window, or clicking the GrabLine button in your
browser.
It downloads fast, with many parallel connections, resume that survives a crash,
and a queue you actually control. On the 1000+ sites it understands (YouTube,
SoundCloud, and the rest) you also get a quality picker: 4K down to 144p,
MP3/M4A/FLAC with tags and cover art, subtitles, and clip trimming. Magnets,
`.torrent` files, and cloud sources (SFTP/FTP/S3/WebDAV plus Drive and Dropbox
share links) all open right in the app.

Windows, macOS, and Linux. **No ads, no telemetry, no paid tier.** AGPL-3.0.

## What you get

- **A real accelerator.** Up to 128 connections per file, dynamic segmentation,
  HTTP/2, resume that survives a crash, retry-forever reconnect, mirror failover.
- **A browser button that just works.** Hover a video and a small GrabLine logo
  button appears; click it and GrabLine opens a fast Download Info dialog: name,
  folder, category, and a quality choice. Everything travels over Native
  Messaging, with no open ports.
- **Video and audio without the terminal.** yt-dlp runs in-process: 4K to 144p,
  MP3/M4A/FLAC with cover art, subtitles, playlists, SponsorBlock.
- **Light on your machine.** About 1% CPU sitting idle, half a second to start.
  [The numbers](docs/performance.md).
- **A full torrent client.** libtorrent, the same engine as qBittorrent: magnets,
  DHT, sequential streaming, seeding ratios, RSS auto-queue.
- **Cloud and file servers.** SFTP/FTP/S3/WebDAV with resume; public Drive and
  Dropbox share links at full speed.
- **A queue manager, not just a queue.** Named queues with schedules, priorities,
  dependencies, and category auto-assign.
- **Scheduling, bandwidth, and power control.** Download windows, per-host caps,
  polite-mode auto-throttle, battery pause, shut down when done.
- **Advisory security, never patronizing.** The safety checks warn; they never
  block. A flagged file is still your file.

<details>
<summary><b>Accelerated engine</b></summary>

- Up to **128 parallel connections** per file (default 8), with **dynamic
  segmentation**: a free connection steals work from the slowest one, so no
  thread sits idle. Pin the connection count per download from its right-click
  menu.
- **HTTP/2** where the server offers it. IPv6 out of the box.
- **Resume that survives a crash.** Progress is checkpointed to survive `kill -9`,
  power loss, and reboots, and downloads keep retrying through internet drops and
  VPN reconnects.
- Smart reconnect with exponential backoff (or **retry forever**), error-aware:
  a rate limit backs off and retries, a dead 404 does not spin. If a page offered
  alternate streams, a failed URL **fails over to its mirrors**.

</details>

<details>
<summary><b>Network and bandwidth</b></summary>

- **Proxy for everything**, downloads and torrents alike: HTTP, HTTPS, SOCKS5,
  and SOCKS4, with `user:pass@` auth.
- **Speed limits** at every level: global, per-download, **per-host** (cap a
  greedy server and every download from it shares one bucket), and time-based
  (a nightly full-speed window).
- **Automatic throttle**, or "polite mode": slow downloads while other apps are
  using the network, then speed back up when they stop.
- **VPN detection.** The dashboard shows when a tunnel (WireGuard, OpenVPN) is up.

</details>

<details>
<summary><b>A queue manager, not just a queue</b></summary>

- **Unlimited named queues**, each with its own rules: sequential mode (one at a
  time, in order), parallel mode with a per-queue cap, pause, its own schedule
  window, and a place in the running order.
- **Queue dependencies.** Make queue B wait until queue A finishes, and per
  download, hold one file with *Start after…* until another completes. Cycles are
  detected and refused.
- **Category queues.** Tie a queue to Video, Music, Documents, and new downloads
  of that type join it automatically.
- Reorder and prioritize, pause/resume/cancel, filter tabs (All, Active,
  Completed, Failed), search, and a live speed graph.
- **Scheduler.** Download only between the hours you choose, on the days you
  choose (weekend-only works), *Start at…* a specific date and time per download,
  and a nightly full-speed window. **Battery mode** pauses on battery and resumes
  on AC; **wait-for-internet** resumes the moment the connection returns.
- **When it finishes:** a notification, a completion sound, your own command (the
  file's path is passed to it), and when the queue empties, quit, sleep,
  hibernate, shut down, or lock the computer.
- Auto-sort into Video, Music, Images, Documents, Archives, Programs, Games, or
  Torrents.
- Import or export your download list to back it up or move it to another machine.

</details>

<details>
<summary><b>One button in the browser</b> (Firefox · Chrome · Edge · Brave · Vivaldi · Opera · Arc)</summary>

- **Firefox users install it from [Firefox Add-ons][amo]**, reviewed and signed
  by Mozilla. Other browsers pair from inside the app (Browser Setup).
- Hover a video or thumbnail (YouTube, YouTube Music, SoundCloud, Vimeo, X) and a
  small **GrabLine logo button** appears; click it and GrabLine opens its
  **Download Info dialog** to confirm the name, folder, and quality, then starts.
  Turn the dialog off to start immediately.
- Right-click → *Download with GrabLine* on anything. **Grab all links**, **all
  images**, or just the links and media inside your **text selection**, or crawl
  a whole site a few levels deep.
- A per-tab sniffer catches the streams a page loads. Native Messaging only: no
  open ports, no localhost server.

</details>

<details>
<summary><b>Video and audio done right</b> (1000+ sites, powered by yt-dlp)</summary>

- Quality picker from 4K to 144p with size estimates, **MP3/M4A/FLAC** with tags
  and cover art, subtitles (manual or auto, `.srt` or embedded), clip trimming,
  and playlists with checkbox selection.
- **SponsorBlock** (mark or cut sponsor and self-promo segments), keep chapter
  marks, save the thumbnail and full metadata (`.info.json`) as sidecars, and a
  `cookies.txt` field for login-gated or age-restricted videos.
- Sites yt-dlp has no dedicated extractor for still work: a best-effort page
  scrape finds embedded `<video>`, `og:video`, or m3u8 media before GrabLine
  gives up.
- **HLS/DASH streams the way IDM does it.** GrabLine fetches every segment and the
  decryption key with its own HTTP client, carrying the browser's headers, then
  remuxes the local files into a clean `.mp4`. A gated CDN that refuses FFmpeg's
  own requests still downloads.

</details>

<details>
<summary><b>Torrent client</b> (powered by libtorrent, the engine behind qBittorrent)</summary>

- Magnet links and `.torrent` files: paste them, click them on websites,
  double-click a downloaded `.torrent`, or drag one onto the window. All of it
  opens in GrabLine, with no separate torrent app.
- DHT, Peer Exchange, and UPnP/NAT-PMP port mapping out of the box; web seeds
  honored automatically.
- Pick the save location and the files you want before it starts. Sequential
  (stream-friendly) mode with first and last-piece priority lets a video play
  while it downloads.
- Seed with a ratio limit (or forever, or off), a session upload cap, and the
  same bandwidth scheduler as every other download.
- Create your own torrents (trackers, web seeds, private flag), subscribe to RSS
  feeds that auto-queue matching releases, and search from the app.

</details>

<details>
<summary><b>Cloud and file servers</b></summary>

- Paste an **sftp://, ftp://, ftps://, scp://, s3://, or webdav://** address
  (**Add Cloud** in the toolbar) and it downloads with resume, using FTP `REST`,
  an SFTP seek, or an HTTP `Range`, whichever the protocol offers.
- Public **Google Drive, Dropbox, OneDrive, and Nextcloud** share links, pasted
  into Add URL, become direct downloads at full speed, with no account needed.
- **Saved logins** for the credentialed protocols, kept in your OS keychain
  (Windows Credential Manager, macOS Keychain, Linux Secret Service). Several
  accounts per host, the right one chosen automatically.
- **Download a whole remote folder** (FTP/SFTP/S3): list it, tick the files you
  want, queue them together.
- Honest about the rest: Mega and Proton Drive are end-to-end encrypted and iCloud
  has no public API, so GrabLine says so instead of failing cryptically.

</details>

<details>
<summary><b>Archive manager</b> (ZIP / TAR / GZIP / BZIP2 / XZ built in; RAR / 7Z via 7-Zip)</summary>

- Preview an archive's contents and extract only the files you pick.
- Extract automatically after download, with saved passwords tried in order. A
  password you type once is remembered for next time.
- Optional virus scan before extraction, using a scanner already on the machine
  (Windows Defender or ClamAV). GrabLine never pretends to scan when none is
  installed.

</details>

<details>
<summary><b>File management</b></summary>

- Smart filenames: junk like `videoplayback.mp4` becomes the page title, illegal
  characters are stripped, and `file (1).bin` version numbering replaces silent
  overwrites.
- Your own rename rules (`find → replace`) applied to every new download.
- Duplicate detection: adding a URL twice asks first, and *Find Duplicate Files*
  hash-compares finished downloads and deletes the extra copies, always keeping
  one.
- Favorite folders in the right-click *Move to* menu, plus per-download tags and
  notes, both searchable from the search box.

</details>

<details>
<summary><b>Download Inspector</b> (right-click → <i>Inspect…</i>)</summary>

- Everything about a link from one live probe: the resolved **IP** and reverse
  DNS, the **CDN** (Cloudflare, CloudFront, Fastly, Akamai), the **server**,
  **MIME type**, **response time**, the full **HTTP headers** and **Set-Cookie**s,
  the **redirect chain**, the **TLS certificate** (issuer, validity, protocol,
  cipher), the job's **mirrors**, and the finished file's **SHA-256**.
- No telemetry: IP, DNS, and CDN come from your own lookup. The address is never
  sent to a geo-location service.

</details>

<details>
<summary><b>Live dashboard</b> (in the sidebar)</summary>

- **Current, average, and peak** download speed, live **ETA**, and how many
  downloads are active.
- **Downloaded today, this week, this month, lifetime**, total files, and
  **per-server** and **per-category** breakdowns.
- Scrolling **graphs**: download speed, torrent upload, whole-machine network,
  CPU, and disk throughput.

</details>

<details>
<summary><b>Security</b> (advisory: it warns, it never blocks or deletes)</summary>

- **Checksums** in MD5, SHA-1, SHA-256, SHA-512, and CRC32. Paste any of them into
  *Verify checksum* and GrabLine figures out which one it is and confirms it.
  *Security check* shows all five at once.
- **Virus scanning** using a scanner already on the machine (Windows Defender or
  ClamAV), plus optional **VirusTotal** (opt-in, your own API key, and only the
  file's hash is sent, never its contents).
- **HTTPS enforcement** (a warning before an unencrypted-HTTP download) and
  optional **Safe Browsing** URL checks (opt-in, your own Google key). **TLS
  certificates are always validated**, so a bad-cert HTTPS download fails on its
  own.
- Executables and installers get an extra heads-up. Everything here is a
  heads-up: a flagged file stays saved and usable, and **you decide**, because
  antivirus false positives are common and should not cost you a file.

</details>

<details>
<summary><b>The interface</b></summary>

- Sidebar navigation: **Downloads**, a live **Dashboard**, the **Queue Manager**,
  and **Settings**, all embedded pages rather than a maze of dialogs.
- Settings organized into 18 searchable sections, from General to About.
- A **details drawer** with a live speed graph for the selected download.
- Speed readouts and progress bars that glide instead of strobing, a shared 60fps
  animation clock that idles when nothing moves, and instant light/dark switching
  from the sidebar.
- URL patterns like `file[1-100].jpg`, drag-and-drop URLs, video to GIF,
  start-minimized-in-the-tray on login, and an update check.

</details>

**Honest by design:** no DRM circumvention, no login bypass, no telemetry. The
VirusTotal and Safe Browsing checks are opt-in and use *your* API keys.

---

## Download & install

Grab the installer for your system from the
[**latest release**](https://github.com/Gr33nOps/GrabLine/releases/latest). No
Python needed. After installing, GrabLine shows up in your Start menu, Spotlight,
or app grid like any other program, and pairs itself with your browsers on first
launch.

| System | File | How |
|---|---|---|
| **Windows** | `Grabline-Setup-*.exe` | Run it, and GrabLine installs and appears in the Start menu. No admin rights? Take the `*-windows-portable.zip` instead. |
| **macOS** | `Grabline-*-applesilicon.dmg` | Open it, drag **GrabLine** to Applications. Apple Silicon (M1 and later). |
| **Linux** | `grabline_*_amd64.deb` | `sudo apt install ./grabline_*_amd64.deb` on Debian, Ubuntu, Mint. |
| **Linux (any distro)** | `Grabline-*-x86_64.AppImage` | `chmod +x` it and run; it adds itself to your app grid. No FUSE? Use the `.tar.gz`: extract and run `./grabline/grabline`. |

**[Full install guide →](docs/install.md)** covers the per-system steps, the exact
click-through for the unsigned-app warnings, where your data lives, and how to
uninstall.

Then add the browser extension:

| Browser | How |
|---|---|
| **Firefox** | Install **[GrabLine Connect from Firefox Add-ons][amo]**: one click, reviewed and signed by Mozilla. |
| **Chrome / Edge / Brave / others** | Open **Browser Setup** in the app (sidebar → ⋯ menu) and click **Add GrabLine to \<your browser\>**. The extension ships inside the app. |

> The installers are **not code-signed yet**, so the OS warns on first launch:
> - **Windows:** SmartScreen → *More info* → *Run anyway*.
> - **macOS:** right-click the app → *Open* → *Open* (or System Settings →
>   Privacy & Security → *Open Anyway*).
>
> This is normal for open-source apps without a paid signing certificate.

## First run

GrabLine sets itself up, with no config files and no terminal:

1. **It pairs with your browsers automatically** on first launch.
2. Install the extension: **Firefox** from [Firefox Add-ons][amo]; other browsers
   via **Browser Setup** (sidebar → ⋯ menu), one click there, then **Add** in the
   browser.
3. For MP3 and streams, open **Settings → Video Downloader** and click **Install
   FFmpeg** if it says *Not found*. GrabLine fetches an official build over HTTPS
   and verifies a pinned checksum.

The extension popup should say **connected**. Optional: in **Settings → General**,
tick **Start GrabLine when I log in** so it waits in the tray, always ready.

## Everyday use

| You do | GrabLine does |
|---|---|
| Hover a video or thumbnail → click the **GrabLine button** | Jumps to the front and opens a **Download Info dialog**: name, folder, category, and a quality choice (Best / 1080p / 720p / 480p / MP3 / M4A / FLAC). Hit **Start Download**, or **Download Later** to queue it paused. |
| Right-click anything → *Download with GrabLine* | Link, image, video, audio, or the page itself, routed to the best engine, with the same Download Info dialog. |
| Right-click a page → *Download all images / all links* | Every image or file link on the page, in a checkable, filterable picker. |
| Click the toolbar icon | Everything the page's network traffic loaded: streams (`.m3u8`/`.mpd`) and media files, one click each. |
| Paste a playlist URL | A fast listing, checkboxes, one quality for the batch. |
| ⋯ menu → **Grab Site…** | Crawl a page a few levels deep and pick from every file it finds. |
| ⋯ menu → **Import / Export List** | Save your whole queue to a file, or restore it on another machine. |
| ⋯ menu → **Import Links** | Paste anything with URLs (or `file[1-100].jpg` patterns) and all of it queues. |
| Drag a URL onto the window | Queued instantly. |
| Select a download | A details drawer: live speed graph, ETA, server, destination, quick actions. |
| Right-click a finished row | Open it, open its folder, re-download, **verify checksum**, **extract**, or **Convert to GIF…** |
| Copy a URL anywhere | An unobtrusive "Download with GrabLine?" offer (off by default). |

Prefer downloads to start without the dialog? Tick **Start downloads immediately**
in the dialog, or turn it off under **Settings → General**.

Popup toggles: hover button on or off per site, hover button on images (off by
default), button position (any corner), and download takeover (on by default, and
active only while the app is running).

## Music

SoundCloud, Bandcamp, YouTube Music, Mixcloud, and every other non-DRM music site
yt-dlp knows: hover, click the GrabLine button, choose MP3, and it downloads
tagged with cover art. Spotify
tracks, Apple Music, TIDAL, Deezer, and Amazon Music are **DRM-protected and are
refused with a clear message**. GrabLine does not and will not bypass DRM. (Spotify
*podcasts* are not DRM-protected and download fine.)

## The CLI

The same engines, headless:

```bash
python -m app.cli "https://…" ~/Downloads --list-formats
python -m app.cli "https://…" ~/Downloads --quality 1080p
python -m app.cli "https://…" ~/Downloads --quality mp3
python -m app.cli "https://…/playlist" ~/Downloads --playlist --limit 10
```

## Honest limits

- **No DRM circumvention.** Netflix, Prime Video, Disney+, Spotify tracks, and the
  rest are refused with a clear message, not a workaround.
- **No login bypass.** The optional *"Use my browser session"* setting uses *your*
  login for *your* content; cookies are read per download, kept in memory only,
  and never stored or transmitted.
- You are responsible for the terms of service of the sites you use and for your
  local law.

## For developers

Run from source (Python 3.12+ and git):

```bash
git clone https://github.com/Gr33nOps/GrabLine.git && cd GrabLine
python3 -m venv .venv && source .venv/bin/activate   # Windows: py -m venv .venv
pip install -e .
python -m app
```

On Windows, use Python from [python.org](https://www.python.org/downloads/), not
the Microsoft Store (its sandbox hides the browser-pairing files). On Debian or
Ubuntu, if the window does not appear:
`sudo apt install libxcb-cursor0 libegl1 libxkbcommon0`.

```
app/
├── core/        resolver, segmented downloader, queue manager, settings,
│                rate limiter, GIF tools, desktop integration, FFmpeg manager
├── engines/     smart.py (yt-dlp in-process) · hls.py (native segment fetch +
│                FFmpeg remux) · manifest.py
├── db/          SQLite: jobs, segment checkpoints, handoffs (WAL, crash-safe)
├── ui/          PySide6: design system, sidebar shell, embedded pages, panels
├── native_host/ Native Messaging host + per-browser registration
└── tests/       failure-simulating media server, engine tests, kill -9 milestone
extension/       GrabLine Connect (MV3, Chrome + Firefox, readable in a sitting)
packaging/       PyInstaller spec + per-OS installers (Windows/macOS/Linux)
scripts/         FFmpeg pin updater, extension store packaging
```

Run what CI runs: `ruff check . && ruff format --check . && mypy app && pytest`
(420+ tests, including an 8-connection download killed with SIGKILL and resumed to
a verified checksum). Security ground rules: no `shell=True` anywhere
(CI-enforced), Native Messaging only (never an open port), and FFmpeg fetched only
against pinned checksums.

Store packaging for the extension: `python scripts/package_extension.py` builds
Chrome Web Store and Firefox (AMO) zips. The Firefox one is [live on AMO][amo];
the listing kit lives in [docs/store-listing.md](docs/store-listing.md). Desktop
installers for all three systems are built by GitHub Actions on a version tag; see
[packaging/README.md](packaging/README.md).

## License

[AGPL-3.0](LICENSE). yt-dlp (Unlicense) and PySide6 (LGPL) are compatible
dependencies; FFmpeg is fetched by the user's machine on first run and never
distributed with releases. Privacy: [PRIVACY.md](PRIVACY.md). Nothing is
collected, ever.
