"""Render Grabline's app icon into the platform icon files packaging needs.

Run headless in CI (QT_QPA_PLATFORM=offscreen). Produces, next to this file:
  - grabline.png       256px, for the Linux .desktop / AppImage
  - grabline.ico       multi-size, for the Windows installer (needs Pillow)
  - grabline.iconset/  PNG set, for macOS `iconutil` to turn into .icns

Missing tools degrade gracefully - the PyInstaller spec treats icons as
optional, so a build still succeeds without them.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent


def _png(size: int) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QGuiApplication

    from app.ui.icon import make_app_icon

    QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    pixmap = make_app_icon().pixmap(size, size)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(bytearray(buffer.data().data()))


def main() -> int:
    (OUT / "grabline.png").write_bytes(_png(256))
    print(f"wrote {OUT / 'grabline.png'}")

    try:
        from PIL import Image

        sizes = (16, 32, 48, 64, 128, 256)
        images = [Image.open(io.BytesIO(_png(s))) for s in sizes]
        images[0].save(OUT / "grabline.ico", format="ICO", sizes=[(s, s) for s in sizes])
        print(f"wrote {OUT / 'grabline.ico'}")
    except Exception as exc:  # Pillow absent or ICO unsupported - non-fatal
        print(f"skipped grabline.ico: {exc}")

    iconset = OUT / "grabline.iconset"
    iconset.mkdir(exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        (iconset / f"icon_{size}x{size}.png").write_bytes(_png(size))
        (iconset / f"icon_{size}x{size}@2x.png").write_bytes(_png(size * 2))
    print(f"wrote {iconset}/ ({len(list(iconset.glob('*.png')))} PNGs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
