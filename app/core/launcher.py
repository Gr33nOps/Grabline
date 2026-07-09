"""Desktop integration, IDM-style: an application-menu entry and start-on-login.

Everything here is per-user (no root) and idempotent. Linux gets the full
treatment - an XDG desktop entry written on first run so Grabline shows up in
the app grid/dock, and an autostart entry behind the Settings toggle. Windows
autostart uses the HKCU Run key; macOS a LaunchAgent plist. Both the dev venv
and the frozen (PyInstaller) binary work: entries launch whatever is running
right now.

Qt-free: the caller supplies rendered icon bytes.
"""

from __future__ import annotations

import contextlib
import os
import plistlib
import shlex
import sys
from pathlib import Path

APP_NAME = "Grabline"
_ENTRY_ID = "grabline"
_MAC_LABEL = "dev.grabline.desktop"


def launch_command(*, minimized: bool = False) -> list[str]:
    """How to start this very installation of Grabline."""
    frozen = getattr(sys, "frozen", False)
    command = [sys.executable] if frozen else [sys.executable, "-m", "app"]
    if minimized:
        command.append("--minimized")
    return command


def _exec_line(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))


def _icon_path() -> Path:
    return _xdg_data_home() / "icons" / "hicolor" / "256x256" / "apps" / f"{_ENTRY_ID}.png"


def _menu_entry_path() -> Path:
    return _xdg_data_home() / "applications" / f"{_ENTRY_ID}.desktop"


def _autostart_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "LaunchAgents" / f"{_MAC_LABEL}.plist"
    return _xdg_config_home() / "autostart" / f"{_ENTRY_ID}.desktop"


def _desktop_entry(command: list[str], *, icon: Path | None, autostart: bool = False) -> str:
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={APP_NAME}",
        "GenericName=Download Manager",
        "Comment=The open-source IDM: a download button on any media, anywhere",
        f"Exec={_exec_line(command)}",
        f"Icon={icon if icon is not None else _ENTRY_ID}",
        "Terminal=false",
        "Categories=Network;FileTransfer;Qt;",
        "StartupNotify=false",
    ]
    if autostart:
        lines.append("X-GNOME-Autostart-enabled=true")
    return "\n".join(lines) + "\n"


def _write_if_changed(path: Path, content: str) -> None:
    if path.exists() and path.read_text() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ------------------------------------------------------------- menu entry


def install_menu_entry(icon_png: bytes | None = None) -> Path | None:
    """Put Grabline in the application menu (Linux; silently a no-op
    elsewhere - the Windows installer and macOS app bundle own that job).
    Safe to call on every startup: rewrites only when something changed,
    so a moved venv heals itself."""
    if sys.platform != "linux":
        return None
    icon = _icon_path()
    if icon_png is not None and (not icon.exists() or icon.read_bytes() != icon_png):
        icon.parent.mkdir(parents=True, exist_ok=True)
        icon.write_bytes(icon_png)
    entry = _menu_entry_path()
    _write_if_changed(entry, _desktop_entry(launch_command(), icon=icon if icon.exists() else None))
    return entry


# -------------------------------------------------------------- autostart


def autostart_enabled() -> bool:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"
            ) as key:
                winreg.QueryValueEx(key, APP_NAME)
                return True
        except OSError:
            return False
    return _autostart_path().exists()


def set_autostart(enabled: bool) -> None:
    """Start Grabline (minimized to the tray) on login - or stop doing so."""
    command = launch_command(minimized=True)
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _exec_line(command))
            else:
                with contextlib.suppress(OSError):
                    winreg.DeleteValue(key, APP_NAME)
        return
    path = _autostart_path()
    if not enabled:
        path.unlink(missing_ok=True)
        return
    if sys.platform == "darwin":
        payload = plistlib.dumps(
            {"Label": _MAC_LABEL, "ProgramArguments": command, "RunAtLoad": True}
        ).decode()
        _write_if_changed(path, payload)
        return
    icon = _icon_path()
    _write_if_changed(
        path,
        _desktop_entry(command, icon=icon if icon.exists() else None, autostart=True),
    )
