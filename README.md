# Grabline

**The open-source IDM: a ⬇ button on any media, anywhere — with full quality
options where they exist, and universal sniffing everywhere else.**

Grabline is a free, open-source download manager. Hover over any video, image,
GIF, or audio on any page, click the button, and it downloads fast — with a
quality picker (4K → 144p, MP3/M4A) on the 1000+ sites the Smart Engine knows,
and IDM-grade segmented downloading everywhere else. No paid tier, no ads, no
telemetry.

> **Status: Phase 0 complete** — the download engine. The app is under active
> development; the extension ("Grabline Connect") arrives in a later phase.

## What works today (Phase 0)

- **Segmented downloader** (F0.1): every download is probed with a
  `Range: bytes=0-0` GET; servers that answer `206 Partial Content` get N
  parallel range connections (default 8) writing into a preallocated
  `.gl-part` file. Servers without range support fall back to a single
  connection, including unknown-length streams.
- **Crash-proof pause/resume** (F0.2): per-segment byte progress is
  checkpointed to SQLite (WAL). Kill the process with `kill -9` mid-download,
  relaunch, and it resumes where it left off — the final checksum matches.
  This is an automated test, not a claim:
  [`app/tests/test_crash_resume.py`](app/tests/test_crash_resume.py).
- **Queue** (F0.4): concurrency-limited queue (default 3) with pause / resume
  / cancel / retry, live speed, progress, system tray, close-to-tray.
- **Headless CLI**: `python -m app.cli <url> <dest_dir>` shares the exact same
  engine and database as the desktop app.
- **Safety by construction**: no `shell=True` anywhere (CI-enforced), no open
  network ports, filenames sanitized, existing files never overwritten
  (auto-rename), `.gl-part` suffix until the file is verified complete.

## Development setup

```bash
git clone <repo-url> && cd Grabline
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Run the desktop app:

```bash
python -m app
```

Download something headlessly:

```bash
python -m app.cli "https://example.com/file.bin" ~/Downloads
```

Run the checks CI runs:

```bash
ruff check . && ruff format --check . && mypy app && pytest
```

The test suite spins up a local HTTP server that simulates every failure mode
the segmenter must survive — no range support, redirects, mid-transfer
connection drops, unknown content length, throttled transfers — plus the
Phase 0 milestone test: an 8-connection download killed with SIGKILL,
relaunched, resumed, and checksum-verified.

## Architecture (Phase 0 slice)

```
app/
├── core/       segmented downloader, probe, queue manager, naming
├── db/         SQLite: jobs, segment checkpoints (WAL, crash-safe)
├── engines/    (Phase 1: yt-dlp Smart Engine, FFmpeg HLS reassembly)
├── ui/         PySide6 queue window + tray
└── tests/      failure-simulating server, engine tests, kill -9 milestone
extension/      (Phase 2: Grabline Connect, MV3)
packaging/      (Phase 1: PyInstaller installers)
```

## Roadmap

- **Phase 0 — the engine** ✅ segmented downloader, checkpointed resume, queue UI, CI
- **Phase 1 — MVP app**: yt-dlp Smart Engine with quality panel + MP3, FFmpeg
  fetch-on-first-run, clipboard watcher, categories, installers
- **Phase 2 — v1.0**: the browser extension — hover ⬇ buttons, Native
  Messaging, YouTube quality panel, download interception
- **Phase 3 — v2.0**: HLS/DASH robustness, gallery grid, GIF tools, store publication

## Honest limits

Grabline does not and will not bypass DRM (Netflix/Prime/etc. are refused with
a clear message) and does not bypass logins. You are responsible for the terms
of service of the sites you use and for your local law.

## License

[AGPL-3.0](LICENSE). yt-dlp (Unlicense) and PySide6 (LGPL) are compatible
dependencies; FFmpeg is fetched by the user's machine on first run and never
distributed with releases.
