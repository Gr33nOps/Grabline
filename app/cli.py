"""Headless single-download CLI.

This exists for two reasons: it is the vehicle for the Phase 0 milestone test
(kill -9 mid-download, relaunch, resume, checksum must match), and it is a
handy scripting entry point. It shares the exact same engine and database as
the desktop app.

Usage:
    python -m app.cli <url> <dest_dir> [--db PATH] [--connections N]

Exit code 0 means the file completed and was verified/renamed into place.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.core import naming
from app.core.downloader import DEFAULT_CONNECTIONS, SegmentedDownload
from app.core.models import JobStatus
from app.db.database import Database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="grabline-cli", description=__doc__)
    parser.add_argument("url", help="URL to download")
    parser.add_argument("dest", help="destination directory")
    parser.add_argument("--db", type=Path, default=None, help="database path")
    parser.add_argument("--connections", type=int, default=DEFAULT_CONNECTIONS)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    dest_dir = Path(args.dest).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)
    db = Database(args.db if args.db is not None else dest_dir / "grabline-cli.db")
    try:
        db.mark_interrupted()
        job = db.find_resumable_job(args.url, str(dest_dir))
        if job is not None:
            already = db.job_downloaded(job.id)
            print(f"RESUMING job {job.id} ({already} bytes already downloaded)", flush=True)
        else:
            job = db.create_job(args.url, str(dest_dir), naming.filename_from_url(args.url))
            print(f"NEW job {job.id}", flush=True)

        download = SegmentedDownload(db, job, connections=args.connections)
        status = download.run()
        print(f"STATUS {status.value}", flush=True)
        if status is JobStatus.COMPLETED:
            print(f"SAVED {job.dest_path}", flush=True)
            return 0
        fresh = db.get_job(job.id)
        if fresh is not None and fresh.error:
            print(f"ERROR {fresh.error}", flush=True)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
