from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

import pytest

from app.core.models import JobKind, JobStatus
from app.db.database import Database
from app.engines.hls import HlsDownload
from app.tests.media_fixtures import (
    FFMPEG,
    FFPROBE,
    make_hls,
    make_hls_audio,
    probe_duration,
    probe_streams,
)
from app.tests.media_server import MediaServer


def _hls_job(db: Database, url: str, dest: Path, options: dict[str, Any] | None = None):
    return db.create_job(
        url, str(dest), "lecture.mp4", kind=JobKind.HLS, title="Lecture", options=options
    )


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


@pytest.mark.skipif(FFMPEG is None, reason="needs a real ffmpeg")
def test_hls_variant_with_separate_audio(
    server: MediaServer, db: Database, dest: Path, tmp_path: Path
):
    """F2.1: a chosen variant plus its audio rendition mux into one mp4."""
    video_files = make_hls(tmp_path / "video", seconds=2)
    audio_files = make_hls_audio(tmp_path / "audio", seconds=2)
    for name, content in video_files.items():
        content_type = "application/vnd.apple.mpegurl" if name.endswith(".m3u8") else "video/mp2t"
        server.add(f"/video/{name}", content, content_type=content_type)
    for name, content in audio_files.items():
        content_type = "application/vnd.apple.mpegurl" if name.endswith(".m3u8") else "video/mp2t"
        server.add(f"/audio/{name}", content, content_type=content_type)
    master = (
        "#EXTM3U\n"
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="Main",DEFAULT=YES,URI="audio/audio.m3u8"\n'
        '#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=128x72,AUDIO="aud"\n'
        "video/index.m3u8\n"
    )
    server.add("/master.m3u8", master.encode(), content_type="application/vnd.apple.mpegurl")

    job = _hls_job(
        db,
        server.url("/master.m3u8"),
        dest,
        options={
            "variant_url": server.url("/video/index.m3u8"),
            "audio_url": server.url("/audio/audio.m3u8"),
            "quality_label": "72p",
        },
    )
    status = HlsDownload(db, job, ffmpeg_path=FFMPEG).run()

    assert status is JobStatus.COMPLETED
    output = dest / "lecture.mp4"
    assert output.exists() and output.stat().st_size > 0
    if FFPROBE is not None:
        kinds = probe_streams(output)
        assert "video" in kinds and "audio" in kinds


def test_transient_failure_is_retried_once(server: MediaServer, db: Database, dest: Path):
    """A nonzero FFmpeg exit gets exactly one retry before failing the job."""
    vod = b"#EXTM3U\n#EXTINF:2.0,\nseg000.ts\n#EXT-X-ENDLIST\n"
    server.add("/vod.m3u8", vod, content_type="application/vnd.apple.mpegurl")
    marker = dest / "invocations.txt"
    stub = dest / "fake-ffmpeg.sh"
    stub.write_text(f'#!/bin/sh\necho run >> "{marker}"\nexit 1\n')
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)

    job = _hls_job(db, server.url("/vod.m3u8"), dest)
    status = HlsDownload(db, job, ffmpeg_path=str(stub)).run()

    assert status is JobStatus.FAILED
    assert marker.read_text().count("run") == 2
    assert not (dest / "lecture.mp4.gl-part").exists()


def test_looks_complete_accepts_full_stream(db: Database, dest: Path):
    """A stream FFmpeg muxed to ~its full duration is kept even on a nonzero
    exit (a trailing segment 404 must not throw away a finished file)."""
    job = _hls_job(db, "http://x/live.m3u8", dest)
    task = HlsDownload(db, job, ffmpeg_path="ffmpeg")
    part = job.part_path
    part.write_bytes(b"x" * 1024)
    task._duration = 100.0

    task._out_time = 99.5  # 99.5% muxed -> complete
    assert task._looks_complete(part) is True
    task._out_time = 40.0  # less than 98% -> not complete
    assert task._looks_complete(part) is False
    task._out_time = 99.5
    task._duration = None  # unknown duration -> cannot claim complete
    assert task._looks_complete(part) is False


def test_discard_removes_leftover_part(db: Database, dest: Path, tmp_path: Path):
    from app.engines.hls import _discard

    leftover = tmp_path / "x.mp4.gl-part"
    leftover.write_bytes(b"junk")
    _discard(leftover)
    assert not leftover.exists()
    _discard(leftover)  # already gone: no error


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


def test_estimate_does_not_read_absurdly_high_early():
    """The early size estimate used to extrapolate the container header over a
    fraction of a second into hundreds of GB. Anchored from a steady window,
    it stays near the true size once it appears."""
    import tempfile
    from pathlib import Path

    from app.core.models import JobKind
    from app.db.database import Database
    from app.engines.hls import HlsDownload

    tmp = Path(tempfile.mkdtemp())
    db = Database(tmp / "t.db")
    job = db.create_job("https://x/s.m3u8", str(tmp), "s.mp4", kind=JobKind.HLS, title="s")
    task = HlsDownload(db, job, ffmpeg_path=None)
    task._duration = 7200.0  # 2-hour video
    header, bitrate = 2_000_000, (2_000_000_000 - 2_000_000) / 7200.0  # ~2 GB total

    last = 0
    seen: list[int] = []
    for out in (0.5, 2.0, 5.0, 8.0, 12.0, 60.0, 600.0, 3600.0):
        task._downloaded = int(header + bitrate * out)
        task._out_time = out
        last = task._persist_estimate(last)
        total = db.get_job(job.id).total_size
        if total:
            seen.append(total)

    assert seen, "an estimate should eventually be published"
    # Every published estimate is within 20% of the true ~2 GB - never 500 GB.
    assert all(1.6e9 <= t <= 2.4e9 for t in seen), [t / 1e9 for t in seen]
    db.close()


def test_finalize_survives_a_failing_fsync(
    db: Database, dest: Path, monkeypatch: pytest.MonkeyPatch
):
    """The Windows regression: FlushFileBuffers rejects a read-only handle, the
    raise skipped the COMPLETED write, and a fully-downloaded stream sat at
    "Downloading" forever. The flush is best-effort; completion is not."""
    import os as os_mod

    job = _hls_job(db, "https://x/s.m3u8", dest)
    task = HlsDownload(db, job, ffmpeg_path="ffmpeg")
    part = job.part_path
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"x" * 1024)

    def refuse(fd):
        raise PermissionError(9, "The handle is invalid")  # what Windows raises

    monkeypatch.setattr(os_mod, "fsync", refuse)
    status = task._finalize(part)
    assert status is JobStatus.COMPLETED
    fresh = db.get_job(job.id)
    assert fresh is not None and fresh.status is JobStatus.COMPLETED
    assert (dest / fresh.filename).exists()
