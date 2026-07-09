"""Archive extraction for the auto-extract setting and the row-menu action.

Zip and tar (.tar/.tar.gz/.tgz/.tar.xz/.tar.bz2) are handled by the standard
library with a path-traversal guard so a malicious member cannot escape the
destination. .rar and .7z are extracted only if a suitable tool is on PATH.
"""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

from app.core import naming
from app.core.errors import DownloadError

_ZIP_SUFFIXES = (".zip",)
_TAR_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".tbz2")
_EXTERNAL_SUFFIXES = (".rar", ".7z")


def is_archive(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(_ZIP_SUFFIXES + _TAR_SUFFIXES + _EXTERNAL_SUFFIXES)


def _is_within(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _dest_dir(path: Path, dest: Path | None) -> Path:
    if dest is not None:
        return dest
    # A folder next to the archive, named after it, never clobbering.
    stem = path.name
    for suffix in _TAR_SUFFIXES + _ZIP_SUFFIXES + _EXTERNAL_SUFFIXES:
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return naming.unique_path(path.parent / (stem or "extracted"))


def extract(path: Path, dest: Path | None = None) -> Path:
    """Extract ``path`` into a folder (created next to it by default).

    Returns the destination folder. Raises DownloadError with a friendly
    message on anything unsupported or unsafe.
    """
    if not path.is_file():
        raise DownloadError(f"archive not found: {path}")
    name = path.name.lower()
    target = _dest_dir(path, dest)
    target.mkdir(parents=True, exist_ok=True)
    try:
        if name.endswith(_ZIP_SUFFIXES):
            _extract_zip(path, target)
        elif name.endswith(_TAR_SUFFIXES):
            _extract_tar(path, target)
        elif name.endswith(_EXTERNAL_SUFFIXES):
            _extract_external(path, target)
        else:
            raise DownloadError("Grabline does not know how to extract this file type.")
    except (zipfile.BadZipFile, tarfile.TarError) as exc:
        raise DownloadError(f"the archive could not be read ({exc})") from exc
    return target


def _extract_zip(path: Path, target: Path) -> None:
    with zipfile.ZipFile(path) as bundle:
        for member in bundle.namelist():
            if not _is_within(target, target / member):
                raise DownloadError("refusing to extract an archive with unsafe paths")
        bundle.extractall(target)


def _extract_tar(path: Path, target: Path) -> None:
    with tarfile.open(path) as bundle:
        for member in bundle.getmembers():
            if not _is_within(target, target / member.name):
                raise DownloadError("refusing to extract an archive with unsafe paths")
        # data filter (Python 3.12+) strips setuid bits, device nodes, etc.
        bundle.extractall(target, filter="data")


def _extract_external(path: Path, target: Path) -> None:
    if path.name.lower().endswith(".rar"):
        tool = shutil.which("unar") or shutil.which("unrar")
    else:
        tool = shutil.which("7z") or shutil.which("7za") or shutil.which("unar")
    if tool is None:
        raise DownloadError(
            f"extracting {path.suffix} files needs an external tool "
            "(install 'unar' or '7z') that Grabline could not find."
        )
    name = Path(tool).name
    if name in ("7z", "7za"):
        command = [tool, "x", "-y", f"-o{target}", str(path)]
    elif name == "unrar":
        command = [tool, "x", "-y", str(path), str(target) + "/"]
    else:  # unar
        command = [tool, "-force-overwrite", "-output-directory", str(target), str(path)]
    result = subprocess.run(command, capture_output=True, text=True)  # arg list only (S1)
    if result.returncode != 0:
        tail = result.stderr.strip().splitlines()[-1:] or ["extraction failed"]
        raise DownloadError(f"could not extract the archive ({tail[0]})")
