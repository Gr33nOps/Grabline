"""Download queue manager (F0.4): concurrency limit, pause/resume/cancel,
and per-kind engine dispatch (direct → segmenter, smart → yt-dlp, hls → FFmpeg).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from app.core import categories, naming
from app.core.downloader import SegmentedDownload
from app.core.ffmpeg import find_ffmpeg
from app.core.models import Job, JobKind, JobStatus
from app.core.ratelimit import RateLimiter
from app.core.settings import Settings
from app.db.database import Database
from app.engines.hls import HlsDownload
from app.engines.manifest import HlsVariant
from app.engines.smart import MediaInfo, QualityOption, SmartDownload

log = logging.getLogger(__name__)


class DownloadTask(Protocol):
    """What every engine's one-shot download object provides."""

    def run(self) -> JobStatus: ...
    def pause(self) -> None: ...
    def cancel(self) -> None: ...
    @property
    def bytes_downloaded(self) -> int: ...


_RETRY_BASE_SECONDS = 5.0
_RETRY_CAP_SECONDS = 300.0

#: Failures worth an automatic retry are everything EXCEPT these permanent
#: ones (DRM, private, 404s, disk-full ...). Unknown errors are retried, which
#: matches how IDM-style managers reconnect through flaky networks.
_PERMANENT_ERROR_MARKERS = (
    "drm",
    "private",
    "age-restricted",
    "region-blocked",
    "available in your country",
    "unsupported",
    "no downloadable",
    "web page",
    "not enough free disk",
    "did not contain",
    "http 4",
    "http error 4",
    "does not look like",
    "only http",
)


