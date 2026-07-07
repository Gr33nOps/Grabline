# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Grabline Desktop (one-file, windowed).

Build from the repo root:  pyinstaller packaging/grabline.spec
"""

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

# yt-dlp loads its 1000+ extractors dynamically; make sure they all ship.
hiddenimports = collect_submodules("yt_dlp")

a = Analysis(
    [os.path.join(SPECPATH, "launch.py")],
    pathex=[os.path.join(SPECPATH, "..")],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Grabline",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="Grabline.app",
        icon=None,
        bundle_identifier="dev.grabline.desktop",
    )
