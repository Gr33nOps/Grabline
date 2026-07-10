"""SQLite persistence for jobs and segment checkpoints.

WAL journaling keeps the database consistent across a kill -9 or power-style
interruption of the process, which is what makes resume-after-crash (F0.2)
trustworthy. A single connection is shared behind a lock so worker threads,
the checkpointer, and the UI thread can all talk to one Database instance.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.core.models import RESUMABLE_STATUSES, Handoff, Job, JobKind, JobStatus, Segment

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL,
    final_url     TEXT,
    dest_dir      TEXT NOT NULL,
    filename      TEXT NOT NULL,
    total_size    INTEGER,
    resumable     INTEGER NOT NULL DEFAULT 0,
    etag          TEXT,
    last_modified TEXT,
    status        TEXT NOT NULL DEFAULT 'queued',
    error         TEXT,
    kind          TEXT NOT NULL DEFAULT 'direct',
    title         TEXT,
    options       TEXT NOT NULL DEFAULT '{}',
    downloaded    INTEGER NOT NULL DEFAULT 0,
    priority      INTEGER NOT NULL DEFAULT 0,
    retry_count   INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS segments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    seg_index  INTEGER NOT NULL,
    start_byte INTEGER NOT NULL,
    end_byte   INTEGER,
    downloaded INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_segments_job_id ON segments(job_id);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- URLs handed over by Grabline Connect (via the Native Messaging host).
-- The host inserts; the running app claims and runs them through the
-- resolver. This table IS the extension->app channel: no sockets exist.
CREATE TABLE IF NOT EXISTS handoffs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    url        TEXT NOT NULL,
    page_url   TEXT,
    page_title TEXT,
    source     TEXT NOT NULL DEFAULT 'extension',
    payload    TEXT NOT NULL DEFAULT '[]',
    quality    TEXT,
    headers    TEXT NOT NULL DEFAULT '{}',
    claimed    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

#: Columns added after Phase 0, applied to pre-existing databases on open.
_JOBS_MIGRATIONS = {
    "kind": "ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'direct'",
    "title": "ALTER TABLE jobs ADD COLUMN title TEXT",
    "options": "ALTER TABLE jobs ADD COLUMN options TEXT NOT NULL DEFAULT '{}'",
    "downloaded": "ALTER TABLE jobs ADD COLUMN downloaded INTEGER NOT NULL DEFAULT 0",
    "priority": "ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0",
    "retry_count": "ALTER TABLE jobs ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
}

_HANDOFFS_MIGRATIONS = {
    "payload": "ALTER TABLE handoffs ADD COLUMN payload TEXT NOT NULL DEFAULT '[]'",
    "quality": "ALTER TABLE handoffs ADD COLUMN quality TEXT",
    "headers": "ALTER TABLE handoffs ADD COLUMN headers TEXT NOT NULL DEFAULT '{}'",
}


def _job_from_row(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        url=row["url"],
        final_url=row["final_url"],
        dest_dir=row["dest_dir"],
        filename=row["filename"],
        total_size=row["total_size"],
        resumable=bool(row["resumable"]),
        etag=row["etag"],
        last_modified=row["last_modified"],
        status=JobStatus(row["status"]),
        error=row["error"],
        kind=JobKind(row["kind"]),
        title=row["title"],
        options=json.loads(row["options"] or "{}"),
        downloaded=row["downloaded"],
        priority=row["priority"],
        retry_count=row["retry_count"],
    )


def _segment_from_row(row: sqlite3.Row) -> Segment:
    return Segment(
        id=row["id"],
        job_id=row["job_id"],
        index=row["seg_index"],
        start=row["start_byte"],
        end=row["end_byte"],
        downloaded=row["downloaded"],
    )


class Database:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(_SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        """Add columns introduced after Phase 0 to databases created before them."""
        for table, migrations in (("jobs", _JOBS_MIGRATIONS), ("handoffs", _HANDOFFS_MIGRATIONS)):
            existing = {
                row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            with self._conn:
                for column, statement in migrations.items():
                    if column not in existing:
                        self._conn.execute(statement)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------- jobs

    def create_job(
        self,
        url: str,
        dest_dir: str,
        filename: str,
        *,
        kind: JobKind = JobKind.DIRECT,
        title: str | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Job:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO jobs (url, dest_dir, filename, kind, title, options) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (url, dest_dir, filename, kind.value, title, json.dumps(dict(options or {}))),
            )
            job_id = cur.lastrowid
        if job_id is None:  # pragma: no cover - sqlite always sets it
            raise RuntimeError("INSERT did not produce a row id")
        job = self.get_job(job_id)
        if job is None:  # pragma: no cover
            raise RuntimeError("job vanished right after INSERT")
        return job

    def get_job(self, job_id: int) -> Job | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _job_from_row(row) if row else None

    def list_jobs(self) -> list[Job]:
        # Higher priority first; ties (the default 0) fall back to insertion
        # order, so an untouched queue still runs oldest-first.
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY priority DESC, id ASC"
            ).fetchall()
        return [_job_from_row(row) for row in rows]

    def set_priority(self, job_id: int, priority: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE jobs SET priority = ? WHERE id = ?", (priority, job_id))

    def set_retry_count(self, job_id: int, count: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE jobs SET retry_count = ? WHERE id = ?", (count, job_id))

    def latest_job_for_url(self, url: str) -> Job | None:
        """The most recent job for a URL - how the extension's progress pill
        (F1.3) finds "its" download without any job-id round trip."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE url = ? ORDER BY id DESC LIMIT 1", (url,)
            ).fetchone()
        return _job_from_row(row) if row else None

    def find_resumable_job(self, url: str, dest_dir: str) -> Job | None:
        placeholders = ", ".join("?" for _ in RESUMABLE_STATUSES)
        params = (url, dest_dir, *[status.value for status in RESUMABLE_STATUSES])
        with self._lock:
            row = self._conn.execute(
                f"SELECT * FROM jobs WHERE url = ? AND dest_dir = ? "
                f"AND status IN ({placeholders}) ORDER BY id DESC LIMIT 1",
                params,
            ).fetchone()
        return _job_from_row(row) if row else None

    def set_job_status(self, job_id: int, status: JobStatus, error: str | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE jobs SET status = ?, error = ?, updated_at = datetime('now') WHERE id = ?",
                (status.value, error, job_id),
            )

    def update_job_probe(self, job: Job) -> None:
        """Persist what the probe learned (size, validators, better filename)."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE jobs SET final_url = ?, filename = ?, total_size = ?, resumable = ?, "
                "etag = ?, last_modified = ?, updated_at = datetime('now') WHERE id = ?",
                (
                    job.final_url,
                    job.filename,
                    job.total_size,
                    int(job.resumable),
                    job.etag,
                    job.last_modified,
                    job.id,
                ),
            )

    def update_job_total(self, job_id: int, total_size: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE jobs SET total_size = ?, updated_at = datetime('now') WHERE id = ?",
                (total_size, job_id),
            )

    def update_job_options(self, job_id: int, options: Mapping[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE jobs SET options = ?, updated_at = datetime('now') WHERE id = ?",
                (json.dumps(dict(options)), job_id),
            )

    def update_job_filename(self, job_id: int, filename: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE jobs SET filename = ?, updated_at = datetime('now') WHERE id = ?",
                (filename, job_id),
            )

    def delete_job(self, job_id: int) -> None:
        """Remove a job from the list/history; its segments cascade away.
        Never touches files on disk."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def update_job_downloaded(self, job_id: int, downloaded: int) -> None:
        """Progress mirror for smart/hls jobs (direct jobs checkpoint segments)."""
        with self._lock, self._conn:
            self._conn.execute("UPDATE jobs SET downloaded = ? WHERE id = ?", (downloaded, job_id))

    def stored_progress(self, job: Job) -> int:
        """Bytes on record for a job that is not currently running."""
        if job.kind is JobKind.DIRECT:
            return self.job_downloaded(job.id)
        return job.downloaded

    def mark_interrupted(self) -> int:
        """Flip jobs a dead process left 'downloading' to 'paused'. Run at startup."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE jobs SET status = ?, updated_at = datetime('now') WHERE status = ?",
                (JobStatus.PAUSED.value, JobStatus.DOWNLOADING.value),
            )
        return cur.rowcount

    # --------------------------------------------------------- handoffs

    def add_handoff(
        self,
        url: str,
        *,
        page_url: str | None = None,
        page_title: str | None = None,
        source: str = "extension",
        payload: Sequence[str] = (),
        quality: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO handoffs "
                "(url, page_url, page_title, source, payload, quality, headers) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    url,
                    page_url,
                    page_title,
                    source,
                    json.dumps(list(payload)),
                    quality,
                    json.dumps(dict(headers or {})),
                ),
            )
        handoff_id = cur.lastrowid
        if handoff_id is None:  # pragma: no cover - sqlite always sets it
            raise RuntimeError("INSERT did not produce a row id")
        return handoff_id

    def claim_handoffs(self) -> list[Handoff]:
        """Atomically take every unclaimed handoff (exactly-once processing)."""
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT * FROM handoffs WHERE claimed = 0 ORDER BY id"
            ).fetchall()
            if rows:
                self._conn.executemany(
                    "UPDATE handoffs SET claimed = 1 WHERE id = ?",
                    [(row["id"],) for row in rows],
                )
        return [
            Handoff(
                id=row["id"],
                url=row["url"],
                page_url=row["page_url"],
                page_title=row["page_title"],
                source=row["source"],
                payload=tuple(json.loads(row["payload"] or "[]")),
                quality=row["quality"],
                headers=json.loads(row["headers"] or "{}"),
            )
            for row in rows
        ]

    # --------------------------------------------------------- settings

    def get_setting(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # --------------------------------------------------------- segments

    def replace_segments(
        self, job_id: int, spans: Sequence[tuple[int, int | None]]
    ) -> list[Segment]:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM segments WHERE job_id = ?", (job_id,))
            self._conn.executemany(
                "INSERT INTO segments (job_id, seg_index, start_byte, end_byte) "
                "VALUES (?, ?, ?, ?)",
                [(job_id, i, start, end) for i, (start, end) in enumerate(spans)],
            )
        return self.segments_for(job_id)

    def add_segment(self, job_id: int, seg_index: int, start: int, end: int | None) -> Segment:
        """Insert one segment (used when a worker steals work at runtime)."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO segments (job_id, seg_index, start_byte, end_byte) "
                "VALUES (?, ?, ?, ?)",
                (job_id, seg_index, start, end),
            )
            seg_id = cur.lastrowid
        if seg_id is None:  # pragma: no cover - sqlite always sets it
            raise RuntimeError("INSERT did not produce a row id")
        return Segment(
            id=seg_id, job_id=job_id, index=seg_index, start=start, end=end, downloaded=0
        )

    def segments_for(self, job_id: int) -> list[Segment]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM segments WHERE job_id = ? ORDER BY seg_index", (job_id,)
            ).fetchall()
        return [_segment_from_row(row) for row in rows]

    def update_segment_progress(self, progress: Mapping[int, int]) -> None:
        if not progress:
            return
        with self._lock, self._conn:
            self._conn.executemany(
                "UPDATE segments SET downloaded = ? WHERE id = ?",
                [(downloaded, segment_id) for segment_id, downloaded in progress.items()],
            )

    def set_segment_end(self, segment_id: int, end: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE segments SET end_byte = ? WHERE id = ?", (end, segment_id))

    def clear_segments(self, job_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM segments WHERE job_id = ?", (job_id,))

    def job_downloaded(self, job_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(downloaded), 0) AS total FROM segments WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return int(row["total"])

    def all_segment_progress(self) -> dict[int, int]:
        """Summed downloaded bytes per job, in one query - the UI snapshot
        polls this every refresh, so it must not be N separate SUM queries."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT job_id, COALESCE(SUM(downloaded), 0) AS total FROM segments GROUP BY job_id"
            ).fetchall()
        return {int(row["job_id"]): int(row["total"]) for row in rows}
