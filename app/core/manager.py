"""Download queue manager (F0.4): concurrency limit, pause/resume/cancel."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from app.core import naming
from app.core.downloader import DEFAULT_CONNECTIONS, SegmentedDownload
from app.core.models import Job, JobStatus
from app.db.database import Database

log = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENT = 3


@dataclass(frozen=True)
class JobView:
    """A read-only snapshot of one job for the UI."""

    id: int
    url: str
    filename: str
    dest_dir: str
    status: JobStatus
    total_size: int | None
    downloaded: int
    error: str | None


class DownloadManager:
    def __init__(
        self,
        db: Database,
        *,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        connections: int = DEFAULT_CONNECTIONS,
    ) -> None:
        self.db = db
        self.max_concurrent = max_concurrent
        self.connections = connections
        self._cond = threading.Condition()
        self._active: dict[int, SegmentedDownload] = {}
        self._threads: dict[int, threading.Thread] = {}
        self._running = True
        self._scheduler = threading.Thread(target=self._loop, name="gl-scheduler", daemon=True)
        self._scheduler.start()

    # ------------------------------------------------------------- public

    def add_url(self, url: str, dest_dir: str | Path, filename: str | None = None) -> Job:
        name = naming.sanitize_filename(filename) if filename else naming.filename_from_url(url)
        job = self.db.create_job(url, str(dest_dir), name)
        self._kick()
        return job

    def pause(self, job_id: int) -> None:
        with self._cond:
            active = self._active.get(job_id)
        if active is not None:
            active.pause()
            return
        job = self.db.get_job(job_id)
        if job is not None and job.status is JobStatus.QUEUED:
            self.db.set_job_status(job_id, JobStatus.PAUSED)

    def resume(self, job_id: int) -> None:
        job = self.db.get_job(job_id)
        if job is not None and job.status in (
            JobStatus.PAUSED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        ):
            self.db.set_job_status(job_id, JobStatus.QUEUED)
            self._kick()

    def cancel(self, job_id: int) -> None:
        with self._cond:
            active = self._active.get(job_id)
        if active is not None:
            active.cancel()
            return
        job = self.db.get_job(job_id)
        if job is not None and job.status in (
            JobStatus.QUEUED,
            JobStatus.PAUSED,
            JobStatus.FAILED,
        ):
            job.part_path.unlink(missing_ok=True)
            self.db.clear_segments(job_id)
            self.db.set_job_status(job_id, JobStatus.CANCELLED)

    def snapshot(self) -> list[JobView]:
        with self._cond:
            active = dict(self._active)
        views: list[JobView] = []
        for job in self.db.list_jobs():
            download = active.get(job.id)
            downloaded = (
                download.bytes_downloaded
                if download is not None
                else self.db.job_downloaded(job.id)
            )
            views.append(
                JobView(
                    id=job.id,
                    url=job.url,
                    filename=job.filename,
                    dest_dir=job.dest_dir,
                    status=job.status,
                    total_size=job.total_size,
                    downloaded=downloaded,
                    error=job.error,
                )
            )
        return views

    def shutdown(self, timeout: float = 10.0) -> None:
        """Pause everything in flight so it resumes cleanly next launch."""
        with self._cond:
            self._running = False
            active = list(self._active.values())
            self._cond.notify_all()
        for download in active:
            download.pause()
        self._scheduler.join(timeout=timeout)
        with self._cond:
            threads = list(self._threads.values())
        for thread in threads:
            thread.join(timeout=timeout)

    # ---------------------------------------------------------- scheduler

    def _kick(self) -> None:
        with self._cond:
            self._cond.notify_all()

    def _loop(self) -> None:
        while True:
            with self._cond:
                if not self._running:
                    return
                if len(self._active) < self.max_concurrent:
                    job = self._next_queued()
                    if job is not None:
                        download = SegmentedDownload(self.db, job, connections=self.connections)
                        thread = threading.Thread(
                            target=self._run_job,
                            args=(job, download),
                            name=f"gl-job-{job.id}",
                            daemon=True,
                        )
                        self._active[job.id] = download
                        self._threads[job.id] = thread
                        thread.start()
                        continue
                self._cond.wait(timeout=0.5)

    def _next_queued(self) -> Job | None:
        for job in self.db.list_jobs():
            if job.status is JobStatus.QUEUED and job.id not in self._active:
                return job
        return None

    def _run_job(self, job: Job, download: SegmentedDownload) -> None:
        try:
            status = download.run()
            log.info("job %s (%s) finished with status %s", job.id, job.filename, status.value)
        finally:
            with self._cond:
                self._active.pop(job.id, None)
                self._threads.pop(job.id, None)
                self._cond.notify_all()
