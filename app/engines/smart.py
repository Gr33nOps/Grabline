"""The Smart Engine (F0.3): yt-dlp in-process, behind the resolver.

Three responsibilities:
- ``SmartEngine.matches``: does one of yt-dlp's site extractors recognize this
  URL? (Offline check; the catch-all generic extractor doesn't count.)
- ``SmartEngine.inspect``: extract metadata without downloading and curate the
  format zoo into the short quality list the panel shows (Best/2160p/.../MP3).
- ``SmartDownload``: run one job through yt-dlp with progress mapped onto the
  queue, honoring pause/cancel, with MP3/M4A extraction (+ cover art & tags),
  subtitles, clip trimming (F0.7), and the opt-in browser session (F0.8).

yt-dlp is imported lazily so the CLI stays fast for plain direct downloads.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.core import naming
from app.core.errors import DownloadError
from app.core.models import Job, JobStatus
from app.db.database import Database

log = logging.getLogger(__name__)

#: The standard quality ladder shown in the panel, top first.
QUALITY_TIERS = (2160, 1440, 1080, 720, 480, 360)

#: Substring -> user-facing message for the yt-dlp error zoo (F1.8 groundwork).
_FRIENDLY_ERRORS: tuple[tuple[str, str], ...] = (
    ("This video is private", "This video is private - its owner restricted access."),
    ("Private video", "This video is private - its owner restricted access."),
    (
        "Sign in to confirm your age",
        "This video is age-restricted. Grabline tried your browser login "
        "automatically - to download it you need to be signed in to YouTube in "
        "your browser (Firefox by default) on an age-verified account. Sign in "
        "there, then try again.",
    ),
    (
        "confirm you're not a bot",
        "YouTube is temporarily blocking automated access from your connection "
        "(a bot check). Wait a little and try again, or try a different network.",
    ),
    (
        "Requested format is not available",
        "YouTube didn't return a usable video format. This is usually temporary "
        "- try again shortly. If it only fails with 'Let Grabline use my browser "
        "session' turned on, turn it off: on a PC without a JavaScript runtime, "
        "browser cookies can make YouTube hide the downloadable formats.",
    ),
    (
        "n challenge",
        "YouTube needs a JavaScript runtime to unlock this video's formats. "
        "Grabline installs one (Deno) automatically; if this keeps happening, "
        "install Node.js and restart Grabline.",
    ),
    (
        "Only images are available",
        "YouTube needs a JavaScript runtime to unlock this video's formats. "
        "Grabline installs one (Deno) automatically; if this keeps happening, "
        "install Node.js and restart Grabline.",
    ),
    (
        "available in your country",
        "This video is region-blocked and not available from your location.",
    ),
    ("geo restricted", "This video is region-blocked and not available from your location."),
    (
        "This live event will begin",
        "This is a live stream that has not started yet - try again once it is over.",
    ),
    ("is not a valid URL", "That does not look like a valid address."),
    (
        "Unable to download JSON metadata: HTTP Error 404",
        "This does not look like a track or video page - it may be a browse "
        "page, or the item was removed. Open the track/video itself and grab "
        "it there, or right-click its title link.",
    ),
    (
        "Unsupported URL",
        "No downloadable media was found at this address.",
    ),
    (
        "DRM",
        "This content is DRM-protected. Grabline cannot and will not bypass DRM.",
    ),
    (
        "cookie database",
        "Could not read the browser's cookie store - close the browser completely "
        "and try again (Chromium locks its cookie database while running).",
    ),
    (
        "could not find",  # e.g. "could not find chrome cookies database"
        "Could not find that browser's cookie store - pick the browser you are "
        "actually signed in with under Settings.",
    ),
)


#: yt-dlp failures a browser login gets past (age gate, bot check, members-only,
#: private). These need cookies, not just a JS runtime.
_AUTH_WALL_MARKERS = (
    "sign in to confirm your age",
    "confirm you're not a bot",
    "sign in to confirm you're not a bot",
    "members-only",
    "join this channel",
    "this video is available to",
    "login required",
    "private video",
    "sign in to",
)

#: yt-dlp failures a JS runtime (+ EJS solver) cures: YouTube's n challenge was
#: skipped, so only throttled/storyboard formats came back.
_RUNTIME_MARKERS = (
    "requested format is not available",
    "only images are available",
    "n challenge",
)


def _looks_like_auth_wall(message: str) -> bool:
    """True when a browser login could get past this failure (see _download_smart)."""
    lowered = message.lower()
    return any(marker in lowered for marker in _AUTH_WALL_MARKERS)


def _runtime_might_help(message: str) -> bool:
    """True when providing a JS runtime + EJS solver could cure this failure."""
    lowered = message.lower()
    return any(marker in lowered for marker in _RUNTIME_MARKERS)


def friendly_error(message: str) -> str:
    """Map a raw yt-dlp error onto a sentence a person can act on."""
    for marker, friendly in _FRIENDLY_ERRORS:
        if marker.lower() in message.lower():
            return friendly
    first_line = message.strip().splitlines()[0] if message.strip() else "download failed"
    return first_line.removeprefix("ERROR:").strip()


@dataclass(frozen=True)
class QualityOption:
    """One row in the quality panel."""

    label: str  # "Best", "1080p", "MP3", "M4A"
    kind: str  # "video" | "audio"
    format_spec: str  # yt-dlp format selector
    height: int | None = None
    estimated_size: int | None = None
    audio_format: str | None = None  # "mp3" | "m4a" for audio options


@dataclass(frozen=True)
class MediaInfo:
    """What inspect() learned about a URL, ready for the quality panel."""

    url: str
    id: str
    title: str
    uploader: str | None
    duration: float | None
    thumbnail_url: str | None
    options: tuple[QualityOption, ...]
    subtitle_languages: tuple[str, ...] = ()
    auto_caption_languages: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlaylistEntry:
    url: str
    title: str
    duration: float | None
    index: int


@dataclass(frozen=True)
class PlaylistInfo:
    """A fast flat listing of a playlist (F1.7): titles and URLs, no formats."""

    url: str
    title: str
    uploader: str | None
    entries: tuple[PlaylistEntry, ...]


def _tier_format(tier: int) -> str:
    """A quality-tier selector that never dead-ends. Prefers the best
    video+audio at or below ``tier`` (then a muxed stream at that cap), but
    falls back to the best available format - so a video that has no stream at
    that exact tier still downloads instead of failing "Requested format is
    not available"."""
    return f"bv*[height<={tier}]+ba/b[height<={tier}]/bv*+ba/b"


