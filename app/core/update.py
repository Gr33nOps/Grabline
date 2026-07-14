"""Best-effort update check against the GitHub releases API.

Never raises and never blocks the UI (call it from a thread). If the repo is
private or offline, it simply returns None and nothing happens.
"""

from __future__ import annotations

import logging
import re

import httpx

from app import __version__
from app.core import net

log = logging.getLogger(__name__)

_LATEST = "https://api.github.com/repos/Gr33nOps/Grabline/releases/latest"
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
