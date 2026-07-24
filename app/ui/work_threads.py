"""Worker-thread infrastructure for the main window: the off-the-GUI-thread
resolve and file-operation threads, and the progress relay that marshals a
worker's progress back onto the GUI thread. Kept out of main_window.py so the
window file is about the window, not thread plumbing.

Lifetime note: these threads are parented (or handed to ``threads.retain``) by
their caller so a dropped Python reference can never destroy a still-running
QThread - the crash class fixed app-wide.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal

from app.core.errors import DownloadError
from app.core.resolver import Resolver
from app.core.settings import Settings


class ResolveThread(QThread):
    #: Resolution, page_title (str|None), quality label (str|None, F1.3),
    #: fallback URLs (tuple[str,...]), extra HTTP headers (dict[str,str]).
    resolved = Signal(object, object, object, object, object)

    def __init__(
        self,
        resolver: Resolver,
        url: str,
        settings: Settings,
        page_title: str | None,
        quality: str | None = None,
        fallbacks: tuple[str, ...] = (),
        headers: dict[str, str] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._resolver = resolver
        self._url = url
        self._page_title = page_title
        self._quality = quality
        self._fallbacks = fallbacks
        self._headers = headers or {}
        self._use_session = settings.use_browser_session
        self._browser = settings.session_browser
        self._proxy = settings.proxy

    def run(self) -> None:
        resolution = self._resolver.resolve(
            self._url,
            use_session=self._use_session,
            session_browser=self._browser,
            proxy=self._proxy,
            headers=self._headers or None,
        )
        self.resolved.emit(
            resolution, self._page_title, self._quality, self._fallbacks, self._headers
        )


class FileOpThread(QThread):
    """Runs a slow file operation (hashing, extraction) off the UI thread."""

    done = Signal(object, object)  # result, error Exception | None

    def __init__(self, work: Callable[[], object], parent: QObject | None = None) -> None:
        # Parented: the C++ thread object's lifetime is owned by Qt, so a
        # dropped Python reference can never destroy a still-running QThread
        # (the classic hard crash).
        super().__init__(parent)
        self._work = work

    def run(self) -> None:
        try:
            self.done.emit(self._work(), None)
        except (OSError, DownloadError, ValueError) as exc:
            # The exception object itself, so handlers can distinguish
            # PasswordRequired from a plain failure; str(error) still works.
            self.done.emit(None, exc)


class ProgressRelay(QObject):
    """Marshals worker-thread progress onto the GUI thread via a signal."""

    tick = Signal(int)