def generic_quality_options() -> tuple[QualityOption, ...]:
    """Static picker for playlist batches, where per-video sizes are unknown.
    yt-dlp resolves the actual formats per entry at download time."""
    options = [QualityOption(label="Best", kind="video", format_spec="bv*+ba/b")]
    for tier in (1080, 720, 480):
        options.append(
            QualityOption(
                label=f"{tier}p",
                kind="video",
                format_spec=_tier_format(tier),
                height=tier,
            )
        )
    options.append(QualityOption(label="MP3", kind="audio", format_spec="ba/b", audio_format="mp3"))
    options.append(
        QualityOption(label="M4A", kind="audio", format_spec="ba[ext=m4a]/ba/b", audio_format="m4a")
    )
    return tuple(options)


def option_for_label(
    label: str, options: tuple[QualityOption, ...] | None = None
) -> QualityOption | None:
    """The quality option matching ``label`` (case-insensitive), for handoffs
    that already carry a choice (F1.3 in-page panel). Tries a media's curated
    ``options`` first, then the generic tiers; "best" falls back to the top."""
    wanted = label.strip().lower()
    for pool in (options or (), generic_quality_options()):
        for option in pool:
            if option.label.lower() == wanted:
                return option
        if wanted == "best" and pool:
            return pool[0]
    return None


