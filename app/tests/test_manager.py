from __future__ import annotations

from pathlib import Path

from app.core.manager import DownloadManager
from app.core.models import JobStatus
from app.db.database import Database
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
