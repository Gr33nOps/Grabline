"""Open a download's folder in the OS file manager.

``QDesktopServices.openUrl`` on a ``file://`` URL is unreliable on Linux:
xdg-open routes a ``file://`` argument through ``x-scheme-handler/file``, whose
default handler is often the web browser - so "Open folder" opened the download
in Firefox instead of the file manager (the reported bug). We drive the file
manager directly, and on Linux hand it a plain directory path (resolved as
``inode/directory``) rather than a URL, so the browser is never in the picture.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from app.core import proc

# Linux file managers to try, best first: xdg-open honours the desktop's
# default, gio is the GLib opener, and the rest are the common concrete apps.
_LINUX_OPENERS = ("xdg-open", "gio", "nautilus", "dolphin", "thunar", "pcmanfm", "nemo")


def folder_command(
    directory: Path,
    platform: str,
    which: Callable[[str], str | None] | None = None,
) -> list[str] | None:
    """The argv that opens *directory* in the file manager on *platform*, or
    ``None`` if no opener is available. Pure - it never runs a subprocess, so
    the per-platform choice is testable on any host."""
    if platform == "win32":
        return ["explorer", str(directory)]
    if platform == "darwin":
        return ["open", str(directory)]
    # Linux / other X-Desktop unix: a plain path, never a file:// URL.
    resolve = which or shutil.which
    for tool in _LINUX_OPENERS:
        found = resolve(tool)
        if not found:
            continue
        if tool == "gio":
            return [found, "open", str(directory)]
        return [found, str(directory)]
    return None


def open_folder(path: str | Path) -> bool:
    """Open *path*'s folder in the OS file manager. A directory opens directly;
    a file opens its parent. Returns ``True`` if a file manager was launched."""
    target = Path(path)
    directory = target if target.is_dir() else target.parent
    command = folder_command(directory, sys.platform)
    if command is None:
        return False
    try:
        subprocess.Popen(command, **proc.hidden())  # arg list only, no shell (S1)
    except OSError:
        return False
    return True
