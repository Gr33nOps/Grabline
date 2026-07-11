#!/usr/bin/env bash
# Assemble an AppImage from the PyInstaller onedir bundle in dist/grabline/.
# Usage: packaging/linux/build_appimage.sh <version>
# Requires: packaging/make_icons.py has produced packaging/grabline.png.
set -euo pipefail

VERSION="${1:?usage: build_appimage.sh <version>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIST="$ROOT/dist"
APPDIR="$ROOT/build/AppDir"

[ -d "$DIST/grabline" ] || { echo "missing $DIST/grabline - run pyinstaller first" >&2; exit 1; }

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -r "$DIST/grabline/." "$APPDIR/usr/bin/"
cp "$ROOT/packaging/linux/grabline.desktop" "$APPDIR/grabline.desktop"
cp "$ROOT/packaging/grabline.png" "$APPDIR/grabline.png"

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/grabline" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

TOOL="$ROOT/build/appimagetool"
if [ ! -x "$TOOL" ]; then
  curl -fsSL -o "$TOOL" \
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
  chmod +x "$TOOL"
fi

# --appimage-extract-and-run avoids needing FUSE on CI runners.
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" \
  "$DIST/Grabline-$VERSION-x86_64.AppImage"
echo "built $DIST/Grabline-$VERSION-x86_64.AppImage"
