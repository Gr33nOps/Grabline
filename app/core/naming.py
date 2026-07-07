"""Filename derivation and sanitization (S4: filesystem safety)."""

from __future__ import annotations

import mimetypes
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


#: Stems servers hand out that say nothing about the content (F1.8).
_UGLY_STEMS = frozenset(
    {
        "videoplayback",
        "download",
        "index",
        "file",
        "video",
        "audio",
        "media",
        "stream",
        "content",
        "item",
        "untitled",
        "attachment",
        "get",
        "fetch",
        FALLBACK_NAME,
    }
)


def is_ugly_name(name: str) -> bool:
    """Would a human curse this filename? (videoplayback.mp4, index, 1234…)"""
    stem = Path(name).stem.lower()
    return len(stem) < 3 or stem.isdigit() or stem in _UGLY_STEMS


def improved_filename(url: str, page_title: str | None, content_type: str | None = None) -> str:
    """The ugly-name fixer (F1.8): keep good URL names, replace junk with the
    page title, keeping (or guessing) the file extension."""
    from_url = filename_from_url(url)
    if not page_title or not is_ugly_name(from_url):
        return from_url
    extension = Path(from_url).suffix
    if not extension and content_type:
        extension = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
    return sanitize_filename(page_title.strip() + extension)


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
