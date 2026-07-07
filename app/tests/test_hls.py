from __future__ import annotations

from pathlib import Path

import pytest

from app.core.models import JobKind, JobStatus
from app.db.database import Database
from app.engines.hls import HlsDownload
from app.tests.media_fixtures import FFMPEG, FFPROBE, make_hls, probe_duration
from app.tests.media_server import MediaServer


def _hls_job(db: Database, url: str, dest: Path):
    return db.create_job(url, str(dest), "lecture.mp4", kind=JobKind.HLS, title="Lecture")


def test_hls_requires_ffmpeg(db: Database, dest: Path):
    job = _hls_job(db, "http://127.0.0.1:1/x.m3u8", dest)
    status = HlsDownload(db, job, ffmpeg_path=None).run()
    assert status is JobStatus.FAILED
    fresh = db.get_job(job.id)
    assert fresh is not None
    assert fresh.error is not None and "FFmpeg" in fresh.error


@pytest.mark.skipif(FFMPEG is None, reason="needs a real ffmpeg")
def test_hls_reassembles_to_mp4(server: MediaServer, db: Database, dest: Path, tmp_path: Path):
    files = make_hls(tmp_path / "hls", seconds=2)
    assert "index.m3u8" in files
    for name, content in files.items():
        content_type = "application/vnd.apple.mpegurl" if name.endswith(".m3u8") else "video/mp2t"
        server.add(f"/hls/{name}", content, content_type=content_type)

    job = _hls_job(db, server.url("/hls/index.m3u8"), dest)
    status = HlsDownload(db, job, ffmpeg_path=FFMPEG).run()

    assert status is JobStatus.COMPLETED
    output = dest / "lecture.mp4"
    assert output.exists() and output.stat().st_size > 0
    assert not (dest / "lecture.mp4.gl-part").exists()
    fresh = db.get_job(job.id)
    assert fresh is not None
    assert fresh.total_size == output.stat().st_size
    if FFPROBE is not None:
        duration = probe_duration(output)
        assert duration is not None and 1.0 < duration < 3.5


@pytest.mark.skipif(FFMPEG is None, reason="needs a real ffmpeg")
def test_hls_broken_stream_fails_cleanly(server: MediaServer, db: Database, dest: Path):
    server.add("/broken.m3u8", b"this is not a playlist at all", content_type="text/plain")
    job = _hls_job(db, server.url("/broken.m3u8"), dest)
    status = HlsDownload(db, job, ffmpeg_path=FFMPEG, stall_timeout=15).run()
    assert status is JobStatus.FAILED
    fresh = db.get_job(job.id)
    assert fresh is not None
    assert fresh.error is not None
    assert not (dest / "lecture.mp4").exists()
    assert not (dest / "lecture.mp4.gl-part").exists()


def test_live_playlist_is_refused_clearly(server: MediaServer, db: Database, dest: Path):
    # A media playlist without #EXT-X-ENDLIST is a live stream in progress.
    # FFmpeg would happily poll it forever; Grabline must refuse up front.
    live = b"#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2.0,\nseg000.ts\n"
    server.add("/live.m3u8", live, content_type="application/vnd.apple.mpegurl")
    job = _hls_job(db, server.url("/live.m3u8"), dest)
    # ffmpeg is never launched for a refused stream, so the path can be fake.
    status = HlsDownload(db, job, ffmpeg_path="ffmpeg-never-invoked").run()
    assert status is JobStatus.FAILED
    fresh = db.get_job(job.id)
    assert fresh is not None
    assert fresh.error is not None and "live" in fresh.error.lower()
