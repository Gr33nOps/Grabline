"""Data model for jobs and segments, mirrored 1:1 by the SQLite schema."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

PART_SUFFIX = ".gl-part"


class JobStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


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

    @property
    def dest_path(self) -> Path:
        return Path(self.dest_dir) / self.filename

    @property
    def part_path(self) -> Path:
        return Path(self.dest_dir) / (self.filename + PART_SUFFIX)
