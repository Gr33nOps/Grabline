"""Opening a download's folder in the OS file manager (never the browser)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.core import reveal


def _only(tool: str):
    """A shutil.which stand-in that finds a single named tool at /usr/bin."""
    return lambda name: f"/usr/bin/{name}" if name == tool else None


def test_linux_uses_a_plain_path_not_a_file_url():
    # The bug: a file:// URL routed through x-scheme-handler/file, whose default
    # handler is the web browser. A plain directory path resolves as
    # inode/directory instead, so the file manager opens.
    command = reveal.folder_command(Path("/home/u/Downloads"), "linux", which=_only("xdg-open"))
    assert command == ["/usr/bin/xdg-open", "/home/u/Downloads"]
    assert not any("file://" in part for part in command)


def test_linux_falls_back_to_gio_with_its_open_subcommand():
    command = reveal.folder_command(Path("/data/clips"), "linux", which=_only("gio"))
    assert command == ["/usr/bin/gio", "open", "/data/clips"]


def test_linux_returns_none_when_no_opener_is_installed():
    assert reveal.folder_command(Path("/x"), "linux", which=lambda name: None) is None


def test_windows_hands_the_folder_to_explorer():
    assert reveal.folder_command(Path(r"C:\Users\me\Downloads"), "win32") == [
        "explorer",
        r"C:\Users\me\Downloads",
    ]


def test_macos_hands_the_folder_to_open():
    assert reveal.folder_command(Path("/Users/me/Downloads"), "darwin") == [
        "open",
        "/Users/me/Downloads",
    ]


def test_open_folder_of_a_file_opens_its_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    launched: list[list[str]] = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", _only("xdg-open"))
    monkeypatch.setattr(subprocess, "Popen", lambda command, **kw: launched.append(command))
    a_file = tmp_path / "video.mp4"
    a_file.write_bytes(b"x")

    assert reveal.open_folder(a_file) is True
    # The folder is opened - the file itself is never passed as the argument.
    assert launched == [["/usr/bin/xdg-open", str(tmp_path)]]


def test_open_folder_reports_failure_when_no_manager_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert reveal.open_folder(tmp_path) is False
