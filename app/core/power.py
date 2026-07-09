"""System power actions for the "when all downloads finish" setting.

Every command is an argument list (never a shell string, per S1) and best
effort: if the platform tool is missing or refused, we log and move on rather
than raise. These only ever run because the user explicitly chose them.
"""

from __future__ import annotations

import logging
import subprocess
import sys

log = logging.getLogger(__name__)

_SLEEP = {
    "linux": ["systemctl", "suspend"],
    "darwin": ["pmset", "sleepnow"],
    "win32": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
}
_SHUTDOWN = {
    "linux": ["systemctl", "poweroff"],
    "darwin": ["osascript", "-e", 'tell app "System Events" to shut down'],
    "win32": ["shutdown", "/s", "/t", "60"],
}


def _run(command: list[str]) -> bool:
    try:
        subprocess.Popen(command)  # argument list only - no shell (S1)
        return True
    except OSError as exc:
        log.warning("power command failed (%s): %s", command[0], exc)
        return False


def sleep() -> bool:
    """Put the computer to sleep. Returns whether the command launched."""
    command = _SLEEP.get(sys.platform)
    return _run(command) if command else False


def shutdown() -> bool:
    """Shut the computer down. Returns whether the command launched."""
    command = _SHUTDOWN.get(sys.platform)
    return _run(command) if command else False
