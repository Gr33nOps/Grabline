"""Is the Grabline desktop app running? PID-file based, no sockets (S3).

The Native Messaging host uses this to tell the extension whether a handed-off
URL will start immediately or wait for the next app launch.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path

from app.core import paths


def pid_file() -> Path:
    return paths.data_dir() / "grabline.pid"


def write_pid(path: Path | None = None) -> None:
    target = path or pid_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(os.getpid()))


def clear_pid(path: Path | None = None) -> None:
    (path or pid_file()).unlink(missing_ok=True)


def app_is_running(path: Path | None = None) -> bool:
    target = path or pid_file()
    try:
        pid = int(target.read_text().strip())
    except (OSError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)  # signal 0: existence check only
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - pid exists, owned by someone else
        return True
    else:
        return True


@contextlib.contextmanager
def running_marker(path: Path | None = None) -> Iterator[None]:
    """Context manager the app holds for its lifetime."""
    write_pid(path)
    try:
        yield
    finally:
        clear_pid(path)
