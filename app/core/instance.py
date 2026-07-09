"""Is the Grabline desktop app running? PID-file based, no sockets (S3).

The Native Messaging host uses this to tell the extension whether a handed-off
URL will start immediately or wait for the next app launch.
"""

from __future__ import annotations

import contextlib
import os
import sys
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
    if sys.platform == "win32":  # pragma: no cover - windows-only
        return _pid_running_windows(pid)
    try:
        os.kill(pid, 0)  # signal 0: existence check only (POSIX semantics)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - pid exists, owned by someone else
        return True
    else:
        return True


def _pid_running_windows(pid: int) -> bool:  # pragma: no cover - windows-only
    """Existence check WITHOUT os.kill: on Windows, os.kill(pid, 0) is not a
    probe — it TerminateProcess()es the target. The native host used to
    murder the running app every time the extension asked 'is it running?'."""
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    # getattr keeps linux mypy happy: ctypes.windll only exists on Windows.
    kernel32 = getattr(ctypes, "windll").kernel32  # noqa: B009
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


@contextlib.contextmanager
def running_marker(path: Path | None = None) -> Iterator[None]:
    """Context manager the app holds for its lifetime."""
    write_pid(path)
    try:
        yield
    finally:
        clear_pid(path)
