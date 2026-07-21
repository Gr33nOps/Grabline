"""Best-effort update check against the GitHub releases API.

Never raises and never blocks the UI (call it from a thread). If the repo is
private or offline, it simply returns None and nothing happens.
"""

from __future__ import annotations

import logging
import re
import threading

import httpx

from app import __version__
from app.core import net
from app.core.errors import DownloadError


class UpdateCancelled(DownloadError):
    """The user cancelled an in-progress installer download. Subclasses
    DownloadError so the UI's file-op thread delivers it like any other
    failure, and the caller tells a cancel apart from a real error."""


log = logging.getLogger(__name__)

_LATEST = "https://api.github.com/repos/Gr33nOps/GrabLine/releases/latest"
_NUM = re.compile(r"\d+")


def _parts(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in _NUM.findall(version))


def is_newer(candidate: str, current: str) -> bool:
    """True if ``candidate`` is a strictly higher version than ``current``."""
    return _parts(candidate) > _parts(current)


def latest_release(proxy: str | None = None) -> tuple[str, str] | None:
    """Return (tag, html_url) of the latest release, or None if unavailable."""
    try:
        with net.build_client(proxy=proxy, follow_redirects=True, timeout=10) as client:
            response = client.get(_LATEST, headers={"Accept": "application/vnd.github+json"})
        if response.status_code != 200:
            return None
        data = response.json()
        tag = str(data.get("tag_name") or "").strip()
        url = str(data.get("html_url") or "").strip()
        return (tag, url) if tag else None
    except (httpx.HTTPError, ValueError) as exc:
        log.debug("update check failed: %s", exc)
        return None


def check_for_update(proxy: str | None = None) -> tuple[str, str] | None:
    """Return (tag, url) when a newer release exists, else None."""
    latest = latest_release(proxy)
    if latest is None:
        return None
    tag, url = latest
    return (tag, url) if is_newer(tag, __version__) else None


#: Where the "Download update" fallback points: the website's download
#: section, which always links the current installers.
WEBSITE_DOWNLOAD_URL = "https://gr33nops.github.io/GrabLine/#download"


def _asset_matches(name: str, platform: str) -> bool:
    lowered = name.lower()
    if platform.startswith("win"):
        return lowered.endswith(".exe") and "setup" in lowered
    if platform == "darwin":
        return lowered.endswith(".dmg")
    return lowered.endswith(".appimage")


def installer_update(
    proxy: str | None = None, platform: str | None = None
) -> tuple[str, str, str] | None:
    """(tag, asset name, download URL) of this platform's installer for a
    newer release, or None (up to date / offline / no matching asset)."""
    import sys

    platform = platform or sys.platform
    try:
        with net.build_client(proxy=proxy, follow_redirects=True, timeout=10) as client:
            response = client.get(_LATEST, headers={"Accept": "application/vnd.github+json"})
        if response.status_code != 200:
            return None
        data = response.json()
        tag = str(data.get("tag_name") or "").strip()
        if not tag or not is_newer(tag, __version__):
            return None
        for asset in data.get("assets") or []:
            name = str(asset.get("name") or "")
            url = str(asset.get("browser_download_url") or "")
            if name and url and _asset_matches(name, platform):
                return (tag, name, url)
        return None
    except (httpx.HTTPError, ValueError) as exc:
        log.debug("installer lookup failed: %s", exc)
        return None


def download_installer(
    url: str,
    dest_dir: str,
    filename: str,
    proxy: str | None = None,
    progress: object = None,
    cancel: threading.Event | None = None,
) -> str:
    """Stream the installer to ``dest_dir`` and return its path. ``progress`` is
    an optional callable(received_bytes, total_bytes_or_None).

    Pass a ``cancel`` event to make the download interruptible: it is checked
    once per chunk, and when set the partial file is removed and
    :class:`UpdateCancelled` is raised, so pressing Cancel actually stops the
    transfer instead of leaving it running and opening a half-written installer.
    """
    from pathlib import Path

    target = Path(dest_dir) / filename
    cancelled = False
    with (
        net.build_client(proxy=proxy, follow_redirects=True, timeout=30) as client,
        client.stream("GET", url) as response,
    ):
        response.raise_for_status()
        total_raw = response.headers.get("Content-Length")
        total = int(total_raw) if total_raw and total_raw.isdigit() else None
        received = 0
        with open(target, "wb") as handle:
            for chunk in response.iter_bytes(65536):
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    break
                handle.write(chunk)
                received += len(chunk)
                if callable(progress):
                    progress(received, total)
    # Unlink only after every handle above is closed (Windows can't remove an
    # open file), then raise so the caller never opens the partial installer.
    if cancelled:
        target.unlink(missing_ok=True)
        raise UpdateCancelled("update download cancelled")
    return str(target)
