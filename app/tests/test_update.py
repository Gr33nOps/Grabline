from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.core import update
from app.tests.media_server import MediaServer, payload

MB = 1024 * 1024


def test_download_installer_cancel_stops_and_removes_partial(server: MediaServer, tmp_path: Path):
    """Pressing Cancel must actually abort the transfer and leave no half-written
    installer behind - the bug was a Cancel button wired to nothing, so the
    download ran on and opened the installer anyway."""
    url = server.add("/GrabLine-Setup.exe", payload(4 * MB, 5))
    cancel = threading.Event()
    cancel.set()  # already set: the loop aborts on its first chunk check

    with pytest.raises(update.UpdateCancelled):
        update.download_installer(url, str(tmp_path), "GrabLine-Setup.exe", cancel=cancel)

    assert not (tmp_path / "GrabLine-Setup.exe").exists()


def test_download_installer_completes_without_cancel(server: MediaServer, tmp_path: Path):
    """With no cancel it downloads to completion and returns the file path."""
    data = payload(256 * 1024, 9)
    url = server.add("/GrabLine-Setup.exe", data)

    path = update.download_installer(url, str(tmp_path), "GrabLine-Setup.exe")

    assert Path(path).read_bytes() == data
