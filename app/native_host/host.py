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

PROTOCOL_VERSION = 2

_MAX_URL_LENGTH = 8192
_MAX_TEXT_LENGTH = 512
_MAX_GALLERY_ITEMS = 300


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
        handoff_id = db.add_handoff(
            url,
            page_url=_valid_url(message.get("pageUrl")),
            page_title=_clean_text(message.get("pageTitle")),
            source=_clean_text(message.get("source")) or "extension",
        )
        return {
            "type": "queued",
            "handoffId": handoff_id,
            "appRunning": instance.app_is_running(),
        }
    if kind == "gallery":
        # F2.2: every image URL the content script collected on one page.
        raw = message.get("urls")
        urls: list[str] = []
        if isinstance(raw, list):
            for item in raw[:_MAX_GALLERY_ITEMS]:
                valid = _valid_url(item)
                if valid is not None:
                    urls.append(valid)
        if not urls:
            return {"type": "error", "message": "no downloadable image URLs in gallery"}
        page_url = _valid_url(message.get("pageUrl"))
        handoff_id = db.add_handoff(
            page_url or urls[0],
            page_url=page_url,
            page_title=_clean_text(message.get("pageTitle")),
            source="gallery",
            payload=urls,
        )
        return {
            "type": "queued",
            "handoffId": handoff_id,
            "count": len(urls),
            "appRunning": instance.app_is_running(),
        }
    return {"type": "error", "message": f"unknown message type: {kind!r}"}


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
