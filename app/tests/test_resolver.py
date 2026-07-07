from __future__ import annotations

import pytest

from app.core.errors import DownloadError
from app.core.models import JobKind
from app.core.resolver import Resolver
from app.engines.smart import (
    MediaInfo,
    PlaylistEntry,
    PlaylistInfo,
    QualityOption,
    SmartEngine,
)
from app.tests.media_server import MediaServer, payload

FAKE_MEDIA = MediaInfo(
    url="https://tube.example/watch?v=1",
    id="1",
    title="A Video",
    uploader="Someone",
    duration=60.0,
    thumbnail_url=None,
    options=(QualityOption(label="Best", kind="video", format_spec="bv*+ba/b"),),
)

FAKE_PLAYLIST = PlaylistInfo(
    url="https://tube.example/playlist?list=1",
    title="A Playlist",
    uploader="Someone",
    entries=(
        PlaylistEntry(url="https://tube.example/watch?v=1", title="One", duration=60, index=1),
        PlaylistEntry(url="https://tube.example/watch?v=2", title="Two", duration=90, index=2),
    ),
)


class FakeSmart(SmartEngine):
    def __init__(
        self,
        *,
        match: bool,
        error: str | None = None,
        playlist: PlaylistInfo | None = None,
    ) -> None:
        super().__init__()
        self._match = match
        self._error = error
        self._playlist = playlist

    def matches(self, url: str) -> bool:
        return self._match

    def inspect(self, url: str, **kwargs) -> MediaInfo | PlaylistInfo:
        if self._error:
            raise DownloadError(self._error)
        return self._playlist if self._playlist is not None else FAKE_MEDIA


def test_direct_file_routes_to_segmenter(server: MediaServer):
    url = server.add("/file.bin", payload(100_000, 3))
    resolution = Resolver(FakeSmart(match=False)).resolve(url)
    assert resolution.kind is JobKind.DIRECT
    assert resolution.probe is not None
    assert resolution.probe.total_size == 100_000


def test_manifest_suffix_routes_to_hls():
    resolution = Resolver(FakeSmart(match=False)).resolve("https://cdn.example/live/stream.m3u8")
    assert resolution.kind is JobKind.HLS


def test_manifest_content_type_routes_to_hls(server: MediaServer):
    url = server.add(
        "/manifest",
        b"#EXTM3U\n",
        content_type="application/vnd.apple.mpegurl",
    )
    resolution = Resolver(FakeSmart(match=False)).resolve(url)
    assert resolution.kind is JobKind.HLS


def test_smart_match_wins(server: MediaServer):
    resolution = Resolver(FakeSmart(match=True)).resolve("https://tube.example/watch?v=1")
    assert resolution.kind is JobKind.SMART
    assert resolution.media is FAKE_MEDIA


def test_playlist_resolution(server: MediaServer):
    resolver = Resolver(FakeSmart(match=True, playlist=FAKE_PLAYLIST))
    resolution = resolver.resolve("https://tube.example/playlist?list=1")
    assert resolution.kind is JobKind.SMART
    assert resolution.playlist is FAKE_PLAYLIST
    assert resolution.media is None


def test_smart_error_is_final_and_friendly():
    resolver = Resolver(FakeSmart(match=True, error="This video is private."))
    resolution = resolver.resolve("https://tube.example/watch?v=1")
    assert resolution.kind is None
    assert resolution.message == "This video is private."


def test_non_http_scheme_refused():
    resolution = Resolver(FakeSmart(match=False)).resolve("ftp://host/file")
    assert resolution.kind is None
    assert resolution.message is not None and "http" in resolution.message


def test_unreachable_host_is_friendly():
    resolution = Resolver(FakeSmart(match=False)).resolve("http://127.0.0.1:1/nothing")
    assert resolution.kind is None
    assert resolution.message is not None
    assert "No downloadable media" in resolution.message


@pytest.mark.parametrize("url", ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
def test_real_extractor_matching_is_offline(url: str):
    """matches() must recognize big sites without any network traffic."""
    assert SmartEngine().matches(url)
    assert not SmartEngine().matches("https://example.com/some/page.html")
