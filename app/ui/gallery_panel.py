"""Gallery grid (F2.2): the image URLs Grabline Connect collected on a page,
shown as a checkable thumbnail grid - pick, then batch-download.

Thumbnails load lazily in one background thread; the grid is usable (and the
download can start) before any of them arrive.
"""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

import httpx
from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui import chrome

_THUMB_SIZE = 128
_MAX_THUMB_BYTES = 10 * 1024 * 1024

#: Loader threads stay referenced here until they finish, so closing the
#: dialog mid-fetch can never destroy a QThread that is still running.
_ACTIVE_THREADS: set[_ThumbnailThread] = set()


def _short_name(url: str) -> str:
    name = unquote(urlsplit(url).path.rsplit("/", 1)[-1]) or url
    return name if len(name) <= 24 else name[:21] + "…"


class _ThumbnailThread(QThread):
    loaded = Signal(int, bytes)  # row, image bytes

    def __init__(self, urls: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._urls = urls
        self._stopping = False

    def stop(self) -> None:
        self._stopping = True

    def run(self) -> None:
        with httpx.Client(follow_redirects=True, timeout=10) as client:
            for row, url in enumerate(self._urls):
                if self._stopping:
                    return
                try:
                    response = client.get(url)
                    if response.status_code == 200 and len(response.content) <= _MAX_THUMB_BYTES:
                        self.loaded.emit(row, response.content)
                except httpx.HTTPError:
                    continue


class GalleryPanel(chrome.Dialog):
    def __init__(
        self,
        urls: list[str],
        *,
        page_title: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.urls = urls
        self.setWindowTitle("Images on this page")
        self.setMinimumSize(640, 480)

        layout = QVBoxLayout(self)
        title = QLabel(f"{page_title or 'This page'} - {len(urls)} images")
        title.setWordWrap(True)
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(title)

        select_row = QHBoxLayout()
        select_all = QPushButton("Select all")
        select_none = QPushButton("Select none")
        select_all.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        select_none.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        select_row.addWidget(select_all)
        select_row.addWidget(select_none)
        select_row.addStretch(1)
        self._selection_label = QLabel("")
        select_row.addWidget(self._selection_label)
        layout.addLayout(select_row)

        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(QSize(_THUMB_SIZE, _THUMB_SIZE))
        self.grid.setGridSize(QSize(_THUMB_SIZE + 24, _THUMB_SIZE + 40))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setUniformItemSizes(True)
        for url in urls:
            item = QListWidgetItem(_short_name(url))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setToolTip(url)
            self.grid.addItem(item)
        self.grid.itemChanged.connect(lambda _item: self._update_count())
        layout.addWidget(self.grid)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_count()

        self._thumbs = _ThumbnailThread(urls)
        _ACTIVE_THREADS.add(self._thumbs)
        self._thumbs.finished.connect(lambda t=self._thumbs: _ACTIVE_THREADS.discard(t))
        self._thumbs.loaded.connect(self._on_thumbnail)
        self._thumbs.start()

    # -------------------------------------------------------------- result

    def selected_urls(self) -> list[str]:
        return [
            url
            for row, url in enumerate(self.urls)
            if self.grid.item(row).checkState() is Qt.CheckState.Checked
        ]

    # ------------------------------------------------------------ internals

    def _on_thumbnail(self, row: int, data: bytes) -> None:
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            scaled = pixmap.scaled(
                _THUMB_SIZE,
                _THUMB_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.grid.item(row).setIcon(QIcon(scaled))

    def _set_all(self, state: Qt.CheckState) -> None:
        for row in range(self.grid.count()):
            self.grid.item(row).setCheckState(state)

    def _update_count(self) -> None:
        count = len(self.selected_urls())
        self._selection_label.setText(f"{count} selected")
        self._ok_button.setText(f"Download {count}" if count else "Download")
        self._ok_button.setEnabled(count > 0)

    def done(self, result: int) -> None:
        self._thumbs.stop()
        super().done(result)
