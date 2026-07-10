"""SmartDownload exercised end-to-end through yt-dlp's generic extractor
against the local media server - the full engine pipeline without YouTube.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

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

    # ffmpeg_path=None: no postprocessing - bytes must come through untouched.
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


def test_cookie_fallback_retries_without_cookies(
    db: Database, dest: Path, monkeypatch: pytest.MonkeyPatch
):
    # Cookies force YouTube's JS-only web client; on a JS-less PC that yields
    # "format not available". The engine must retry cookie-free and succeed.
    import yt_dlp

    job = _smart_job(db, "https://youtu.be/x", dest, "v.mp4", use_session=True)
    task = SmartDownload(db, job, ffmpeg_path=None)
    calls: list[bool] = []

    def fake_download(*, drop_cookies: bool = False) -> dict[str, Any]:
        calls.append(drop_cookies)
        if not drop_cookies:
            raise yt_dlp.utils.DownloadError("Requested format is not available")
        return {"title": "ok"}

    monkeypatch.setattr(task, "_download", fake_download)
    assert task._download_with_cookie_fallback() == {"title": "ok"}
    assert calls == [False, True]  # first with cookies, then without


def test_cookie_fallback_only_when_session_on(
    db: Database, dest: Path, monkeypatch: pytest.MonkeyPatch
):
    import yt_dlp

    job = _smart_job(db, "https://youtu.be/x", dest, "v.mp4", use_session=False)
    task = SmartDownload(db, job, ffmpeg_path=None)

    def fake_download(*, drop_cookies: bool = False) -> dict[str, Any]:
        raise yt_dlp.utils.DownloadError("Requested format is not available")

    monkeypatch.setattr(task, "_download", fake_download)
    with pytest.raises(yt_dlp.utils.DownloadError):
        task._download_with_cookie_fallback()  # no cookies were used: no retry


def test_cookie_fallback_ignores_unrelated_errors(
    db: Database, dest: Path, monkeypatch: pytest.MonkeyPatch
):
    import yt_dlp

    job = _smart_job(db, "https://youtu.be/x", dest, "v.mp4", use_session=True)
    task = SmartDownload(db, job, ffmpeg_path=None)

    def fake_download(*, drop_cookies: bool = False) -> dict[str, Any]:
        raise yt_dlp.utils.DownloadError("Private video")

    monkeypatch.setattr(task, "_download", fake_download)
    with pytest.raises(yt_dlp.utils.DownloadError):
        task._download_with_cookie_fallback()  # a private video won't be fixed cookie-free


def test_js_runtime_provisioned_only_with_session(
    db: Database, dest: Path, monkeypatch: pytest.MonkeyPatch
):
    from app.core import jsruntime

    calls: list[str] = []

    def fake_ensure(**_kw: object) -> Path:
        calls.append("deno")
        return Path("/x/deno")

    monkeypatch.setattr(jsruntime, "ensure_deno", fake_ensure)

    off = SmartDownload(db, _smart_job(db, "https://youtu.be/x", dest, "v.mp4"), ffmpeg_path=None)
    off._ensure_js_runtime()
    assert calls == [] and off._deno_path is None  # session off: no runtime fetched

    on = SmartDownload(
        db, _smart_job(db, "https://youtu.be/x", dest, "v.mp4", use_session=True), ffmpeg_path=None
    )
    on._ensure_js_runtime()
    assert calls == ["deno"] and on._deno_path == "/x/deno"


def test_js_runtime_failure_is_non_fatal(db: Database, dest: Path, monkeypatch: pytest.MonkeyPatch):
    from app.core import jsruntime
    from app.core.errors import DownloadError

    def boom(**_kw):
        raise DownloadError("no network")

    monkeypatch.setattr(jsruntime, "ensure_deno", boom)
    task = SmartDownload(
        db, _smart_job(db, "https://youtu.be/x", dest, "v.mp4", use_session=True), ffmpeg_path=None
    )
    task._ensure_js_runtime()  # must not raise
    assert task._deno_path is None


def test_deno_path_is_passed_to_ytdlp(db: Database, dest: Path):
    task = SmartDownload(db, _smart_job(db, "https://youtu.be/x", dest, "v.mp4"), ffmpeg_path=None)
    assert "js_runtimes" not in task._build_options()
    task._deno_path = "/opt/deno"
    assert task._build_options()["js_runtimes"] == {"deno": {"path": "/opt/deno"}}


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
