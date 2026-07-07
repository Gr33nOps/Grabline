"""Basic HLS/DASH reassembly (Phase 1): FFmpeg copies the stream into a clean
.mp4. Robustness for the manifest zoo (byte-range playlists, separate audio
renditions, live detection) is Phase 3 work (F2.1) — this is the honest core.

No resume: an interrupted reassembly restarts from the beginning next run.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path

import httpx

from app.core import naming
from app.core.models import Job, JobStatus
from app.db.database import Database

log = logging.getLogger(__name__)


class HlsDownload:
    """Runs one HLS job via FFmpeg. One-shot object."""

    def __init__(
        self,
        db: Database,
        job: Job,
        *,
        ffmpeg_path: str | None,
        persist_interval: float = 0.5,
        stall_timeout: float = 90.0,
    ) -> None:
        self.db = db
        self.job = job
        self.ffmpeg_path = ffmpeg_path
        self.persist_interval = persist_interval
        self.stall_timeout = stall_timeout
        self._stop_event = threading.Event()
        self._cancelled = False
        self._downloaded = 0

    def pause(self) -> None:
        self._stop_event.set()

    def cancel(self) -> None:
        self._cancelled = True
        self._stop_event.set()

    @property
    def bytes_downloaded(self) -> int:
        return self._downloaded

    def run(self) -> JobStatus:
        self.db.set_job_status(self.job.id, JobStatus.DOWNLOADING)
        if not self.ffmpeg_path:
            return self._finish_failed(
                "FFmpeg is required to save this stream — install it from Settings"
            )
        live_error = self._detect_live_playlist()
        if live_error:
            return self._finish_failed(live_error)
        part = self.job.part_path
        part.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.ffmpeg_path,
            "-y",
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            self.job.url,
            "-c",
            "copy",
            "-f",
            "mp4",
            str(part),
        ]
        try:
            process = subprocess.Popen(  # argument list only — no shell (S1)
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            return self._finish_failed(f"could not start FFmpeg: {exc}")

        last_persist = 0.0
        last_growth = time.monotonic()
        stalled = False
        while process.poll() is None:
            if self._stop_event.is_set():
                self._terminate(process)
                break
            now = time.monotonic()
            if part.exists():
                size = part.stat().st_size
                if size != self._downloaded:
                    self._downloaded = size
                    last_growth = now
                if now - last_persist >= self.persist_interval:
                    last_persist = now
                    self.db.update_job_downloaded(self.job.id, self._downloaded)
            # A live or broken playlist makes FFmpeg poll forever without
            # producing data; never let a job spin indefinitely.
            if now - last_growth > self.stall_timeout:
                self._terminate(process)
                stalled = True
                break
            time.sleep(0.2)

        stderr_tail = ""
        if process.stderr is not None:
            lines = process.stderr.read().strip().splitlines()
            process.stderr.close()
            if lines:
                stderr_tail = lines[-1]

        if self._stop_event.is_set():
            return self._settle_stopped(part)
        if stalled:
            part.unlink(missing_ok=True)
            return self._finish_failed(
                f"the stream stalled (no data for {self.stall_timeout:.0f}s) — "
                "it may be live or the server may be down"
            )
        if process.returncode != 0:
            part.unlink(missing_ok=True)
            detail = f" ({stderr_tail})" if stderr_tail else ""
            return self._finish_failed(f"FFmpeg could not process this stream{detail}")
        return self._finalize(part)

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def _detect_live_playlist(self) -> str | None:
        """Refuse live-in-progress HLS clearly instead of recording forever.

        Only a direct media playlist can be judged here; master playlists pass
        through (the stall guard still bounds the worst case). Any fetch error
        is ignored so FFmpeg can report the real problem.
        """
        try:
            with httpx.Client(follow_redirects=True, timeout=10) as client:
                response = client.get(self.job.url)
                if response.status_code != 200:
                    return None
                text = response.text
        except httpx.HTTPError:
            return None
        if "#EXTM3U" not in text or "#EXT-X-STREAM-INF" in text:
            return None
        if "#EXTINF" in text and "#EXT-X-ENDLIST" not in text:
            return (
                "This looks like a live stream that is still in progress — "
                "Grabline cannot save it yet. Try again once it has ended."
            )
        return None

    def _finalize(self, part: Path) -> JobStatus:
        with open(part, "rb") as handle:
            os.fsync(handle.fileno())
        size = part.stat().st_size
        if size == 0:
            part.unlink(missing_ok=True)
            return self._finish_failed("the stream produced an empty file")
        dest = naming.unique_path(self.job.dest_path)
        os.replace(part, dest)
        if dest.name != self.job.filename:
            self.job.filename = dest.name
            self.db.update_job_filename(self.job.id, dest.name)
        self.job.total_size = size
        self.db.update_job_total(self.job.id, size)
        self.db.update_job_downloaded(self.job.id, size)
        self.db.set_job_status(self.job.id, JobStatus.COMPLETED)
        return JobStatus.COMPLETED

    def _settle_stopped(self, part: Path) -> JobStatus:
        # MP4 muxing cannot resume: a paused reassembly restarts from scratch,
        # so the partial output is useless either way.
        part.unlink(missing_ok=True)
        self.db.update_job_downloaded(self.job.id, 0)
        if self._cancelled:
            self.db.set_job_status(self.job.id, JobStatus.CANCELLED)
            return JobStatus.CANCELLED
        self.db.set_job_status(self.job.id, JobStatus.PAUSED)
        return JobStatus.PAUSED

    def _finish_failed(self, message: str) -> JobStatus:
        log.warning("hls job %s failed: %s", self.job.id, message)
        self.db.set_job_status(self.job.id, JobStatus.FAILED, error=message)
        return JobStatus.FAILED