def parse_playlist(info: dict[str, Any]) -> PlaylistInfo | None:
    """Turn a flat-extracted yt-dlp info dict into a PlaylistInfo, or None."""
    if info.get("_type") != "playlist":
        return None
    entries: list[PlaylistEntry] = []
    for position, raw in enumerate(info.get("entries") or [], start=1):
        if not raw:
            continue  # deleted/private items come through as None
        url = raw.get("url") or raw.get("webpage_url")
        if url and not str(url).startswith(("http://", "https://")):
            # Some flat extractions yield bare video IDs.
            url = (
                f"https://www.youtube.com/watch?v={url}" if raw.get("ie_key") == "Youtube" else None
            )
        if not url:
            continue
        entries.append(
            PlaylistEntry(
                url=str(url),
                title=str(raw.get("title") or f"Item {position}"),
                duration=raw.get("duration"),
                index=position,
            )
        )
    return PlaylistInfo(
        url=str(info.get("webpage_url") or info.get("original_url") or ""),
        title=str(info.get("title") or "Playlist"),
        uploader=info.get("uploader") or info.get("channel"),
        entries=tuple(entries),
    )


def _format_size(fmt: dict[str, Any]) -> int | None:
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    return int(size) if size else None


def _snap_to_tier(height: int) -> int | None:
    """1088 -> 1080, 2176 -> 2160 … formats are rarely exactly on the ladder."""
    for tier in QUALITY_TIERS:
        if abs(height - tier) <= tier * 0.08:
            return tier
    return None


def curate_formats(info: dict[str, Any]) -> tuple[QualityOption, ...]:
    """Boil the raw format list down to the curated picker (F0.3)."""
    formats: list[dict[str, Any]] = info.get("formats") or []
    video_formats = [f for f in formats if f.get("vcodec") not in (None, "none")]
    audio_formats = [
        f
        for f in formats
        if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")
    ]

    best_audio = max(audio_formats, key=lambda f: f.get("abr") or 0, default=None)
    audio_size = _format_size(best_audio) if best_audio else None

    def tier_estimate(tier: int) -> int | None:
        candidates = [
            f for f in video_formats if f.get("height") and _snap_to_tier(f["height"]) == tier
        ]
        if not candidates:
            return None
        best = max(candidates, key=lambda f: (f.get("tbr") or 0, _format_size(f) or 0))
        video_size = _format_size(best)
        if video_size is None:
            return None
        needs_audio = best.get("acodec") in (None, "none")
        if needs_audio and audio_size is not None:
            return video_size + audio_size
        return video_size

    options: list[QualityOption] = []
    tiers_present = sorted(
        {
            tier
            for f in video_formats
            if f.get("height") and (tier := _snap_to_tier(f["height"])) is not None
        },
        reverse=True,
    )
    if video_formats:
        best_estimate = tier_estimate(tiers_present[0]) if tiers_present else None
        options.append(
            QualityOption(
                label="Best",
                kind="video",
                format_spec="bv*+ba/b",
                height=max((f.get("height") or 0) for f in video_formats) or None,
                estimated_size=best_estimate,
            )
        )
        for tier in tiers_present:
            options.append(
                QualityOption(
                    label=f"{tier}p",
                    kind="video",
                    format_spec=_tier_format(tier),
                    height=tier,
                    estimated_size=tier_estimate(tier),
                )
            )
    if audio_formats or video_formats:
        options.append(
            QualityOption(
                label="MP3",
                kind="audio",
                format_spec="ba/b",
                estimated_size=audio_size,
                audio_format="mp3",
            )
        )
        options.append(
            QualityOption(
                label="M4A",
                kind="audio",
                format_spec="ba[ext=m4a]/ba/b",
                estimated_size=audio_size,
                audio_format="m4a",
            )
        )
    return tuple(options)


