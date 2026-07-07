"""Download queue manager (F0.4): concurrency limit, pause/resume/cancel,
and per-kind engine dispatch (direct → segmenter, smart → yt-dlp, hls → FFmpeg).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.core import categories, naming
from app.core.downloader import SegmentedDownload
from app.core.ffmpeg import find_ffmpeg
from app.core.models import Job, JobKind, JobStatus
from app.core.settings import Settings
from app.db.database import Database
from app.engines.hls import HlsDownload
from app.engines.smart import MediaInfo, QualityOption, SmartDownload

log = logging.getLogger(__name__)


class DownloadTask(Protocol):
    """What every engine's one-shot download object provides."""

    def run(self) -> JobStatus: ...
    def pause(self) -> None: ...
    def cancel(self) -> None: ...
    @property
    def bytes_downloaded(self) -> int: ...


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
    kind: JobKind = JobKind.DIRECT
    title: str | None = None

    @property
    def display_name(self) -> str:
        return self.title or self.filename


class DownloadManager:
    def __init__(
        self,
        db: Database,
        *,
        settings: Settings | None = None,
        max_concurrent: int | None = None,
        connections: int | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or Settings(db)
        self.max_concurrent = (
            max_concurrent if max_concurrent is not None else self.settings.max_concurrent
        )
        self.connections = connections if connections is not None else self.settings.connections
        self._cond = threading.Condition()
        self._active: dict[int, DownloadTask] = {}
        self._threads: dict[int, threading.Thread] = {}
        self._running = True
        self._scheduler = threading.Thread(target=self._loop, name="gl-scheduler", daemon=True)
        self._scheduler.start()

    # ------------------------------------------------------------- adding

    def _dest_for(self, filename: str, dest_dir: str | Path | None) -> str:
        if dest_dir is not None:
            return str(dest_dir)
        return str(
            categories.dest_dir_for(
                self.settings.download_dir,
                filename,
                enabled=self.settings.categories_enabled,
            )
        )

    def add_url(
        self,
        url: str,
        dest_dir: str | Path | None = None,
        filename: str | None = None,
    ) -> Job:
        """Queue a direct (segmented) download."""
        name = naming.sanitize_filename(filename) if filename else naming.filename_from_url(url)
        job = self.db.create_job(url, self._dest_for(name, dest_dir), name)
        self._kick()
        return job

    def add_smart(
        self,
        url: str,
        media: MediaInfo,
        option: QualityOption,
        *,
        dest_dir: str | Path | None = None,
        subtitles: Mapping[str, Any] | None = None,
        trim: tuple[float, float] | None = None,
        use_session: bool = False,
        session_browser: str = "chrome",
    ) -> Job:
        """Queue a Smart Engine (yt-dlp) download with a chosen quality option."""
        extension = option.audio_format if option.kind == "audio" else "mp4"
        base = naming.sanitize_filename(media.title)
        filename = f"{base}.{extension}"
        options: dict[str, Any] = {
            "format_spec": option.format_spec,
            "quality_label": option.label,
            "audio_format": option.audio_format,
            "subtitles": dict(subtitles) if subtitles else None,
            "trim": list(trim) if trim else None,
            "use_session": use_session,
            "session_browser": session_browser,
        }
        job = self.db.create_job(
            url,
            self._dest_for(filename, dest_dir),
            filename,
            kind=JobKind.SMART,
            title=media.title,
            options=options,
        )
        self._kick()
        return job

    def add_hls(
        self,
        url: str,
        *,
        dest_dir: str | Path | None = None,
        title: str | None = None,
    ) -> Job:
        """Queue an HLS/DASH stream for FFmpeg reassembly."""
        stem = Path(naming.filename_from_url(url)).stem or "stream"
        base = naming.sanitize_filename(title) if title else stem
        filename = f"{base}.mp4"
        job = self.db.create_job(
            url,
            self._dest_for(filename, dest_dir),
            filename,
            kind=JobKind.HLS,
            title=title,
        )
        self._kick()
        return job

    # ------------------------------------------------------------ control

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
            task = active.get(job.id)
            downloaded = task.bytes_downloaded if task is not None else self.db.stored_progress(job)
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
                    kind=job.kind,
                    title=job.title,
                )
            )
        return views

    def shutdown(self, timeout: float = 10.0) -> None:
        """Pause everything in flight so it resumes cleanly next launch."""
        with self._cond:
            self._running = False
            active = list(self._active.values())
            self._cond.notify_all()
        for task in active:
            task.pause()
        self._scheduler.join(timeout=timeout)
        with self._cond:
            threads = list(self._threads.values())
        for thread in threads:
            thread.join(timeout=timeout)

    # ---------------------------------------------------------- scheduler

    def _create_task(self, job: Job) -> DownloadTask:
        if job.kind is JobKind.SMART:
            return SmartDownload(self.db, job, ffmpeg_path=find_ffmpeg(self.settings))
        if job.kind is JobKind.HLS:
            return HlsDownload(self.db, job, ffmpeg_path=find_ffmpeg(self.settings))
        return SegmentedDownload(self.db, job, connections=self.connections)

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
                        task = self._create_task(job)
                        thread = threading.Thread(
                            target=self._run_job,
                            args=(job, task),
                            name=f"gl-job-{job.id}",
                            daemon=True,
                        )
                        self._active[job.id] = task
                        self._threads[job.id] = thread
                        thread.start()
                        continue
                self._cond.wait(timeout=0.5)

    def _next_queued(self) -> Job | None:
        for job in self.db.list_jobs():
            if job.status is JobStatus.QUEUED and job.id not in self._active:
                return job
        return None

    def _run_job(self, job: Job, task: DownloadTask) -> None:
        try:
            status = task.run()
            log.info("job %s (%s) finished with status %s", job.id, job.filename, status.value)
        finally:
            with self._cond:
                self._active.pop(job.id, None)
                self._threads.pop(job.id, None)
                self._cond.notify_all()
