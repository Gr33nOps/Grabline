"""Data model for jobs and segments, mirrored 1:1 by the SQLite schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

PART_SUFFIX = ".gl-part"


class JobStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobKind(StrEnum):
    """Which engine runs the job (decided once, by the resolver)."""

    DIRECT = "direct"  # segmented downloader (app.core.downloader)
    SMART = "smart"  # yt-dlp in-process (app.engines.smart)
    HLS = "hls"  # FFmpeg stream reassembly (app.engines.hls)


#: Statuses a job can be picked up from again (used by "find unfinished").
RESUMABLE_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.QUEUED, JobStatus.DOWNLOADING, JobStatus.PAUSED, JobStatus.FAILED}
)


@dataclass
class Segment:
    """One byte range of a job. ``end`` is None while the size is unknown."""

    id: int
    job_id: int
    index: int
    start: int
    end: int | None
    downloaded: int

    @property
    def is_complete(self) -> bool:
        return self.end is not None and self.downloaded >= self.end - self.start + 1


@dataclass(frozen=True)
class Handoff:
    """A URL delivered by Grabline Connect, waiting for the app to pick it up."""

    id: int
    url: str
    page_url: str | None
    page_title: str | None
    source: str
    #: Gallery handoffs (F2.2) carry the page's image URLs here.
    payload: tuple[str, ...] = ()
    #: A quality label chosen in the in-page panel (F1.3), e.g. "1080p".
    quality: str | None = None
    #: Extra HTTP headers (Cookie / Referer / User-Agent) so a login-gated
    #: download the browser could reach can be fetched by the app too.
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Job:
    id: int
    url: str
    final_url: str | None
    dest_dir: str
    filename: str
    total_size: int | None
    resumable: bool
    etag: str | None
    last_modified: str | None
    status: JobStatus
    error: str | None
    kind: JobKind = JobKind.DIRECT
    title: str | None = None
    #: Engine options (smart jobs: format spec, audio mode, subtitles, trim, session).
    options: dict[str, Any] = field(default_factory=dict)
    #: Progress mirror for non-segmented jobs (smart/hls); direct jobs use segments.
    downloaded: int = 0
    #: Queue priority; higher runs first, ties break by id (older first).
    priority: int = 0
    #: How many times auto-retry has re-queued this job after a failure.
    retry_count: int = 0

    @property
    def dest_path(self) -> Path:
        return Path(self.dest_dir) / self.filename

    @property
    def part_path(self) -> Path:
        return Path(self.dest_dir) / (self.filename + PART_SUFFIX)