class SmartEngine:
    """Extractor matching and metadata inspection."""

    def __init__(self) -> None:
        self._extractors: list[Any] | None = None
        self._lock = threading.Lock()

    def _extractor_classes(self) -> list[Any]:
        with self._lock:
            if self._extractors is None:
                from yt_dlp.extractor import gen_extractor_classes

                self._extractors = [ie for ie in gen_extractor_classes() if ie.IE_NAME != "generic"]
            return self._extractors

    def matches(self, url: str) -> bool:
        """Offline check: does a real site extractor (not generic) claim this URL?"""
        return any(ie.suitable(url) for ie in self._extractor_classes())

    def inspect(
        self,
        url: str,
        *,
        use_session: bool = False,
        session_browser: str = "chrome",
        proxy: str | None = None,
    ) -> MediaInfo | PlaylistInfo:
        """Metadata for a single video, or a fast flat listing for a playlist.

        ``noplaylist`` keeps watch-URLs-with-a-list-param as single videos;
        pure playlist URLs still come back as playlists. ``extract_flat``
        makes the playlist case one cheap request instead of hundreds.
        """
        import yt_dlp

        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
        }
        if use_session:
            opts["cookiesfrombrowser"] = (session_browser,)
        if proxy:
            opts["proxy"] = proxy
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            raise DownloadError(friendly_error(str(exc))) from exc
        if not isinstance(info, dict):
            raise DownloadError("No downloadable media was found at this address.")
        playlist = parse_playlist(info)
        if playlist is not None:
            if not playlist.entries:
                raise DownloadError("This playlist appears to be empty.")
            if len(playlist.entries) == 1:
                # A one-item playlist deserves the full single-video panel.
                return self.inspect(
                    playlist.entries[0].url,
                    use_session=use_session,
                    session_browser=session_browser,
                    proxy=proxy,
                )
            return playlist
        return MediaInfo(
            url=url,
            id=str(info.get("id") or ""),
            title=str(info.get("title") or "Untitled"),
            uploader=info.get("uploader") or info.get("channel"),
            duration=info.get("duration"),
            thumbnail_url=info.get("thumbnail"),
            options=curate_formats(info),
            subtitle_languages=tuple(sorted((info.get("subtitles") or {}).keys())),
            auto_caption_languages=tuple(sorted((info.get("automatic_captions") or {}).keys())),
        )


class _StopRequested(Exception):
    pass


@dataclass
class _LiveProgress:
    per_file: dict[str, int] = field(default_factory=dict)
    totals: dict[str, int | None] = field(default_factory=dict)


