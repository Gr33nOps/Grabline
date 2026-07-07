"""Clipboard watcher (F0.5): copy a URL anywhere → an unobtrusive offer to
download it. Snooze/disable lives in Settings and the tray menu.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from app.core.settings import Settings


def is_probable_url(text: str) -> bool:
    text = text.strip()
    if not text or any(ch.isspace() for ch in text):
        return False
    parts = urlsplit(text)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


class ClipboardWatcher(QObject):
    url_copied = Signal(str)

    def __init__(self, app: QApplication, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._clipboard = app.clipboard()
        self._last: str | None = None
        self._clipboard.dataChanged.connect(self._on_change)

    def _on_change(self) -> None:
        if not self.settings.clipboard_watcher:
            return
        text = self._clipboard.text().strip()
        if not text or text == self._last:
            return
        self._last = text
        if is_probable_url(text):
            self.url_copied.emit(text)
