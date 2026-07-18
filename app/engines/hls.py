"""HLS/DASH reassembly (F2.1): FFmpeg copies the stream into a clean .mp4.

Robustness beyond the Phase 1 core:
- a chosen master-playlist variant (``options["variant_url"]``) is downloaded
  instead of letting FFmpeg pick, and a separate audio rendition
  (``options["audio_url"]``) is muxed in alongside it;
- ``-progress`` output plus the playlist's summed #EXTINF durations give a
  self-correcting total-size estimate, so the UI can show a real percentage;
- one automatic retry on transient failures (nonzero exit or a stall), since
  a CDN hiccup should not kill a 40-minute reassembly for good.

No resume: an interrupted reassembly restarts from the beginning next run.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import IO

import httpx

from app.core import naming, net, proc
from app.core.models import Job, JobStatus
from app.db.database import Database
from app.engines.manifest import playlist_duration

log = logging.getLogger(__name__)

_ESTIMATE_MIN_SECONDS = 5.0  # muxed seconds before the size estimate is trusted


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
        max_attempts: int = 2,
        proxy: str | None = None,
    ) -> None:
        self.db = db
        self.job = job
        self.ffmpeg_path = ffmpeg_path
        self.persist_interval = persist_interval
        self.stall_timeout = stall_timeout
        self.max_attempts = max_attempts
        self.proxy = proxy
        self._stop_event = threading.Event()
        self._cancelled = False
        self._downloaded = 0
        self._out_time = 0.0  # seconds muxed so far, from -progress
        self._size_ema: float | None = None  # smoothed total-size estimate
        self._est_ref: tuple[int, float] | None = None  # (bytes, out_time) anchor
        self._duration: float | None = None
        self._failure = "FFmpeg could not process this stream"
        options = job.options or {}
        self._input_url = str(options.get("variant_url") or job.url)
        audio = options.get("audio_url")
        self._audio_url = str(audio) if audio else None

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
                "FFmpeg is required to save this stream - install it from Settings"
            )
        playlist_text = self._fetch_playlist()
        live_error = self._detect_live_playlist(playlist_text)
        if live_error:
            return self._finish_failed(live_error)
        if playlist_text is not None:
            self._duration = playlist_duration(playlist_text)
        part = self.job.part_path
        part.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, self.max_attempts + 1):
            status = self._attempt(part)
            if status is not None:
                return status
            if attempt < self.max_attempts:
                delay = min(2.0 * 2 ** (attempt - 1), 15.0)
                log.info(
                    "hls job %s attempt %d failed (%s) - retrying in %.0fs",
                    self.job.id,
                    attempt,
                    self._failure,
                    delay,
                )
                # Interruptible: a pause/cancel during the wait aborts the retry.
                if self._stop_event.wait(delay):
                    return self._settle_stopped(part)
        return self._finish_failed(self._failure)

    # ------------------------------------------------------------ one attempt

    def _command(self, part: Path) -> list[str]:
        assert self.ffmpeg_path is not None
        command = [
            self.ffmpeg_path,
            "-y",
            "-nostdin",
            "-loglevel",
            "error",
            "-nostats",
            "-progress",
            "pipe:1",
            "-i",
            self._input_url,
        ]
        if self._audio_url:
            command += ["-i", self._audio_url, "-map", "0", "-map", "1"]
        command += ["-c", "copy", "-f", "mp4", str(part)]
        return command

    def _attempt(self, part: Path) -> JobStatus | None:
        """One FFmpeg run. None means: transient failure, caller may retry."""
        self._downloaded = 0
        self._out_time = 0.0
        env = None
        if self.proxy:
            # FFmpeg reads http(s)_proxy from the environment for http inputs.
            env = {**os.environ, "http_proxy": self.proxy, "https_proxy": self.proxy}
        try:
            process = subprocess.Popen(  # argument list only - no shell (S1)
                self._command(part),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                **proc.hidden(),
            )
        except OSError as exc:
            self._failure = f"could not start FFmpeg: {exc}"
            return self._finish_failed(self._failure)
        assert process.stdout is not None
        reader = threading.Thread(target=self._read_progress, args=(process.stdout,), daemon=True)
        reader.start()

        last_persist = 0.0
        last_estimate = 0
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
                    last_estimate = self._persist_estimate(last_estimate)
            # A live or broken playlist makes FFmpeg poll forever without
            # producing data; never let a job spin indefinitely.
            if now - last_growth > self.stall_timeout:
                self._terminate(process)
                stalled = True
                break
            time.sleep(0.2)

        reader.join(timeout=5)
        stderr_tail = ""
        if process.stderr is not None:
            lines = process.stderr.read().strip().splitlines()
            process.stderr.close()
            if lines:
                stderr_tail = lines[-1]

        if self._stop_event.is_set():
            return self._settle_stopped(part)
        if stalled:
            # A stall at the very end is usually not a failure: the CDN holds
            # a trailing connection open after the last segment, the file stops
            # growing at 99%, and the guard fires. Everything is muxed - and
            # FFmpeg writes the MP4 trailer on the SIGTERM we just sent - so
            # keep the result instead of throwing away a finished download.
            if self._looks_complete(part):
                log.info("hls job %s: stalled after the last segment - keeping", self.job.id)
                return self._finalize(part)
            _discard(part)
            self._failure = (
                f"the stream stalled (no data for {self.stall_timeout:.0f}s) - "
                "it may be live or the server may be down"
            )
            return None
        if process.returncode != 0:
            # FFmpeg often exits nonzero on a fully downloaded stream because a
            # trailing segment 404s or the connection drops after the last byte.
            # If we actually muxed the whole thing, keep it instead of failing.
            if self._looks_complete(part):
                log.info("hls job %s: nonzero exit but stream is complete, keeping", self.job.id)
                return self._finalize(part)
            _discard(part)
            detail = f" ({stderr_tail})" if stderr_tail else ""
            self._failure = f"FFmpeg could not process this stream{detail}"
            return None
        return self._finalize(part)

    def _looks_complete(self, part: Path) -> bool:
        """A stream is 'done' when we muxed ~all of the playlist's duration."""
        if not part.exists() or part.stat().st_size <= 0:
            return False
        if not self._duration:
            return False
        return self._out_time >= self._duration * 0.98

    def _read_progress(self, stream: IO[str]) -> None:
        # FFmpeg's out_time_ms is microseconds too (bug-compatible forever).
        for raw in stream:
            line = raw.strip()
            if line.startswith(("out_time_us=", "out_time_ms=")):
                try:
                    value = int(line.split("=", 1)[1])
                except ValueError:
                    continue
                self._out_time = max(self._out_time, value / 1_000_000)
        stream.close()

    def _persist_estimate(self, last_estimate: int) -> int:
        """Total-size estimate from the stream's steady-state bitrate.

        Scaling bytes-so-far by muxed/total duration reads absurdly high at the
        start: FFmpeg writes the container header and reads several segments
        ahead before out_time has moved, so a few MB over a fraction of a second
        extrapolates to hundreds of GB (the '500 GB that became 2 GB' report).
        Instead we anchor a reference point once past that startup, measure the
        bitrate only over what's muxed *after* it, and extrapolate the bytes
        still to come. That is accurate from the first estimate; an EMA irons
        out VBR wobble, it never drops below what's on disk, and it is persisted
        in step with the downloaded bytes so both progress bars agree. The real
        size replaces it at finalize.
        """
        if not self._duration or self._downloaded <= 0 or self._out_time >= self._duration:
            return last_estimate
        # Anchor once the container startup is behind us; measure from there.
        if self._est_ref is None:
            if self._out_time >= _ESTIMATE_MIN_SECONDS:
                self._est_ref = (self._downloaded, self._out_time)
            return last_estimate
        ref_bytes, ref_time = self._est_ref
        span = self._out_time - ref_time
        if span < _ESTIMATE_MIN_SECONDS:  # need a window to read a steady rate
            return last_estimate
        rate = (self._downloaded - ref_bytes) / span  # bytes per muxed second
        estimate = self._downloaded + (self._duration - self._out_time) * rate
        if self._size_ema is None:
            self._size_ema = estimate
        else:
            self._size_ema += (estimate - self._size_ema) * 0.2
        published = max(int(self._size_ema), self._downloaded)
        if published != last_estimate:
            self.db.update_job_total(self.job.id, published)
        return published

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    # -------------------------------------------------------------- playlist

    def _fetch_playlist(self) -> str | None:
        """The input manifest's text, or None when it cannot be fetched.

        Any fetch error is ignored so FFmpeg can report the real problem.
        """
        try:
            with net.build_client(proxy=self.proxy, follow_redirects=True, timeout=10) as client:
                response = client.get(self._input_url)
                if response.status_code != 200:
                    return None
                return response.text
        except httpx.HTTPError:
            return None

    def _detect_live_playlist(self, text: str | None) -> str | None:
        """Refuse live-in-progress HLS clearly instead of recording forever.

        Only a direct media playlist can be judged here; master playlists pass
        through (the stall guard still bounds the worst case).
        """
        if text is None:
            return None
        if "#EXTM3U" not in text or "#EXT-X-STREAM-INF" in text:
            return None
        if "#EXTINF" in text and "#EXT-X-ENDLIST" not in text:
            return (
                "This looks like a live stream that is still in progress - "
                "Grabline cannot save it yet. Try again once it has ended."
            )
        return None

    # ------------------------------------------------------------- outcomes

    def _finalize(self, part: Path) -> JobStatus:
        # Never a raw read-only fsync here: on Windows that raises, and the
        # raise used to skip everything below - the downloaded stream sat at
        # "Downloading" forever with its .gl-part never renamed.
        naming.fsync_before_rename(part)
        size = part.stat().st_size
        if size == 0:
            _discard(part)
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
        _discard(part)
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


def _discard(part: Path) -> None:
    """Delete a leftover .gl-part, retrying briefly: on Windows FFmpeg may
    still hold the handle for a moment after it exits (WinError 32)."""
    for attempt in range(5):
        try:
            part.unlink(missing_ok=True)
            return
        except OSError:
            time.sleep(0.2 * (attempt + 1))
    log.warning("could not remove leftover part file: %s", part)
