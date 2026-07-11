"""Desktop integration: menu entry and start-on-login (Linux paths)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.core import launcher

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="XDG paths")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return tmp_path


def test_launch_command_runs_this_installation():
    command = launcher.launch_command()
    assert command[0] == sys.executable
    assert command[-2:] == ["-m", "app"]
    assert launcher.launch_command(minimized=True)[-1] == "--minimized"


def test_launch_command_frozen_is_the_exe_itself(monkeypatch: pytest.MonkeyPatch):
    # A frozen build's executable IS Grabline; there's no "-m app" to run.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/opt/Grabline/grabline")
    assert launcher.launch_command() == ["/opt/Grabline/grabline"]
    assert launcher.launch_command(minimized=True) == ["/opt/Grabline/grabline", "--minimized"]


def test_menu_entry_written_with_icon(tmp_path: Path):
    entry = launcher.install_menu_entry(icon_png=b"\x89PNG-ish")
    assert entry is not None and entry.exists()
    content = entry.read_text()
    assert "[Desktop Entry]" in content
    assert sys.executable in content
    assert "-m app" in content
    assert "Categories=Network;FileTransfer;Qt;" in content
    icon_line = next(line for line in content.splitlines() if line.startswith("Icon="))
    assert Path(icon_line.removeprefix("Icon=")).read_bytes() == b"\x89PNG-ish"


def test_menu_entry_is_idempotent_and_self_healing(tmp_path: Path):
    entry = launcher.install_menu_entry(icon_png=b"png")
    assert entry is not None
    first = entry.read_text()
    entry.write_text(first.replace(sys.executable, "/somewhere/stale/python"))
    healed = launcher.install_menu_entry(icon_png=b"png")
    assert healed is not None and sys.executable in healed.read_text()


def test_autostart_roundtrip():
    assert launcher.autostart_enabled() is False
    launcher.set_autostart(True)
    assert launcher.autostart_enabled() is True
    entry = next(iter((Path(launcher._xdg_config_home()) / "autostart").iterdir()))
    content = entry.read_text()
    assert "--minimized" in content
    assert "X-GNOME-Autostart-enabled=true" in content
    launcher.set_autostart(False)
    assert launcher.autostart_enabled() is False
    launcher.set_autostart(False)  # disabling twice is fine
