"""Browser integration setup for the Setup wizard.

Copies the repo's extension folder to a fixed, writable location under the
data dir so a "Load unpacked" pick keeps working even if the checkout moves,
and reports which browsers are installed.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from app.core import paths

#: How each browser can install Grabline Connect for free.
#: "auto"  - a free store / signed add-on exists, so it can be one click.
#: "unpacked" - needs the Chrome Web Store ($5) for auto; free path is
#:             Developer mode -> Load unpacked (permanent, one manual step).
BROWSERS: tuple[tuple[str, str, str], ...] = (
    ("Firefox", "firefox", "auto"),
    ("Microsoft Edge", "chromium", "auto"),
    ("Chrome", "chromium", "unpacked"),
    ("Brave", "chromium", "unpacked"),
    ("Chromium", "chromium", "unpacked"),
)


@dataclass(frozen=True)
class BrowserStep:
    name: str
    kind: str  # "chromium" | "firefox"
    method: str  # "auto" | "unpacked"
    installed: bool


def _source_extension_dir() -> Path:
    """The repo's extension folder (paths.py is app/core/paths.py)."""
    return Path(paths.__file__).resolve().parents[2] / "extension"


def stable_extension_dir() -> Path:
    """The fixed location the browser loads the extension from."""
    return paths.data_dir() / "browser-extension"


def install_extension_files() -> Path:
    """Copy the extension to the stable path and return it. Overwrites any
    previous copy so a git pull refreshes it."""
    source = _source_extension_dir()
    manifest = source / "manifest.json"
    if not manifest.is_file():
        raise FileNotFoundError(f"extension folder not found at {source}")
    target = stable_extension_dir()
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target)
    return target


def _chromium_root(name: str, home: Path, platform: str) -> Path | None:
    roots = {
        "linux": {
            "Chrome": home / ".config" / "google-chrome",
            "Chromium": home / ".config" / "chromium",
            "Microsoft Edge": home / ".config" / "microsoft-edge",
            "Brave": home / ".config" / "BraveSoftware" / "Brave-Browser",
            "Firefox": home / ".mozilla",
        },
        "darwin": {
            "Chrome": home / "Library" / "Application Support" / "Google" / "Chrome",
            "Chromium": home / "Library" / "Application Support" / "Chromium",
            "Microsoft Edge": home / "Library" / "Application Support" / "Microsoft Edge",
            "Brave": home / "Library" / "Application Support" / "BraveSoftware" / "Brave-Browser",
            "Firefox": home / "Library" / "Application Support" / "Firefox",
        },
    }
    return roots.get(platform, {}).get(name)


def _cookie_roots(platform: str, home: Path) -> dict[str, Path]:
    """Browser key (as yt-dlp / SESSION_BROWSERS names it) -> the profile
    root that only exists once that browser has actually been set up here."""
    if platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        return {
            "firefox": roaming / "Mozilla" / "Firefox" / "Profiles",
            "chrome": local / "Google" / "Chrome" / "User Data",
            "brave": local / "BraveSoftware" / "Brave-Browser" / "User Data",
            "chromium": local / "Chromium" / "User Data",
            "opera": roaming / "Opera Software" / "Opera Stable",
            "edge": local / "Microsoft" / "Edge" / "User Data",
        }
    if platform == "darwin":
        support = home / "Library" / "Application Support"
        return {
            "firefox": support / "Firefox" / "Profiles",
            "chrome": support / "Google" / "Chrome",
            "brave": support / "BraveSoftware" / "Brave-Browser",
            "chromium": support / "Chromium",
            "opera": support / "com.operasoftware.Opera",
            "edge": support / "Microsoft Edge",
        }
    config = home / ".config"
    return {
        "firefox": home / ".mozilla" / "firefox",
        "chrome": config / "google-chrome",
        "brave": config / "BraveSoftware" / "Brave-Browser",
        "chromium": config / "chromium",
        "opera": config / "opera",
        "edge": config / "microsoft-edge",
    }


#: Preference when several browsers are present. Firefox first: an existing
#: Firefox profile is a strong signal the person actually uses it, whereas
#: Edge ships with Windows and is usually present but unused.
_COOKIE_BROWSER_PREFERENCE = ("firefox", "chrome", "brave", "chromium", "opera", "edge")


def detect_cookie_browser(platform: str | None = None, home: Path | None = None) -> str | None:
    """The best browser to read a login session from: the first, by active-use
    preference, whose profile directory exists. None when nothing is found, so
    callers keep their own fallback. Used to seed the 'Browser session' choice
    so it points at the browser the person is signed into, not a hardcoded one."""
    platform = platform or sys.platform
    home = home or Path.home()
    roots = _cookie_roots(platform, home)
    for key in _COOKIE_BROWSER_PREFERENCE:
        root = roots.get(key)
        if root is not None and root.exists():
            return key
    return None


def detect_browsers(platform: str | None = None, home: Path | None = None) -> list[BrowserStep]:
    """The browsers to show in the wizard, with a best-effort 'installed' flag.

    On Windows detection is unreliable (per-user vs machine, registry), so
    every browser is shown as available there.
    """
    platform = platform or sys.platform
    home = home or Path.home()
    steps: list[BrowserStep] = []
    for name, kind, method in BROWSERS:
        if platform == "win32":
            installed = True
        else:
            root = _chromium_root(name, home, platform)
            installed = root is not None and root.exists()
        steps.append(BrowserStep(name=name, kind=kind, method=method, installed=installed))
    return steps
