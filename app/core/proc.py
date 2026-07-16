"""Subprocess helpers shared by every tool Grabline shells out to.

On Windows a GUI app that launches a console program (FFmpeg, 7-Zip, Deno, a
virus scanner) pops a black console window unless the child is created with
CREATE_NO_WINDOW - which is what :func:`hidden` supplies. On other platforms
it is a no-op.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any


def hidden() -> dict[str, Any]:
    """Keyword arguments for ``subprocess.run/Popen`` that keep the child's
    console window from appearing (Windows); empty elsewhere."""
    if sys.platform == "win32":  # pragma: no cover - Windows-only
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {
            "startupinfo": startupinfo,
            "creationflags": subprocess.CREATE_NO_WINDOW,
        }
    return {}