class SmartDownload:
    """Runs one smart job through yt-dlp. One-shot object, like SegmentedDownload.

    Job options (job.options):
        format_spec: str        yt-dlp format selector (required)
        audio_format: str|None  "mp3"/"m4a" -> extract audio + tags + cover art
        subtitles: {"lang": str, "auto": bool, "embed": bool} | None
        trim: [start_seconds, end_seconds] | None   (F0.7)
        use_session: bool, session_browser: str      (F0.8)
    """

    def __init__(
        self,
        db: Database,
        job: Job,
        *,
        ffmpeg_path: str | None = None,
        persist_interval: float = 0.3,
        ratelimit: int | None = None,
        proxy: str | None = None,
    ) -> None:
        self.db = db
        self.job = job
        self.ffmpeg_path = ffmpeg_path
        self.persist_interval = persist_interval
        self.ratelimit = ratelimit
        self.proxy = proxy
        self._stop_event = threading.Event()
        self._cancelled = False
        self._live = _LiveProgress()
        self._last_persist = 0.0
        self._known_files: set[str] = set()
        self._js_runtime: tuple[str, str] | None = None  # (yt-dlp name, path)

    # ------------------------------------------------------------ control

    def pause(self) -> None:
        self._stop_event.set()

    def cancel(self) -> None:
        self._cancelled = True
        self._stop_event.set()

    @property
    def bytes_downloaded(self) -> int:
        return sum(self._live.per_file.values())

    # ---------------------------------------------------------------- run

    def run(self) -> JobStatus:
        import yt_dlp

        self.db.set_job_status(self.job.id, JobStatus.DOWNLOADING)
        try:
            info = self._download_smart()
        except _StopRequested:
            return self._settle_stopped()
        except yt_dlp.utils.DownloadError as exc:
            if self._stop_event.is_set():  # our hook exception, re-wrapped by yt-dlp
                return self._settle_stopped()
            return self._finish_failed(friendly_error(str(exc)))
        except DownloadError as exc:
            return self._finish_failed(str(exc))
        except Exception:
            if self._stop_event.is_set():
                return self._settle_stopped()
            log.exception("unexpected error in smart job %s", self.job.id)
            return self._finish_failed("unexpected internal error (see log)")
        return self._finalize(info)

    # ------------------------------------------------------------ internals

    def _build_options(
        self, *, with_cookies: bool = False, with_runtime: bool = False
    ) -> dict[str, Any]:
        options = self.job.options
        base = Path(self.job.filename).stem or "download"
        outtmpl = str(Path(self.job.dest_dir) / f"{base}.%(ext)s")
        ydl_opts: dict[str, Any] = {
            "format": options.get("format_spec") or "bv*+ba/b",
            "outtmpl": {"default": outtmpl},
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "progress_hooks": [self._hook],
            "postprocessor_hooks": [self._postprocessor_hook],
            "retries": 3,
            "fragment_retries": 5,
            "continuedl": True,
        }
        if self.ffmpeg_path:
            ydl_opts["ffmpeg_location"] = self.ffmpeg_path
        if with_runtime and self._js_runtime:
            # The slow path, used only on escalation: hand yt-dlp the runtime we
            # found (yt-dlp only auto-enables Deno, and only if on PATH) so it can
            # solve YouTube's n challenge, plus allow the EJS solver download
            # (without it the challenge is skipped and only storyboards come
            # back). The fast path omits both so normal videos use the jsless
            # android_vr/tv clients and start quickly.
            name, path = self._js_runtime
            ydl_opts["js_runtimes"] = {name: {"path": path}}
            ydl_opts["remote_components"] = ["ejs:github"]
        if self.ratelimit:
            ydl_opts["ratelimit"] = float(self.ratelimit)
        # Postprocessing (audio extraction, tags, subtitle conversion) needs
        # FFmpeg. Without it, plain video downloads still work untouched.
        has_ffmpeg = bool(self.ffmpeg_path)
        postprocessors: list[dict[str, Any]] = []
        audio_format = options.get("audio_format")
        if audio_format:
            if not has_ffmpeg:
                raise DownloadError(
                    "FFmpeg is required for audio extraction - install it from Settings"
                )
            postprocessors.append(
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_format,
                    "preferredquality": "0",
                }
            )
            postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
            postprocessors.append({"key": "EmbedThumbnail"})
            ydl_opts["writethumbnail"] = True
        elif has_ffmpeg:
            postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
        subtitles = options.get("subtitles")
        if subtitles and subtitles.get("lang"):
            ydl_opts["writesubtitles"] = True
            ydl_opts["writeautomaticsub"] = bool(subtitles.get("auto"))
            ydl_opts["subtitleslangs"] = [subtitles["lang"]]
            if has_ffmpeg:
                postprocessors.append({"key": "FFmpegSubtitlesConvertor", "format": "srt"})
                if subtitles.get("embed"):
                    postprocessors.append({"key": "FFmpegEmbedSubtitle"})
        trim = options.get("trim")
        if trim:
            from yt_dlp.utils import download_range_func

            start, end = float(trim[0] or 0), float(trim[1])
            ydl_opts["download_ranges"] = download_range_func(None, [(start, end)])
            ydl_opts["force_keyframes_at_cuts"] = True
        if with_cookies and (browser := self._cookie_browser()):
            ydl_opts["cookiesfrombrowser"] = (browser,)
        if self.proxy:
            ydl_opts["proxy"] = self.proxy
        ydl_opts["postprocessors"] = postprocessors
        return ydl_opts

    def _needs_js_runtime(self) -> bool:
        """YouTube now expects a JavaScript runtime to solve its 'n challenge';
        without one, formats can come back throttled/unusable ("Requested
        format is not available") - so provision it for every YouTube job, not
        only signed-in ones. Other sites only need it when a browser session
        pushes yt-dlp onto a JS-dependent client."""
        if self.job.options.get("use_session"):
            return True
        host = (urlsplit(self.job.url).hostname or "").lower()
        return host in ("youtu.be", "youtube.com", "youtube-nocookie.com") or host.endswith(
            (".youtube.com", ".youtube-nocookie.com")
        )

    def _ensure_js_runtime(self) -> None:
        """Make a JS runtime available before yt-dlp runs: prefer one already
        installed (Node/Bun/Deno/QuickJS - yt-dlp won't auto-enable them, so we
        pass them explicitly), and only download Deno if nothing is present.
        Non-fatal: on failure the download still tries."""
        if not self._needs_js_runtime():
            return
        from app.core import jsruntime

        found = jsruntime.detect_js_runtime()
        if found is not None:
            log.info("job %s: using %s as the JavaScript runtime", self.job.id, found[0])
            self._js_runtime = found
            return
        try:
            log.info(
                "job %s: no JavaScript runtime found - fetching Deno (one-time ~40 MB)",
                self.job.id,
            )
            self._js_runtime = ("deno", str(jsruntime.ensure_deno(proxy=self.proxy)))
        except DownloadError as exc:
            log.warning("job %s: could not provision a JS runtime: %s", self.job.id, exc)
        except Exception:  # never let runtime setup crash the job
            log.exception("job %s: unexpected error provisioning a JS runtime", self.job.id)

    def _cookie_browser(self) -> str | None:
        """Which browser to read a login from: the one chosen in Settings, or
        the auto-detected installed one. None if we can't find a browser."""
        configured = self.job.options.get("session_browser")
        if configured:
            return str(configured)
        from app.core.browser_setup import detect_cookie_browser

        return detect_cookie_browser()

    def _download(self, *, with_cookies: bool, with_runtime: bool) -> dict[str, Any]:
        import yt_dlp

        opts = self._build_options(with_cookies=with_cookies, with_runtime=with_runtime)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(self.job.url, download=True)
        if not isinstance(info, dict):
            raise DownloadError("No downloadable media was found at this address.")
        return info

    def _download_smart(self) -> dict[str, Any]:
        """Fast first, capable second. The first attempt uses no JS runtime and
        no cookies, so yt-dlp picks YouTube's jsless android_vr/tv clients and
        normal videos start in seconds. Only if that fails in a way a runtime
        or a login could fix do we escalate to the slow path (Deno + EJS solver,
        plus the browser login on an auth wall) - so age/login-restricted videos
        still work, without making every video pay for it."""
        import yt_dlp

        try:
            return self._download(with_cookies=False, with_runtime=False)
        except yt_dlp.utils.DownloadError as exc:
            if self._stop_event.is_set():
                raise
            message = str(exc)
            browser = self._cookie_browser()
            wants_login = browser is not None and (
                _looks_like_auth_wall(message) or bool(self.job.options.get("use_session"))
            )
            if not (_runtime_might_help(message) or wants_login):
                raise  # unrecoverable (removed, geo-blocked, ...) - fail fast, no slow retry
            log.info(
                "job %s: fast path failed - escalating (runtime%s)",
                self.job.id,
                f" + {browser} login" if wants_login else "",
            )
            self._ensure_js_runtime()  # provisions Deno for YouTube/session jobs; no-op otherwise
            return self._download(with_cookies=wants_login, with_runtime=True)

    def _hook(self, event: dict[str, Any]) -> None:
        if self._stop_event.is_set():
            raise _StopRequested
        status = event.get("status")
        filename = event.get("tmpfilename") or event.get("filename") or ""
        if status == "downloading":
            self._known_files.add(filename)
            self._live.per_file[filename] = int(event.get("downloaded_bytes") or 0)
            total = event.get("total_bytes") or event.get("total_bytes_estimate")
            self._live.totals[filename] = int(total) if total else None
            self._persist_progress()
        elif status == "finished":
            final = event.get("total_bytes") or event.get("downloaded_bytes")
            if final:
                self._live.per_file[filename] = int(final)
            self._persist_progress(force=True)

    def _postprocessor_hook(self, event: dict[str, Any]) -> None:
        if self._stop_event.is_set() and event.get("status") == "started":
            raise _StopRequested

    def _persist_progress(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_persist < self.persist_interval:
            return
        self._last_persist = now
        self.db.update_job_downloaded(self.job.id, self.bytes_downloaded)
        totals = list(self._live.totals.values())
        if totals and all(t is not None for t in totals):
            total = sum(t for t in totals if t is not None)
            if total != self.job.total_size:
                self.job.total_size = total
                self.db.update_job_total(self.job.id, total)

    # ---------------------------------------------------------- completion

    def _finalize(self, info: dict[str, Any]) -> JobStatus:
        filepath = self._final_filepath(info)
        if filepath is None or not filepath.exists():
            return self._finish_failed("yt-dlp finished but the output file was not found")
        size = filepath.stat().st_size
        self.job.filename = filepath.name
        self.db.update_job_filename(self.job.id, filepath.name)
        self.db.update_job_total(self.job.id, size)
        self.db.update_job_downloaded(self.job.id, size)
        if info.get("title") and not self.job.title:
            self.job.title = str(info["title"])
        self.db.set_job_status(self.job.id, JobStatus.COMPLETED)
        return JobStatus.COMPLETED

    def _final_filepath(self, info: dict[str, Any]) -> Path | None:
        downloads = info.get("requested_downloads") or []
        if downloads and downloads[0].get("filepath"):
            return Path(downloads[0]["filepath"])
        if info.get("filepath"):
            return Path(str(info["filepath"]))
        # Fallback: the newest plausible file matching our output stem.
        base = Path(self.job.filename).stem
        candidates = [
            p
            for p in Path(self.job.dest_dir).glob(f"{naming.sanitize_filename(base)}.*")
            if not p.name.endswith((".part", ".ytdl"))
        ]
        return max(candidates, key=lambda p: p.stat().st_mtime, default=None)

    def _settle_stopped(self) -> JobStatus:
        self._persist_progress(force=True)
        if self._cancelled:
            self._remove_partials()
            self.db.update_job_downloaded(self.job.id, 0)
            self.db.set_job_status(self.job.id, JobStatus.CANCELLED)
            return JobStatus.CANCELLED
        # yt-dlp resumes its own .part files on the next run.
        self.db.set_job_status(self.job.id, JobStatus.PAUSED)
        return JobStatus.PAUSED

    def _remove_partials(self) -> None:
        dest = Path(self.job.dest_dir)
        stems = {Path(name).name for name in self._known_files if name}
        for stem in stems:
            for suffix in ("", ".part", ".ytdl"):
                (dest / f"{stem}{suffix}").unlink(missing_ok=True)

    def _finish_failed(self, message: str) -> JobStatus:
        log.warning("smart job %s failed: %s", self.job.id, message)
        self.db.set_job_status(self.job.id, JobStatus.FAILED, error=message)
        return JobStatus.FAILED
