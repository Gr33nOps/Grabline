"""Platform data directories, Qt-free so the CLI and core never import PySide6.

Locations match what Qt's QStandardPaths.AppDataLocation resolves to with the
application/organization name "Grabline", so Phase 0 databases stay in place.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Grabline"


def data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / APP_NAME


def bin_dir() -> Path:
    """Where fetched, checksum-verified binaries (FFmpeg) are installed."""
    return data_dir() / "bin"


def default_download_dir() -> Path:
    return Path.home() / "Downloads" / APP_NAME
