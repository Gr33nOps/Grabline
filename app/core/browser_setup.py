"""Browser integration setup for the Setup wizard.

Copies the repo's extension folder to a fixed, writable location under the
data dir so a "Load unpacked" pick keeps working even if the checkout moves,
and reports which browsers are installed.
"""

from __future__ import annotations

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
