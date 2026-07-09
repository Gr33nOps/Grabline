"""Message handling for the Native Messaging host.

Kept free of I/O so every branch is unit-testable: ``handle_message`` maps one
request dict to one reply dict; ``serve`` runs the stdio loop around it.
"""

from __future__ import annotations

import logging
from typing import Any, BinaryIO
from urllib.parse import urlsplit

from app.core import instance
from app.db.database import Database
from app.native_host.protocol import ProtocolError, read_message, write_message

log = logging.getLogger(__name__)

PROTOCOL_VERSION = 3

_MAX_URL_LENGTH = 8192
_MAX_TEXT_LENGTH = 512
_MAX_GALLERY_ITEMS = 300
_MAX_STATUS_ITEMS = 50
_MAX_FALLBACK_ITEMS = 5

#: Labels the in-page quality panel (F1.3) may pin; anything else is dropped
#: and the app shows its own panel instead.
_QUALITY_LABELS = frozenset(
    {"best", "2160p", "1440p", "1080p", "720p", "480p", "360p", "mp3", "m4a"}
)


def _clean_text(value: object, limit: int = _MAX_TEXT_LENGTH) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] if value else None


def _valid_url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > _MAX_URL_LENGTH:
        return None
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return value


def handle_message(db: Database, message: dict[str, Any]) -> dict[str, Any]:
    kind = message.get("type")
    if kind == "ping":
        return {
            "type": "pong",
            "protocolVersion": PROTOCOL_VERSION,
            "appRunning": instance.app_is_running(),
        }
    if kind == "download":
        url = _valid_url(message.get("url"))
        if url is None:
            return {"type": "error", "message": "only http(s) URLs can be downloaded"}
        quality = _clean_text(message.get("quality"), limit=8)
        if quality is not None and quality.lower() not in _QUALITY_LABELS:
            quality = None
        # Sniffed streams from the tab: tried in order if the URL itself
        # resolves to nothing (blob players on no-name streaming sites).
        raw_fallbacks = message.get("fallbackUrls")
        fallbacks: list[str] = []
        if isinstance(raw_fallbacks, list):
            for item in raw_fallbacks[:_MAX_FALLBACK_ITEMS]:
                valid = _valid_url(item)
                if valid is not None and valid != url:
                    fallbacks.append(valid)
        handoff_id = db.add_handoff(
            url,
            page_url=_valid_url(message.get("pageUrl")),
            page_title=_clean_text(message.get("pageTitle")),
            source=_clean_text(message.get("source")) or "extension",
            quality=quality,
            payload=fallbacks,
        )
        return {
            "type": "queued",
            "handoffId": handoff_id,
            "appRunning": instance.app_is_running(),
        }
    if kind == "status":
        # F1.3 progress pill: latest job per URL, straight from the jobs table.
        raw = message.get("urls")
        jobs: list[dict[str, Any]] = []
        if isinstance(raw, list):
            for item in raw[:_MAX_STATUS_ITEMS]:
                url = _valid_url(item)
                if url is None:
                    continue
                job = db.latest_job_for_url(url)
                if job is None:
                    jobs.append({"url": url, "status": "pending"})
                    continue
                jobs.append(
                    {
                        "url": url,
                        "status": job.status.value,
                        "downloaded": db.stored_progress(job),
                        "total": job.total_size,
                        "name": job.title or job.filename,
                    }
                )
        return {"type": "status", "jobs": jobs, "appRunning": instance.app_is_running()}
    if kind == "gallery":
        # F2.2: every image URL the content script collected on one page.
        return _collection_handoff(db, message, "gallery", "no downloadable image URLs found")
    if kind == "links":
        # Every downloadable link the content script found on one page.
        return _collection_handoff(db, message, "links", "no downloadable links found")
    return {"type": "error", "message": f"unknown message type: {kind!r}"}


def _collection_handoff(
    db: Database, message: dict[str, Any], source: str, empty_message: str
) -> dict[str, Any]:
    raw = message.get("urls")
    urls: list[str] = []
    if isinstance(raw, list):
        for item in raw[:_MAX_GALLERY_ITEMS]:
            valid = _valid_url(item)
            if valid is not None and valid not in urls:
                urls.append(valid)
    if not urls:
        return {"type": "error", "message": empty_message}
    page_url = _valid_url(message.get("pageUrl"))
    handoff_id = db.add_handoff(
        page_url or urls[0],
        page_url=page_url,
        page_title=_clean_text(message.get("pageTitle")),
        source=source,
        payload=urls,
    )
    return {
        "type": "queued",
        "handoffId": handoff_id,
        "count": len(urls),
        "appRunning": instance.app_is_running(),
    }


def serve(stdin: BinaryIO, stdout: BinaryIO, db: Database) -> None:
    """Process messages until the browser closes the pipe."""
    while True:
        try:
            message = read_message(stdin)
        except ProtocolError as exc:
            log.warning("protocol error: %s", exc)
            write_message(stdout, {"type": "error", "message": str(exc)})
            return
        if message is None:
            return
        try:
            reply = handle_message(db, message)
        except Exception:  # never crash the channel; reply and carry on
            log.exception("failed to handle message")
            reply = {"type": "error", "message": "internal host error"}
        write_message(stdout, reply)