def _is_transient_error(error: str | None) -> bool:
    if not error:
        return False
    lowered = error.lower()
    return not any(marker in lowered for marker in _PERMANENT_ERROR_MARKERS)


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
    speed_limit_kbps: int = 0
    retry_count: int = 0

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
        # Explicit constructor values pin the knob; otherwise settings apply
        # live (reload_settings / next scheduler pass), no restart needed.
        self._max_concurrent_override = max_concurrent
        self._connections_override = connections
        self.limiter = RateLimiter(self.settings.speed_limit_kbps * 1024)
        self._applied_rate: int | None = None
        # One reusable limiter per download that has its own cap; the running
        # task holds the very same instance, so a live change takes effect now.
        self._job_limiters: dict[int, RateLimiter] = {}
        # job id -> monotonic deadline at which an auto-retry becomes due.
        self._retry_at: dict[int, float] = {}
        self._cond = threading.Condition()
        self._active: dict[int, DownloadTask] = {}
        self._threads: dict[int, threading.Thread] = {}
        self._running = True
        self._scheduler = threading.Thread(target=self._loop, name="gl-scheduler", daemon=True)
        self._scheduler.start()

    @property
    def max_concurrent(self) -> int:
        if self._max_concurrent_override is not None:
            return self._max_concurrent_override
        return self.settings.max_concurrent

    @property
    def connections(self) -> int:
        if self._connections_override is not None:
            return self._connections_override
        return self.settings.connections

    def reload_settings(self) -> None:
        """Apply settings changes to live state (speed cap now, slots next pass)."""
        self._apply_global_rate()
        self._kick()

    # -------------------------------------------------- speed limit + schedule

    def _in_full_speed_window(self, now: datetime) -> bool:
        """Is the clock inside the nightly full-speed window? Handles a window
        that wraps past midnight (e.g. 23:00 to 07:00)."""
        try:
            fh, fm = (int(p) for p in self.settings.speed_full_from.split(":"))
            th, tm = (int(p) for p in self.settings.speed_full_to.split(":"))
        except ValueError:
            return False
        start, end, cur = fh * 60 + fm, th * 60 + tm, now.hour * 60 + now.minute
        if start == end:
            return False
        return start <= cur < end if start < end else (cur >= start or cur < end)

    def _effective_global_rate(self) -> int:
        base = self.settings.speed_limit_kbps * 1024
        if (
            base
            and self.settings.speed_schedule_enabled
            and self._in_full_speed_window(datetime.now())
        ):
            return 0  # full speed during the scheduled window
        return base

    def _apply_global_rate(self) -> None:
        rate = self._effective_global_rate()
        if rate != self._applied_rate:
            self.limiter.set_rate(rate)
            self._applied_rate = rate

    # -------------------------------------------------- per-download speed cap

    def _job_limiter_for(self, job: Job) -> RateLimiter | None:
        kbps = int(job.options.get("speed_limit_kbps") or 0)
        if kbps <= 0:
            self._job_limiters.pop(job.id, None)
            return None
        limiter = self._job_limiters.get(job.id)
        if limiter is None:
            limiter = RateLimiter(kbps * 1024)
            self._job_limiters[job.id] = limiter
        else:
            limiter.set_rate(kbps * 1024)
        return limiter

    def set_job_speed(self, job_id: int, kbps: int) -> None:
        """Cap one download to ``kbps`` KB/s (0 clears it). Applies live if it
        is running, and persists for the next run."""
        job = self.db.get_job(job_id)
        if job is None:
            return
        options = dict(job.options)
        if kbps > 0:
            options["speed_limit_kbps"] = kbps
        else:
            options.pop("speed_limit_kbps", None)
        self.db.update_job_options(job_id, options)
        job.options = options
        self._job_limiter_for(job)  # create/update/drop the live limiter

    # -------------------------------------------------------- queue priorities

    def _pending_order(self) -> list[Job]:
        """Jobs waiting to run, in current run order (list_jobs is priority
        sorted already)."""
        return [j for j in self.db.list_jobs() if j.status in (JobStatus.QUEUED, JobStatus.PAUSED)]

    def _reassign(self, order: list[Job]) -> None:
        # Dense, strictly-decreasing priorities so the order is unambiguous.
        for position, job in enumerate(order):
            self.db.set_priority(job.id, len(order) - position)
        self._kick()

    def _move(self, job_id: int, delta: int) -> None:
        order = self._pending_order()
        index = next((i for i, j in enumerate(order) if j.id == job_id), None)
        if index is None:
            return
        target = index + delta
        if not 0 <= target < len(order):
            return
        order[index], order[target] = order[target], order[index]
        self._reassign(order)

    def move_up(self, job_id: int) -> None:
        self._move(job_id, -1)

    def move_down(self, job_id: int) -> None:
        self._move(job_id, 1)

    def move_to_top(self, job_id: int) -> None:
        order = self._pending_order()
        picked = [j for j in order if j.id == job_id]
        if picked:
            self._reassign(picked + [j for j in order if j.id != job_id])

    def move_to_bottom(self, job_id: int) -> None:
        order = self._pending_order()
        picked = [j for j in order if j.id == job_id]
        if picked:
            self._reassign([j for j in order if j.id != job_id] + picked)

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
        return self.add_smart_entry(
            url,
            media.title,
            option,
            dest_dir=dest_dir,
            subtitles=subtitles,
            trim=trim,
            use_session=use_session,
            session_browser=session_browser,
        )

    def add_smart_entry(
        self,
        url: str,
        title: str,
        option: QualityOption,
        *,
        dest_dir: str | Path | None = None,
        subtitles: Mapping[str, Any] | None = None,
        trim: tuple[float, float] | None = None,
        use_session: bool = False,
        session_browser: str = "chrome",
    ) -> Job:
        """Queue one Smart Engine job from just a URL and title - the playlist
        path (F1.7), where entries were listed flat and formats resolve at
        download time."""
        extension = option.audio_format if option.kind == "audio" else "mp4"
        base = naming.sanitize_filename(title)
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
            title=title,
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
        variant: HlsVariant | None = None,
    ) -> Job:
        """Queue an HLS/DASH stream for FFmpeg reassembly; ``variant`` pins a
        quality picked from the master playlist (F2.1)."""
        stem = Path(naming.filename_from_url(url)).stem or "stream"
        base = naming.sanitize_filename(title) if title else stem
        filename = f"{base}.mp4"
        options: dict[str, Any] = {}
        if variant is not None:
            options = {
                "variant_url": variant.url,
                "audio_url": variant.audio_url,
                "quality_label": variant.label,
            }
        job = self.db.create_job(
            url,
            self._dest_for(filename, dest_dir),
            filename,
            kind=JobKind.HLS,
            title=title,
            options=options,
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
            # A manual resume overrides any pending auto-retry and its counter.
            self._retry_at.pop(job_id, None)
            self.db.set_retry_count(job_id, 0)
            self.db.set_job_status(job_id, JobStatus.QUEUED)
            self._kick()

    def cancel(self, job_id: int) -> None:
        with self._cond:
            active = self._active.get(job_id)
        if active is not None:
            active.cancel()
            return
        self._retry_at.pop(job_id, None)
        self._job_limiters.pop(job_id, None)
        job = self.db.get_job(job_id)
        if job is not None and job.status in (
            JobStatus.QUEUED,
            JobStatus.PAUSED,
            JobStatus.FAILED,
        ):
            job.part_path.unlink(missing_ok=True)
            self.db.clear_segments(job_id)
            self.db.set_job_status(job_id, JobStatus.CANCELLED)

    def remove(self, job_id: int) -> None:
        """Drop a job from the list/history. Running jobs are cancelled first;
        completed files stay on disk."""
        self._retry_at.pop(job_id, None)
        self._job_limiters.pop(job_id, None)
        with self._cond:
            active = self._active.get(job_id)
        if active is not None:
            active.cancel()
            return  # scheduler clears it; the row can be removed afterwards
        job = self.db.get_job(job_id)
        if job is None:
            return
        if job.status is not JobStatus.COMPLETED:
            job.part_path.unlink(missing_ok=True)
        self.db.delete_job(job_id)

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
                    speed_limit_kbps=int(job.options.get("speed_limit_kbps") or 0),
                    retry_count=job.retry_count,
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
        job_kbps = int(job.options.get("speed_limit_kbps") or 0)
        proxy = self.settings.proxy
        if job.kind is JobKind.SMART:
            # yt-dlp takes one number: the tighter of the global and per-job cap.
            rates = [r for r in (self.limiter.rate, job_kbps * 1024) if r]
            return SmartDownload(
                self.db,
                job,
                ffmpeg_path=find_ffmpeg(self.settings),
                ratelimit=min(rates) if rates else None,
                proxy=proxy,
            )
        if job.kind is JobKind.HLS:
            # FFmpeg-driven jobs are not rate-limited (Phase 3 polish).
            return HlsDownload(self.db, job, ffmpeg_path=find_ffmpeg(self.settings), proxy=proxy)
        return SegmentedDownload(
            self.db,
            job,
            connections=self.connections,
            limiter=self.limiter,
            job_limiter=self._job_limiter_for(job),
            proxy=proxy,
        )

    def _kick(self) -> None:
        with self._cond:
            self._cond.notify_all()

    def _loop(self) -> None:
        while True:
            with self._cond:
                if not self._running:
                    return
                self._apply_global_rate()  # honor the nightly full-speed window
                self._promote_due_retries()  # re-queue failed jobs whose backoff elapsed
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

    def _promote_due_retries(self) -> None:
        if not self._retry_at:
            return
        now = time.monotonic()
        for job_id, deadline in list(self._retry_at.items()):
            if now < deadline:
                continue
            del self._retry_at[job_id]
            job = self.db.get_job(job_id)
            if job is not None and job.status is JobStatus.FAILED:
                log.info("auto-retrying job %s (attempt %s)", job_id, job.retry_count)
                self.db.set_job_status(job_id, JobStatus.QUEUED)

    def _schedule_retry(self, job_id: int) -> bool:
        """Queue an automatic retry for a transiently-failed job. Returns True
        if one was scheduled."""
        if not self.settings.auto_retry:
            return False
        job = self.db.get_job(job_id)
        if job is None or not _is_transient_error(job.error):
            return False
        if job.retry_count >= self.settings.auto_retry_max:
            return False
        count = job.retry_count + 1
        self.db.set_retry_count(job_id, count)
        delay = min(_RETRY_BASE_SECONDS * 2 ** (count - 1), _RETRY_CAP_SECONDS)
        self._retry_at[job_id] = time.monotonic() + delay
        log.info("job %s failed; auto-retry %s scheduled in %.0fs", job_id, count, delay)
        return True

    def _run_job(self, job: Job, task: DownloadTask) -> None:
        status = JobStatus.FAILED
        try:
            status = task.run()
            log.info("job %s (%s) finished with status %s", job.id, job.filename, status.value)
        finally:
            with self._cond:
                self._active.pop(job.id, None)
                self._threads.pop(job.id, None)
                if status is JobStatus.COMPLETED:
                    # Settle history back to insertion order and forget retries.
                    self.db.set_priority(job.id, 0)
                    self.db.set_retry_count(job.id, 0)
                    self._retry_at.pop(job.id, None)
                    self._job_limiters.pop(job.id, None)
                elif status is JobStatus.FAILED:
                    self._schedule_retry(job.id)
                self._cond.notify_all()
