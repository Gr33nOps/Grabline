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


def _no_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin 'no JS runtime installed' so tests don't depend on the machine."""
    monkeypatch.setattr("app.core.jsruntime.detect_js_runtime", lambda *a, **k: None)


def test_normal_video_takes_the_fast_path(
    db: Database, dest: Path, monkeypatch: pytest.MonkeyPatch
):
    # No runtime installed anywhere: one jsless attempt, no cookies, no retry.
    _no_runtime(monkeypatch)
    job = _smart_job(db, "https://youtu.be/x", dest, "v.mp4", session_browser="firefox")
    task = SmartDownload(db, job, ffmpeg_path=None)
    calls: list[tuple[bool, bool]] = []

    def fake_download(*, with_cookies: bool, with_runtime: bool) -> dict[str, Any]:
        calls.append((with_cookies, with_runtime))
        return {"title": "ok"}

    monkeypatch.setattr(task, "_download", fake_download)
    assert task._download_smart() == {"title": "ok"}
    assert calls == [(False, False)]  # no runtime, no cookies, no retry


def test_installed_runtime_is_used_from_the_start(
    db: Database, dest: Path, monkeypatch: pytest.MonkeyPatch
):
    # The 'every YouTube video is slow' fix: an already-installed runtime is
    # used on attempt one (solver cached -> seconds), not after a doomed
    # jsless attempt plus a fresh escalation per video.
    monkeypatch.setattr(
        "app.core.jsruntime.detect_js_runtime", lambda *a, **k: ("node", "/usr/bin/node")
    )
    job = _smart_job(db, "https://youtu.be/x", dest, "v.mp4", session_browser="firefox")
    task = SmartDownload(db, job, ffmpeg_path=None)
    calls: list[tuple[bool, bool]] = []

    def fake_download(*, with_cookies: bool, with_runtime: bool) -> dict[str, Any]:
        calls.append((with_cookies, with_runtime))
        return {"title": "ok"}

    monkeypatch.setattr(task, "_download", fake_download)
    assert task._download_smart() == {"title": "ok"}
    assert calls == [(False, True)]  # runtime on, still no cookies, one attempt


def test_age_wall_escalates_to_runtime_and_login(
    db: Database, dest: Path, monkeypatch: pytest.MonkeyPatch
):
    # Age-restricted: the first try hits the wall, so retry with the browser
    # login (and provision a runtime for the signed-in client) - no toggle.
    import yt_dlp

    _no_runtime(monkeypatch)
    job = _smart_job(db, "https://youtu.be/x", dest, "v.mp4", session_browser="firefox")
    task = SmartDownload(db, job, ffmpeg_path=None)

    def fake_ensure() -> None:  # a successful Deno provisioning
        task._js_runtime = ("deno", "/x/deno")

    monkeypatch.setattr(task, "_ensure_js_runtime", fake_ensure)
    calls: list[tuple[bool, bool]] = []

    def fake_download(*, with_cookies: bool, with_runtime: bool) -> dict[str, Any]:
        calls.append((with_cookies, with_runtime))
        if not with_cookies:
            raise yt_dlp.utils.DownloadError("Sign in to confirm your age")
        return {"title": "ok"}

    monkeypatch.setattr(task, "_download", fake_download)
    assert task._download_smart() == {"title": "ok"}
    assert calls == [(False, False), (True, True)]  # fast, then runtime + login


