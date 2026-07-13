from __future__ import annotations

from pathlib import Path

import pytest

from app.core.manager import DownloadManager
from app.core.models import JobKind, JobStatus
from app.core.settings import Settings
from app.db.database import Database
from app.engines.smart import MediaInfo, QualityOption
from app.tests.conftest import sha256_file, wait_for
from app.tests.media_server import MediaServer, payload, sha256

MB = 1024 * 1024


def _status(db: Database, job_id: int) -> JobStatus:
    job = db.get_job(job_id)
    assert job is not None
    return job.status


def test_queue_respects_concurrency_and_completes_all(
    server: MediaServer, db: Database, dest: Path
):
    datas = [payload(400_000, seed) for seed in range(3)]
    urls = [server.add(f"/f{i}.bin", datas[i]) for i in range(3)]
    manager = DownloadManager(db, max_concurrent=2)
    try:
        jobs = [manager.add_url(url, dest) for url in urls]
        wait_for(
            lambda: all(_status(db, job.id) is JobStatus.COMPLETED for job in jobs),
            timeout=60,
        )
    finally:
        manager.shutdown()
    for i in range(3):
        assert sha256_file(dest / f"f{i}.bin") == sha256(datas[i])


def test_add_url_threads_headers_into_a_gated_download(
    server: MediaServer, db: Database, dest: Path
):
    data = payload(400_000, 41)
    url = server.add("/gated.bin", data, required_headers={"Cookie": "session=abc"})
    manager = DownloadManager(db, max_concurrent=1)
    try:
        job = manager.add_url(url, dest, headers={"Cookie": "session=abc"})
        assert job.options["http_headers"] == {"Cookie": "session=abc"}
        wait_for(lambda: _status(db, job.id) is JobStatus.COMPLETED, timeout=60)
    finally:
        manager.shutdown()
    assert sha256_file(dest / "gated.bin") == sha256(data)
    assert server.received_headers("/gated.bin")["cookie"] == "session=abc"


def test_manager_pause_and_resume(server: MediaServer, db: Database, dest: Path):
    data = payload(4 * MB, 9)
    url = server.add("/s.bin", data, chunk_size=32 * 1024, delay_per_chunk=0.03)
    manager = DownloadManager(db, max_concurrent=1)
    try:
        job = manager.add_url(url, dest)
        wait_for(lambda: db.job_downloaded(job.id) > 512 * 1024, timeout=60)
        manager.pause(job.id)
        wait_for(lambda: _status(db, job.id) is JobStatus.PAUSED, timeout=30)
        manager.resume(job.id)
        wait_for(lambda: _status(db, job.id) is JobStatus.COMPLETED, timeout=60)
    finally:
        manager.shutdown()
    assert sha256_file(dest / "s.bin") == sha256(data)


def test_manager_dispatches_smart_jobs(
    server: MediaServer, db: Database, dest: Path, monkeypatch: pytest.MonkeyPatch
):
    # Force ffmpeg_path=None: no postprocessing, so served bytes come through
    # untouched and the checksum must match.
    monkeypatch.setattr("app.core.manager.find_ffmpeg", lambda settings: None)
    data = payload(600_000, 21)
    url = server.add("/tube.mp4", data, content_type="video/mp4")
    media = MediaInfo(
        url=url,
        id="x",
        title="Manager Clip",
        uploader=None,
        duration=None,
        thumbnail_url=None,
        options=(QualityOption(label="Best", kind="video", format_spec="b"),),
    )
    manager = DownloadManager(db, max_concurrent=1)
    try:
        job = manager.add_smart(url, media, media.options[0], dest_dir=dest)
        assert job.kind is JobKind.SMART
        wait_for(lambda: _status(db, job.id) is JobStatus.COMPLETED, timeout=60)
        views = {view.id: view for view in manager.snapshot()}
        assert views[job.id].display_name == "Manager Clip"
    finally:
        manager.shutdown()
    assert sha256_file(dest / "Manager Clip.mp4") == sha256(data)


def test_add_smart_entry_for_playlist_items(db: Database, dest: Path):
    from app.engines.smart import generic_quality_options

    manager = DownloadManager(db, max_concurrent=0)
    try:
        option = generic_quality_options()[0]
        job = manager.add_smart_entry(
            "https://tube.example/watch?v=xyz", "Episode 12", option, dest_dir=dest
        )
        assert job.kind is JobKind.SMART
        assert job.title == "Episode 12"
        assert job.filename == "Episode 12.mp4"
        assert job.options["format_spec"] == option.format_spec
    finally:
        manager.shutdown()


def test_remove_deletes_row_but_keeps_completed_file(db: Database, dest: Path):
    manager = DownloadManager(db, max_concurrent=0)
    try:
        job = db.create_job("http://x.test/keep.bin", str(dest), "keep.bin")
        db.set_job_status(job.id, JobStatus.COMPLETED)
        artifact = dest / "keep.bin"
        artifact.write_bytes(b"data")
        manager.remove(job.id)
        assert db.get_job(job.id) is None
        assert artifact.exists()  # history removal never deletes finished files
    finally:
        manager.shutdown()


def test_reload_settings_applies_speed_cap(db: Database):
    from app.core.settings import Settings

    settings = Settings(db)
    manager = DownloadManager(db, settings=settings, max_concurrent=0)
    try:
        assert manager.limiter.rate == 0
        settings.speed_limit_kbps = 512
        manager.reload_settings()
        assert manager.limiter.rate == 512 * 1024
        # dynamic concurrency: no override given at construction
        dynamic = DownloadManager(db, settings=settings)
        try:
            settings.max_concurrent = 7
            assert dynamic.max_concurrent == 7
        finally:
            dynamic.shutdown()
    finally:
        manager.shutdown()


