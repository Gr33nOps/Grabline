"""SmartDownload exercised end-to-end through yt-dlp's generic extractor
against the local media server — the full engine pipeline without YouTube.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.core.models import JobKind, JobStatus
from app.db.database import Database
from app.engines.smart import SmartDownload
from app.tests.conftest import sha256_file, wait_for
from app.tests.media_fixtures import FFMPEG, make_mp4
from app.tests.media_server import MediaServer, payload, sha256

MB = 1024 * 1024


def _smart_job(db: Database, url: str, dest: Path, filename: str, **options):
    return db.create_job(
        url,
        str(dest),
        filename,
        kind=JobKind.SMART,
        title=Path(filename).stem,
        options={"format_spec": "b", **options},
    )


def test_smart_download_direct_file(server: MediaServer, db: Database, dest: Path):
    data = payload(1 * MB, 55)
    url = server.add("/video.mp4", data, content_type="video/mp4")
    job = _smart_job(db, url, dest, "clip.mp4")

    # ffmpeg_path=None: no postprocessing — bytes must come through untouched.
    status = SmartDownload(db, job, ffmpeg_path=None).run()

    assert status is JobStatus.COMPLETED
    assert sha256_file(dest / "clip.mp4") == sha256(data)
    fresh = db.get_job(job.id)
    assert fresh is not None
    assert fresh.filename == "clip.mp4"
    assert fresh.total_size == len(data)
    assert fresh.downloaded == len(data)


def test_smart_download_pause_and_resume(server: MediaServer, db: Database, dest: Path):
    data = payload(4 * MB, 56)
    url = server.add(
        "/slowvideo.mp4",
        data,
        content_type="video/mp4",
        chunk_size=32 * 1024,
        delay_per_chunk=0.02,
    )
    job = _smart_job(db, url, dest, "slowclip.mp4")

    task = SmartDownload(db, job, ffmpeg_path=None)
    results: list[JobStatus] = []
    thread = threading.Thread(target=lambda: results.append(task.run()))
    thread.start()
    wait_for(lambda: task.bytes_downloaded > 512 * 1024, timeout=30)
    task.pause()
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert results == [JobStatus.PAUSED]
    assert not (dest / "slowclip.mp4").exists()
    fresh = db.get_job(job.id)
    assert fresh is not None
    assert fresh.downloaded > 0  # progress mirror persisted for the UI

    served_before = server.served_bytes("/slowvideo.mp4")
    status = SmartDownload(db, fresh, ffmpeg_path=None).run()
    assert status is JobStatus.COMPLETED
    assert sha256_file(dest / "slowclip.mp4") == sha256(data)
    resumed_bytes = server.served_bytes("/slowvideo.mp4") - served_before
    assert resumed_bytes < len(data)  # yt-dlp continued the .part file


def test_smart_download_cancel_removes_partials(server: MediaServer, db: Database, dest: Path):
    data = payload(4 * MB, 57)
    url = server.add(
        "/cancelvideo.mp4",
        data,
        content_type="video/mp4",
        chunk_size=32 * 1024,
        delay_per_chunk=0.02,
    )
    job = _smart_job(db, url, dest, "cancelclip.mp4")

    task = SmartDownload(db, job, ffmpeg_path=None)
    results: list[JobStatus] = []
    thread = threading.Thread(target=lambda: results.append(task.run()))
    thread.start()
    wait_for(lambda: task.bytes_downloaded > 256 * 1024, timeout=30)
    task.cancel()
    thread.join(timeout=30)
    assert results == [JobStatus.CANCELLED]
    leftovers = [p.name for p in dest.iterdir() if "cancelclip" in p.name]
    assert leftovers == []


def test_audio_extraction_requires_ffmpeg(server: MediaServer, db: Database, dest: Path):
    url = server.add("/a.mp4", payload(100_000, 58), content_type="video/mp4")
    job = _smart_job(db, url, dest, "a.mp3", audio_format="mp3")
    status = SmartDownload(db, job, ffmpeg_path=None).run()
    assert status is JobStatus.FAILED
    fresh = db.get_job(job.id)
    assert fresh is not None
    assert fresh.error is not None and "FFmpeg" in fresh.error


@pytest.mark.skipif(FFMPEG is None, reason="needs a real ffmpeg for postprocessing")
def test_smart_download_mp3_extraction(
    server: MediaServer, db: Database, dest: Path, tmp_path: Path
):
    data = make_mp4(tmp_path / "src.mp4", seconds=2, with_audio=True)
    url = server.add("/real.mp4", data, content_type="video/mp4")
    job = _smart_job(db, url, dest, "song.mp3", audio_format="mp3")

    status = SmartDownload(db, job, ffmpeg_path=FFMPEG).run()

    assert status is JobStatus.COMPLETED
    fresh = db.get_job(job.id)
    assert fresh is not None
    assert fresh.filename.endswith(".mp3")
    output = dest / fresh.filename
    assert output.exists() and output.stat().st_size > 0
    assert not (dest / "song.mp4").exists()  # intermediate got cleaned up


@pytest.mark.skipif(FFMPEG is None, reason="needs a real ffmpeg for remuxing")
def test_smart_download_video_with_metadata_pass(
    server: MediaServer, db: Database, dest: Path, tmp_path: Path
):
    data = make_mp4(tmp_path / "src.mp4", seconds=2, with_audio=True)
    url = server.add("/meta.mp4", data, content_type="video/mp4")
    job = _smart_job(db, url, dest, "tagged.mp4")

    status = SmartDownload(db, job, ffmpeg_path=FFMPEG).run()

    assert status is JobStatus.COMPLETED
    output = dest / "tagged.mp4"
    assert output.exists() and output.stat().st_size > 0
