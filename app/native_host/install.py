"""Register the Native Messaging host with installed browsers (F1.1).

Writes the host manifests browsers look up by name, each pinning the allowed
extension IDs (S3), plus a small launcher script the manifests point at.

Usage:
    python -m app.native_host.install            # register for this user
    python -m app.native_host.install --dry-run  # show what would be written
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from app.core import paths
from app.native_host import CHROME_EXTENSION_IDS, FIREFOX_EXTENSION_IDS, HOST_NAME


@dataclass(frozen=True)
class BrowserTarget:
    browser: str
    manifest_dir: Path
    kind: str  # "chromium" | "firefox"


def _linux_targets(home: Path) -> list[BrowserTarget]:
    config = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")))
    return [
        BrowserTarget("Chrome", config / "google-chrome" / "NativeMessagingHosts", "chromium"),
        BrowserTarget("Chromium", config / "chromium" / "NativeMessagingHosts", "chromium"),
        BrowserTarget("Edge", config / "microsoft-edge" / "NativeMessagingHosts", "chromium"),
        BrowserTarget(
            "Brave",
            config / "BraveSoftware" / "Brave-Browser" / "NativeMessagingHosts",
            "chromium",
        ),
        BrowserTarget("Firefox", home / ".mozilla" / "native-messaging-hosts", "firefox"),
    ]


def _darwin_targets(home: Path) -> list[BrowserTarget]:
    support = home / "Library" / "Application Support"
    return [
        BrowserTarget("Chrome", support / "Google" / "Chrome" / "NativeMessagingHosts", "chromium"),
        BrowserTarget("Edge", support / "Microsoft Edge" / "NativeMessagingHosts", "chromium"),
        BrowserTarget("Firefox", support / "Mozilla" / "NativeMessagingHosts", "firefox"),
    ]


def browser_targets(platform: str | None = None, home: Path | None = None) -> list[BrowserTarget]:
    platform = platform or sys.platform
    home = home or Path.home()
    if platform == "darwin":
        return _darwin_targets(home)
    if platform == "win32":
        # Windows resolves manifests via registry keys; handled in install().
        return []
    return _linux_targets(home)


def host_manifest(kind: str, launcher: Path) -> dict[str, object]:
    manifest: dict[str, object] = {
        "name": HOST_NAME,
        "description": "Grabline download manager connector",
        "path": str(launcher),
        "type": "stdio",
    }
    if kind == "firefox":
        manifest["allowed_extensions"] = list(FIREFOX_EXTENSION_IDS)
    else:
        manifest["allowed_origins"] = [
            f"chrome-extension://{ext_id}/" for ext_id in CHROME_EXTENSION_IDS
        ]
    return manifest


def write_launcher(bin_dir: Path | None = None) -> Path:
    """A tiny script that runs the host with the current interpreter.

    Packaged builds will point manifests at the app binary with a
    ``--native-host`` flag instead; this covers the from-source install.
    """
    target_dir = bin_dir or paths.bin_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":  # pragma: no cover - windows-only branch
        launcher = target_dir / "grabline-host.bat"
        launcher.write_text(f'@echo off\r\n"{sys.executable}" -m app.native_host %*\r\n')
    else:
        launcher = target_dir / "grabline-host"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m app.native_host "$@"\n')
        launcher.chmod(0o755)
    return launcher


def install(
    *,
    dry_run: bool = False,
    platform: str | None = None,
    home: Path | None = None,
    bin_dir: Path | None = None,
) -> list[Path]:
    """Write manifests for every known browser location. Returns paths written."""
    platform = platform or sys.platform
    launcher = write_launcher(bin_dir) if not dry_run else (paths.bin_dir() / "grabline-host")
    written: list[Path] = []
    if platform == "win32":  # pragma: no cover - registry path, windows-only
        return _install_windows_registry(launcher, dry_run=dry_run)
    for target in browser_targets(platform, home):
        manifest_path = target.manifest_dir / f"{HOST_NAME}.json"
        payload = json.dumps(host_manifest(target.kind, launcher), indent=2) + "\n"
        if dry_run:
            print(f"would write {manifest_path}")
            continue
        target.manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(payload)
        written.append(manifest_path)
    return written


def _install_windows_registry(
    launcher: Path, *, dry_run: bool
) -> list[Path]:  # pragma: no cover - windows-only
    if sys.platform == "win32":
        import winreg

        manifest_dir = paths.data_dir() / "native_host"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for kind, registry_root in (
            ("chromium", r"Software\Google\Chrome\NativeMessagingHosts"),
            ("chromium", r"Software\Microsoft\Edge\NativeMessagingHosts"),
            ("firefox", r"Software\Mozilla\NativeMessagingHosts"),
        ):
            manifest_path = manifest_dir / f"{HOST_NAME}.{kind}.json"
            if dry_run:
                print(f"would write {manifest_path} and HKCU\\{registry_root}\\{HOST_NAME}")
                continue
            manifest_path.write_text(json.dumps(host_manifest(kind, launcher), indent=2) + "\n")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{registry_root}\{HOST_NAME}") as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_path))
            written.append(manifest_path)
        return written
    raise RuntimeError("registry registration is Windows-only")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print targets, write nothing")
    args = parser.parse_args(argv)
    written = install(dry_run=args.dry_run)
    for path in written:
        print(f"registered {path}")
    if written:
        print(
            "Pairing complete. Load the extension (see extension/README.md), "
            "then the right-click menu and toolbar button will reach Grabline."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
