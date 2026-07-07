"""Filename derivation and sanitization (S4: filesystem safety)."""

from __future__ import annotations

import os.path
import posixpath
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

FALLBACK_NAME = "download"
MAX_NAME_LENGTH = 150
_MAX_EXT_LENGTH = 16

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def sanitize_filename(name: str, max_length: int = MAX_NAME_LENGTH) -> str:
    """Make an arbitrary (often title-derived) string safe as a filename."""
    name = _INVALID_CHARS.sub("_", name).strip().strip(".")
    if not name:
        return FALLBACK_NAME
    if name.split(".")[0].upper() in _WINDOWS_RESERVED:
        name = "_" + name
    if len(name) > max_length:
        root, ext = os.path.splitext(name)
        ext = ext[:_MAX_EXT_LENGTH]
        name = root[: max_length - len(ext)] + ext
    return name


def filename_from_url(url: str) -> str:
    name = unquote(posixpath.basename(urlsplit(url).path))
    return sanitize_filename(name) if name else FALLBACK_NAME


def unique_path(path: Path) -> Path:
    """Never overwrite silently: 'file.bin' -> 'file (1).bin' -> ... (S4)."""
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1