def test_add_url_sorts_into_categories(server: MediaServer, db: Database, tmp_path: Path):
    url = server.add("/report.pdf", payload(10_000, 23))
    settings = Settings(db)
    settings.download_dir = tmp_path / "base"
    manager = DownloadManager(db, settings=settings, max_concurrent=0)
    try:
        job = manager.add_url(url)
        assert job.dest_dir == str(tmp_path / "base" / "Documents")
        settings.categories_enabled = False
        job2 = manager.add_url(url)
        assert job2.dest_dir == str(tmp_path / "base")
    finally:
        manager.shutdown()


def test_snapshot_reports_progress(server: MediaServer, db: Database, dest: Path):
    data = payload(300_000, 5)
    url = server.add("/snap.bin", data)
    manager = DownloadManager(db, max_concurrent=1)
    try:
        job = manager.add_url(url, dest)
        wait_for(lambda: _status(db, job.id) is JobStatus.COMPLETED, timeout=60)
        views = manager.snapshot()
    finally:
        manager.shutdown()
    assert len(views) == 1
    view = views[0]
    assert view.id == job.id
    assert view.status is JobStatus.COMPLETED
    assert view.downloaded == len(data)
    assert view.total_size == len(data)


def test_connection_budget_is_shared_across_active_jobs(db: Database, dest: Path):
    # A job starting while others run gets a slice of the connection budget,
    # not another full set of sockets that would starve its siblings.
    from app.core.downloader import SegmentedDownload

    def segmented(url: str, name: str) -> SegmentedDownload:
        task = manager._create_task(db.create_job(url, str(dest), name))
        assert isinstance(task, SegmentedDownload)
        return task

    manager = DownloadManager(db, max_concurrent=3)
    try:
        manager._connections_override = 16
        alone = segmented("https://x.test/a.bin", "a.bin")
        assert alone.connections == 16  # nothing else running: full budget

        manager._active[1] = alone  # simulate one running download
        second = segmented("https://x.test/b.bin", "b.bin")
        assert second.connections == 8  # 16 // 2

        manager._active[2] = second
        third = segmented("https://x.test/c.bin", "c.bin")
        assert third.connections == 5  # 16 // 3
    finally:
        manager._active.clear()
        manager.shutdown()


def test_429_and_408_are_transient_but_404_is_permanent():
    from app.core.manager import _is_transient_error

    assert _is_transient_error("server responded with HTTP 429")
    assert _is_transient_error("HTTP Error 408: Request Timeout")
    assert _is_transient_error("could not reach server: timeout")
    assert not _is_transient_error("server responded with HTTP 404")
    assert not _is_transient_error("server responded with HTTP 403")


def test_retry_forever_when_max_is_zero(db: Database, dest: Path):
    settings = Settings(db)
    settings.auto_retry = True
    settings.auto_retry_max = 0  # 0 = forever
    manager = DownloadManager(db, settings=settings, max_concurrent=0)
    try:
        job = db.create_job("https://x.test/f.bin", str(dest), "f.bin")
        db.set_job_status(job.id, JobStatus.FAILED, error="could not reach server: timeout")
        db.set_retry_count(job.id, 50)  # far past any finite cap
        assert manager._schedule_retry(job.id) is True
        fresh = db.get_job(job.id)
        assert fresh is not None and fresh.retry_count == 51
    finally:
        manager.shutdown()


def test_mirror_failover_downloads_from_the_next_url(server: MediaServer, db: Database, dest: Path):
    # First URL 404s (permanent - no point retrying it); the job must switch
    # to its mirror and complete from there.
    data = payload(300_000, 61)
    dead = server.url("/gone.bin")  # never added -> 404
    mirror = server.add("/mirror.bin", data)
    manager = DownloadManager(db, max_concurrent=1)
    try:
        job = manager.add_url(dead, dest, filename="m.bin", mirrors=[mirror])
        assert job.options["mirrors"] == [mirror]
        wait_for(lambda: _status(db, job.id) is JobStatus.COMPLETED, timeout=60)
        fresh = db.get_job(job.id)
        assert fresh is not None
        assert fresh.url == mirror  # switched
        assert fresh.options["mirrors"] == []  # consumed
    finally:
        manager.shutdown()
    assert sha256_file(dest / "m.bin") == sha256(data)


def test_pinned_connections_bypass_the_share_split(db: Database, dest: Path):
    from app.core.downloader import SegmentedDownload

    manager = DownloadManager(db, max_concurrent=3)
    try:
        manager._connections_override = 16
        # Something already running, so the share-split would normally apply.
        other = db.create_job("https://x.test/other.bin", str(dest), "other.bin")
        manager._active[1] = manager._create_task(other)
        job = db.create_job("https://x.test/p.bin", str(dest), "p.bin", options={"connections": 24})
        task = manager._create_task(job)
        assert isinstance(task, SegmentedDownload)
        assert task.connections == 24  # the explicit pin wins over the split

        manager.set_job_connections(job.id, 500)  # clamped
        fresh = db.get_job(job.id)
        assert fresh is not None and fresh.options["connections"] == 128
        manager.set_job_connections(job.id, 0)  # back to automatic
        fresh = db.get_job(job.id)
        assert fresh is not None and "connections" not in fresh.options
    finally:
        manager._active.clear()
        manager.shutdown()
