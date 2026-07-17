"""Keep a running QThread alive until it actually finishes.

A QThread owned only by a dialog is destroyed the moment that dialog closes.
If its worker is still running - a slow thumbnail fetch, a URL inspection, an
FFmpeg download - Qt aborts the whole process:

    QThread: Destroyed while thread '' is still running

which is a SIGABRT with no Python traceback. Handing the thread to ``retain``
moves ownership out of the dialog: this module holds the reference until the
thread emits ``finished``, then releases it and schedules ``deleteLater``. The
dialog may close whenever it likes; the thread lives exactly as long as its
work does, and is destroyed only once it has genuinely stopped.

The thread must be unparented (or at least not parented to the dialog) so a
closing dialog cannot destroy it out from under this registry.
"""

from __future__ import annotations

from PySide6.QtCore import QThread

#: Threads currently running on someone's behalf. A module-level strong
#: reference is what keeps the QThread's C++ object alive past the death of
#: whatever UI started it.
_RUNNING: set[QThread] = set()


def retain(thread: QThread) -> None:
    """Own ``thread`` until it finishes, then release and delete it. Call this
    immediately before ``thread.start()``."""
    _RUNNING.add(thread)

    def _release() -> None:
        _RUNNING.discard(thread)
        thread.deleteLater()

    thread.finished.connect(_release)


def shutdown(timeout_ms: int = 6000) -> None:
    """On app quit, wait for retained threads to finish before the interpreter
    tears them down. Destroying a still-running QThread aborts the process, so
    the alternative to waiting is a crash on exit. Retained workers use bounded
    network timeouts, so a normal quit returns at once; a quit during a stuck
    fetch waits at most ``timeout_ms``. Any thread that still hasn't stopped is
    left referenced on purpose - a leaked-but-alive thread is safe; a
    destroyed-while-running one is not."""
    import time

    deadline = time.monotonic() + timeout_ms / 1000
    for thread in list(_RUNNING):
        thread.requestInterruption()
    for thread in list(_RUNNING):
        remaining = max(0, int((deadline - time.monotonic()) * 1000))
        thread.wait(remaining)
