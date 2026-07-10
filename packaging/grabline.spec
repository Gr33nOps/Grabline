# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Grabline Desktop (one-file, windowed).

Build from the repo root:  pyinstaller packaging/grabline.spec
"""

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

# yt-dlp loads its 1000+ extractors dynamically; make sure they all ship.
hiddenimports = collect_submodules("yt_dlp")

# curl_cffi (yt-dlp's TLS impersonation, needed by Dailymotion and friends)
# carries a native libcurl build that PyInstaller's scanner misses.
_cffi_datas, _cffi_binaries, _cffi_hidden = collect_all("curl_cffi")
hiddenimports += _cffi_hidden

# Ship the browser extension inside the binary so the Setup wizard can stage
# it to a stable path and "Load unpacked" always has a valid folder.
_extension_dir = os.path.join(SPECPATH, "..", "extension")
_datas = list(_cffi_datas) + [(_extension_dir, "extension")]
# A signed Firefox add-on, if one has been placed here (free AMO signing).
_xpi = os.path.join(SPECPATH, "..", "dist", "grabline.xpi")
if os.path.isfile(_xpi):
    _datas.append((_xpi, "."))

a = Analysis(
    [os.path.join(SPECPATH, "launch.py")],
    pathex=[os.path.join(SPECPATH, "..")],
    binaries=_cffi_binaries,
    datas=_datas,
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
