"""The resolver: every URL, one route (proposal §5).

1. Smart Engine — does a yt-dlp site extractor recognize it? Full experience.
2. HLS/DASH manifest — FFmpeg reassembly.
3. Direct file — the segmented downloader.
4. Nothing — a friendly message, never a traceback.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.core.errors import DownloadError
from app.core.models import JobKind
from app.core.probe import ProbeResult, probe
from app.engines.smart import MediaInfo, PlaylistInfo, SmartEngine

_MANIFEST_SUFFIXES = (".m3u8", ".mpd")
_MANIFEST_CONTENT_TYPES = (
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
    "application/dash+xml",
)


@dataclass(frozen=True)
class Resolution:
    """Where a URL routes. ``kind`` None means: nothing to download, see message."""

    url: str
    kind: JobKind | None
    media: MediaInfo | None = None  # set for SMART single videos
    playlist: PlaylistInfo | None = None  # set for SMART playlists (F1.7)
    probe: ProbeResult | None = None  # set for DIRECT
    message: str | None = None  # set when kind is None


class Resolver:
    def __init__(self, smart: SmartEngine | None = None) -> None:
        self.smart = smart or SmartEngine()

    def resolve(
        self,
        url: str,
        *,
        use_session: bool = False,
        session_browser: str = "chrome",
    ) -> Resolution:
        url = url.strip()
        scheme = urlsplit(url).scheme.lower()
        if scheme not in ("http", "https"):
            return Resolution(
                url=url,
                kind=None,
                message="Only http:// and https:// addresses can be downloaded.",
            )

        if self.smart.matches(url):
            try:
                inspected = self.smart.inspect(
                    url, use_session=use_session, session_browser=session_browser
                )
            except DownloadError as exc:
                # A site extractor claimed the URL; its verdict is final —
                # falling through to sniffing would just fail less clearly.
                return Resolution(url=url, kind=None, message=str(exc))
            if isinstance(inspected, PlaylistInfo):
                return Resolution(url=url, kind=JobKind.SMART, playlist=inspected)
            return Resolution(url=url, kind=JobKind.SMART, media=inspected)

        path = urlsplit(url).path.lower()
        if path.endswith(_MANIFEST_SUFFIXES):
            return Resolution(url=url, kind=JobKind.HLS)

        try:
            with httpx.Client(
                follow_redirects=True, timeout=httpx.Timeout(20.0, connect=10.0)
            ) as client:
                result = probe(client, url)
        except DownloadError as exc:
            return Resolution(
                url=url,
                kind=None,
                message=f"No downloadable media was found at this address ({exc}).",
            )
        content_type = (result.content_type or "").split(";")[0].strip().lower()
        if content_type in _MANIFEST_CONTENT_TYPES:
            return Resolution(url=url, kind=JobKind.HLS, probe=result)
        return Resolution(url=url, kind=JobKind.DIRECT, probe=result)
