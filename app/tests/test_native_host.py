from __future__ import annotations

import io
import struct
from pathlib import Path
from typing import Any

import pytest

from app.core import instance
from app.db.database import Database
from app.native_host.host import handle_message, serve
from app.native_host.protocol import (
    MAX_MESSAGE_BYTES,
    ProtocolError,
    read_message,
    write_message,
)


@pytest.fixture(autouse=True)
def isolated_pid_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(instance, "pid_file", lambda: tmp_path / "grabline.pid")


# ------------------------------------------------------------- protocol


def test_protocol_roundtrip():
    buffer = io.BytesIO()
    write_message(buffer, {"type": "ping", "n": 1})
    buffer.seek(0)
    assert read_message(buffer) == {"type": "ping", "n": 1}
    assert read_message(buffer) is None  # clean EOF


def test_protocol_rejects_truncated_header():
    with pytest.raises(ProtocolError, match="truncated"):
        read_message(io.BytesIO(b"\x01\x00"))


def test_protocol_rejects_truncated_body():
    buffer = io.BytesIO(struct.pack("<I", 100) + b"{}")
    with pytest.raises(ProtocolError, match="truncated"):
        read_message(buffer)


def test_protocol_rejects_oversized_messages():
    buffer = io.BytesIO(struct.pack("<I", MAX_MESSAGE_BYTES + 1))
    with pytest.raises(ProtocolError, match="too large"):
        read_message(buffer)
    with pytest.raises(ProtocolError, match="oversized"):
        write_message(io.BytesIO(), {"blob": "x" * (MAX_MESSAGE_BYTES + 1)})


def test_protocol_rejects_non_object_and_bad_json():
    for payload in (b"[1, 2]", b"not json"):
        buffer = io.BytesIO(struct.pack("<I", len(payload)) + payload)
        with pytest.raises(ProtocolError):
            read_message(buffer)


# ----------------------------------------------------------------- host


def test_ping_reports_app_not_running(db: Database):
    reply = handle_message(db, {"type": "ping"})
    assert reply["type"] == "pong"
    assert reply["appRunning"] is False


def test_ping_reports_app_running(db: Database):
    instance.write_pid()  # this test process counts as "running"
    reply = handle_message(db, {"type": "ping"})
    assert reply["appRunning"] is True


def test_download_creates_handoff(db: Database):
    reply = handle_message(
        db,
        {
            "type": "download",
            "url": "https://example.com/video.mp4",
            "pageUrl": "https://example.com/watch",
            "pageTitle": "  A Page  ",
        },
    )
    assert reply["type"] == "queued"
    handoffs = db.claim_handoffs()
    assert len(handoffs) == 1
    handoff = handoffs[0]
    assert handoff.id == reply["handoffId"]
    assert handoff.url == "https://example.com/video.mp4"
    assert handoff.page_url == "https://example.com/watch"
    assert handoff.page_title == "A Page"
    assert handoff.source == "extension"


def test_download_rejects_bad_urls(db: Database):
    for url in ("ftp://host/f", "javascript:alert(1)", "", None, 42, "x" * 9000):
        reply = handle_message(db, {"type": "download", "url": url})
        assert reply["type"] == "error"
    assert db.claim_handoffs() == []


def test_page_title_is_truncated(db: Database):
    handle_message(db, {"type": "download", "url": "https://x.test/f", "pageTitle": "t" * 2000})
    handoff = db.claim_handoffs()[0]
    assert handoff.page_title is not None and len(handoff.page_title) == 512


def test_unknown_type_is_an_error_reply(db: Database):
    reply = handle_message(db, {"type": "reboot"})
    assert reply["type"] == "error"


# -------------------------------------------------------- gallery (F2.2)


def test_gallery_creates_one_handoff_with_payload(db: Database):
    reply = handle_message(
        db,
        {
            "type": "gallery",
            "urls": [
                "https://example.com/a.jpg",
                "javascript:alert(1)",  # dropped
                "https://example.com/b.png",
            ],
            "pageUrl": "https://example.com/gallery",
            "pageTitle": "Holiday",
        },
    )
    assert reply["type"] == "queued"
    assert reply["count"] == 2
    handoffs = db.claim_handoffs()
    assert len(handoffs) == 1
    handoff = handoffs[0]
    assert handoff.source == "gallery"
    assert handoff.url == "https://example.com/gallery"
    assert handoff.payload == ("https://example.com/a.jpg", "https://example.com/b.png")


def test_gallery_with_no_valid_urls_is_an_error(db: Database):
    for urls in ([], ["ftp://x/y"], "not-a-list", None):
        reply = handle_message(db, {"type": "gallery", "urls": urls})
        assert reply["type"] == "error"
    assert db.claim_handoffs() == []


def test_gallery_is_capped(db: Database):
    urls = [f"https://example.com/{i}.jpg" for i in range(500)]
    reply = handle_message(db, {"type": "gallery", "urls": urls})
    assert reply["count"] == 300
    assert len(db.claim_handoffs()[0].payload) == 300


# ---------------------------------------------------------------- serve


def _framed(*messages: dict[str, Any]) -> io.BytesIO:
    buffer = io.BytesIO()
    for message in messages:
        write_message(buffer, message)
    buffer.seek(0)
    return buffer


def _replies(buffer: io.BytesIO) -> list[dict[str, Any]]:
    buffer.seek(0)
    out: list[dict[str, Any]] = []
    while (message := read_message(buffer)) is not None:
        out.append(message)
    return out


def test_serve_end_to_end(db: Database):
    stdin = _framed(
        {"type": "ping"},
        {"type": "download", "url": "https://example.com/a.zip"},
    )
    stdout = io.BytesIO()
    serve(stdin, stdout, db)
    replies = _replies(stdout)
    assert [reply["type"] for reply in replies] == ["pong", "queued"]
    assert len(db.claim_handoffs()) == 1


def test_serve_replies_error_on_protocol_garbage(db: Database):
    stdin = io.BytesIO(struct.pack("<I", 5) + b"nope!")
    stdout = io.BytesIO()
    serve(stdin, stdout, db)
    replies = _replies(stdout)
    assert len(replies) == 1
    assert replies[0]["type"] == "error"


def test_handoff_claims_are_exactly_once(db: Database):
    db.add_handoff("https://x.test/1")
    db.add_handoff("https://x.test/2")
    first = db.claim_handoffs()
    assert [h.url for h in first] == ["https://x.test/1", "https://x.test/2"]
    assert db.claim_handoffs() == []