def test_format_error_escalates_to_runtime_without_login(
    db: Database, dest: Path, monkeypatch: pytest.MonkeyPatch
):
    # A bare format error means the n challenge was skipped: add the runtime
    # (+ solver), but no login - it isn't an auth wall.
    import yt_dlp

    _no_runtime(monkeypatch)
    job = _smart_job(db, "https://youtu.be/x", dest, "v.mp4", session_browser="firefox")
    task = SmartDownload(db, job, ffmpeg_path=None)

    def fake_ensure() -> None:
        task._js_runtime = ("deno", "/x/deno")

    monkeypatch.setattr(task, "_ensure_js_runtime", fake_ensure)
    calls: list[tuple[bool, bool]] = []

    def fake_download(*, with_cookies: bool, with_runtime: bool) -> dict[str, Any]:
        calls.append((with_cookies, with_runtime))
        if not with_runtime:
            raise yt_dlp.utils.DownloadError("Requested format is not available")
        return {"title": "ok"}

    monkeypatch.setattr(task, "_download", fake_download)
    assert task._download_smart() == {"title": "ok"}
    assert calls == [(False, False), (False, True)]  # fast, then runtime, no cookies


def test_no_login_escalation_when_no_browser_found(
    db: Database, dest: Path, monkeypatch: pytest.MonkeyPatch
):
    import yt_dlp

    _no_runtime(monkeypatch)
    job = _smart_job(db, "https://youtu.be/x", dest, "v.mp4")  # no session_browser set
    task = SmartDownload(db, job, ffmpeg_path=None)
    monkeypatch.setattr("app.core.browser_setup.detect_cookie_browser", lambda *a, **k: None)

    def fake_download(*, with_cookies: bool, with_runtime: bool) -> dict[str, Any]:
        raise yt_dlp.utils.DownloadError("Sign in to confirm your age")

    monkeypatch.setattr(task, "_download", fake_download)
    with pytest.raises(yt_dlp.utils.DownloadError):
        task._download_smart()  # an auth wall with no browser to log in with


def test_unrelated_error_is_not_retried(db: Database, dest: Path, monkeypatch: pytest.MonkeyPatch):
    import yt_dlp

    _no_runtime(monkeypatch)
    job = _smart_job(db, "https://youtu.be/x", dest, "v.mp4", session_browser="firefox")
    task = SmartDownload(db, job, ffmpeg_path=None)
    calls: list[tuple[bool, bool]] = []

    def fake_download(*, with_cookies: bool, with_runtime: bool) -> dict[str, Any]:
        calls.append((with_cookies, with_runtime))
        raise yt_dlp.utils.DownloadError("This live event will begin in 2 hours")

    monkeypatch.setattr(task, "_download", fake_download)
    with pytest.raises(yt_dlp.utils.DownloadError):
        task._download_smart()  # a scheduled premiere isn't runtime- or login-fixable
    assert calls == [(False, False)]  # tried once, no slow retry


def test_build_options_includes_cookies_only_when_asked(db: Database, dest: Path):
    job = _smart_job(db, "https://youtu.be/x", dest, "v.mp4", session_browser="firefox")
    task = SmartDownload(db, job, ffmpeg_path=None)
    assert "cookiesfrombrowser" not in task._build_options()
    assert task._build_options(with_cookies=True)["cookiesfrombrowser"] == ("firefox",)


def test_build_options_wires_the_post_processing_extras(db: Database, dest: Path):
    """SponsorBlock, chapters, sidecars, a cookies file and custom ffmpeg args
    all reach the yt-dlp option dict (the ones that need FFmpeg are gated on it)."""
    cookies = dest / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    job = _smart_job(
        db,
        "https://youtu.be/x",
        dest,
        "v.mp4",
        sponsorblock="remove",
        chapters=True,
        save_thumbnail=True,
        save_metadata=True,
        cookie_file=str(cookies),
        ffmpeg_args=["-metadata", "comment=grabline"],
    )
    task = SmartDownload(db, job, ffmpeg_path="/usr/bin/ffmpeg")
    opts = task._build_options()
    keys = {pp["key"] for pp in opts["postprocessors"]}
    assert "SponsorBlock" in keys and "ModifyChapters" in keys
    assert opts["writethumbnail"] is True
    assert opts["writeinfojson"] is True
    assert opts["cookiefile"] == str(cookies)  # a cookies file wins over the browser
    assert opts["postprocessor_args"] == {"default": ["-metadata", "comment=grabline"]}


