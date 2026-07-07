from __future__ import annotations

from app.core.models import JobStatus
from app.db.database import Database


def test_job_roundtrip(db: Database):
    job = db.create_job("http://x.test/a.bin", "/tmp/dl", "a.bin")
    assert job.status is JobStatus.QUEUED
    fetched = db.get_job(job.id)
    assert fetched is not None
    assert (fetched.url, fetched.filename) == ("http://x.test/a.bin", "a.bin")


def test_status_and_error_persist(db: Database):
    job = db.create_job("http://x.test/a.bin", "/tmp/dl", "a.bin")
    db.set_job_status(job.id, JobStatus.FAILED, error="disk full")
    fetched = db.get_job(job.id)
    assert fetched is not None
    assert fetched.status is JobStatus.FAILED
    assert fetched.error == "disk full"
    db.set_job_status(job.id, JobStatus.QUEUED)
    fetched = db.get_job(job.id)
    assert fetched is not None
    assert fetched.error is None


def test_segments_roundtrip_and_progress(db: Database):
    job = db.create_job("http://x.test/a.bin", "/tmp/dl", "a.bin")
    segments = db.replace_segments(job.id, [(0, 99), (100, 199), (200, None)])
    assert [(s.start, s.end) for s in segments] == [(0, 99), (100, 199), (200, None)]
    db.update_segment_progress({segments[0].id: 100, segments[1].id: 40})
    assert db.job_downloaded(job.id) == 140
    reloaded = db.segments_for(job.id)
    assert reloaded[0].is_complete
    assert not reloaded[1].is_complete
    assert not reloaded[2].is_complete  # unknown end is never complete


def test_mark_interrupted_flips_downloading_to_paused(db: Database):
    job = db.create_job("http://x.test/a.bin", "/tmp/dl", "a.bin")
    db.set_job_status(job.id, JobStatus.DOWNLOADING)
    assert db.mark_interrupted() == 1
    fetched = db.get_job(job.id)
    assert fetched is not None
    assert fetched.status is JobStatus.PAUSED


def test_find_resumable_job(db: Database):
    job = db.create_job("http://x.test/a.bin", "/tmp/dl", "a.bin")
    assert db.find_resumable_job("http://x.test/a.bin", "/tmp/dl") is not None
    db.set_job_status(job.id, JobStatus.COMPLETED)
    assert db.find_resumable_job("http://x.test/a.bin", "/tmp/dl") is None