def test_build_options_skips_ffmpeg_extras_without_ffmpeg(db: Database, dest: Path):
    """No FFmpeg means no SponsorBlock/chapters passes - but the sidecar writes,
    which yt-dlp does itself, still happen."""
    job = _smart_job(
        db, "https://youtu.be/x", dest, "v.mp4", sponsorblock="mark", save_thumbnail=True
    )
    task = SmartDownload(db, job, ffmpeg_path=None)
    opts = task._build_options()
    assert not any(pp["key"] == "SponsorBlock" for pp in opts["postprocessors"])
    assert opts["writethumbnail"] is True


def test_build_options_passes_runtime_only_on_escalation(db: Database, dest: Path):
    task = SmartDownload(db, _smart_job(db, "https://youtu.be/x", dest, "v.mp4"), ffmpeg_path=None)
    task._js_runtime = ("node", "/usr/bin/node")  # an existing Node, not Deno
    # Fast path omits the runtime even when one is available (that's the speed win).
    assert "js_runtimes" not in task._build_options()
    # Escalated path passes the runtime by name plus the EJS solver fetch.
    opts = task._build_options(with_runtime=True)
    assert opts["js_runtimes"] == {"node": {"path": "/usr/bin/node"}}
    assert opts["remote_components"] == ["ejs:github"]


def test_existing_runtime_used_without_downloading(
    db: Database, dest: Path, monkeypatch: pytest.MonkeyPatch
):
    from app.core import jsruntime

    monkeypatch.setattr(jsruntime, "detect_js_runtime", lambda *a, **k: ("node", "/usr/bin/node"))

    def no_download(**_kw: object) -> Path:
        raise AssertionError("must not download when a runtime already exists")

    monkeypatch.setattr(jsruntime, "ensure_deno", no_download)
    task = SmartDownload(db, _smart_job(db, "https://youtu.be/x", dest, "v.mp4"), ffmpeg_path=None)
    task._ensure_js_runtime()
    assert task._js_runtime == ("node", "/usr/bin/node")


def test_downloads_deno_when_no_runtime_and_only_for_youtube_or_session(
    db: Database, dest: Path, monkeypatch: pytest.MonkeyPatch
):
    from app.core import jsruntime

    monkeypatch.setattr(jsruntime, "detect_js_runtime", lambda *a, **k: None)
    calls: list[str] = []

    def fake_ensure(**_kw: object) -> Path:
        calls.append("deno")
        return Path("/x/deno")

    monkeypatch.setattr(jsruntime, "ensure_deno", fake_ensure)

    # Non-YouTube, no session: not needed, so nothing is fetched.
    other = SmartDownload(
        db, _smart_job(db, "https://soundcloud.com/a/b", dest, "a.mp3"), ffmpeg_path=None
    )
    other._ensure_js_runtime()
    assert calls == [] and other._js_runtime is None

    # YouTube, no session: Deno fetched because nothing is installed.
    yt = SmartDownload(db, _smart_job(db, "https://youtu.be/x", dest, "v.mp4"), ffmpeg_path=None)
    yt._ensure_js_runtime()
    assert calls == ["deno"] and yt._js_runtime == ("deno", "/x/deno")


def test_js_runtime_failure_is_non_fatal(db: Database, dest: Path, monkeypatch: pytest.MonkeyPatch):
    from app.core import jsruntime
    from app.core.errors import DownloadError

    monkeypatch.setattr(jsruntime, "detect_js_runtime", lambda *a, **k: None)

    def boom(**_kw: object) -> Path:
        raise DownloadError("no network")

    monkeypatch.setattr(jsruntime, "ensure_deno", boom)
    task = SmartDownload(
        db, _smart_job(db, "https://youtu.be/x", dest, "v.mp4", use_session=True), ffmpeg_path=None
    )
    task._ensure_js_runtime()  # must not raise
    assert task._js_runtime is None


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
