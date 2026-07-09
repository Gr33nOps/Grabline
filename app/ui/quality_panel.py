"""The quality panel (F0.3): metadata card + curated quality list + audio
options + subtitles + optional clip trim (F0.7). Shown after the resolver
routes a URL to the Smart Engine.
"""

from __future__ import annotations

from typing import Any

import httpx
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.engines.smart import MediaInfo, QualityOption
from app.ui.format import duration_text, human_bytes


def parse_timestamp(text: str) -> float | None:
    """'90', '1:30', '1:02:03' -> seconds; None for blank; ValueError if bad."""
    text = text.strip()
    if not text:
        return None
    parts = text.split(":")
    if not 1 <= len(parts) <= 3 or not all(p.strip().isdigit() or "." in p for p in parts):
        raise ValueError(f"not a timestamp: {text!r}")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


class _ThumbnailFetcher(QThread):
    loaded = Signal(bytes)

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url

    def run(self) -> None:
        try:
            response = httpx.get(self._url, timeout=5, follow_redirects=True)
            if response.status_code == 200:
                self.loaded.emit(response.content)
        except httpx.HTTPError:
            pass  # a missing thumbnail is cosmetic


class QualityPanel(QDialog):
    def __init__(self, media: MediaInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.media = media
        self.setWindowTitle("Grabline - choose quality")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self._thumbnail = QLabel()
        self._thumbnail.setFixedSize(160, 90)
        self._thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumbnail.setStyleSheet("background: rgba(127,127,127,0.15); border-radius: 4px;")
        header.addWidget(self._thumbnail)
        text_column = QVBoxLayout()
        title = QLabel(media.title)
        title.setWordWrap(True)
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        text_column.addWidget(title)
        detail_parts = [part for part in (media.uploader, duration_text(media.duration)) if part]
        detail = QLabel("  •  ".join(detail_parts))
        detail.setStyleSheet("color: gray;")
        text_column.addWidget(detail)
        text_column.addStretch(1)
        header.addLayout(text_column, 1)
        layout.addLayout(header)

        self.options_list = QListWidget()
        for index, option in enumerate(media.options):
            label = option.label
            if option.kind == "audio":
                label += "  (audio only)"
            if option.estimated_size:
                label += f"   ~{human_bytes(option.estimated_size)}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.options_list.addItem(item)
        if media.options:
            self.options_list.setCurrentRow(0)
        self.options_list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.options_list)

        subtitle_row = QHBoxLayout()
        subtitle_row.addWidget(QLabel("Subtitles:"))
        self.subtitle_combo = QComboBox()
        self.subtitle_combo.addItem("None", None)
        for lang in media.subtitle_languages:
            self.subtitle_combo.addItem(lang, {"lang": lang, "auto": False})
        for lang in media.auto_caption_languages:
            if lang not in media.subtitle_languages:
                self.subtitle_combo.addItem(f"{lang} (auto)", {"lang": lang, "auto": True})
        subtitle_row.addWidget(self.subtitle_combo, 1)
        self.embed_subtitles = QCheckBox("Embed")
        subtitle_row.addWidget(self.embed_subtitles)
        layout.addLayout(subtitle_row)

        trim_row = QHBoxLayout()
        trim_row.addWidget(QLabel("Clip (optional):"))
        self.trim_start = QLineEdit()
        self.trim_start.setPlaceholderText("start  e.g. 1:20")
        self.trim_end = QLineEdit()
        self.trim_end.setPlaceholderText("end  e.g. 2:45")
        trim_row.addWidget(self.trim_start)
        trim_row.addWidget(self.trim_end)
        layout.addLayout(trim_row)
        self._trim_error = QLabel("")
        self._trim_error.setStyleSheet("color: #c0392b;")
        self._trim_error.hide()
        layout.addWidget(self._trim_error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Download")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._fetcher: _ThumbnailFetcher | None = None
        if media.thumbnail_url:
            self._fetcher = _ThumbnailFetcher(media.thumbnail_url)
            self._fetcher.loaded.connect(self._set_thumbnail)
            self._fetcher.start()

    # -------------------------------------------------------------- result

    def selected_option(self) -> QualityOption | None:
        row = self.options_list.currentRow()
        if 0 <= row < len(self.media.options):
            return self.media.options[row]
        return None

    def subtitles_config(self) -> dict[str, Any] | None:
        config = self.subtitle_combo.currentData()
        if config is None:
            return None
        return {**config, "embed": self.embed_subtitles.isChecked()}

    def trim_range(self) -> tuple[float, float] | None:
        start = parse_timestamp(self.trim_start.text())
        end = parse_timestamp(self.trim_end.text())
        if end is None:
            return None
        return (start or 0.0, end)

    # ------------------------------------------------------------ internals

    def _validate_and_accept(self) -> None:
        try:
            trim = self.trim_range()
        except ValueError:
            self._trim_error.setText("Clip times must look like 90, 1:30, or 1:02:03.")
            self._trim_error.show()
            return
        if trim is not None and trim[1] <= trim[0]:
            self._trim_error.setText("Clip end must be after the start.")
            self._trim_error.show()
            return
        self.accept()

    def _set_thumbnail(self, data: bytes) -> None:
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self._thumbnail.setPixmap(
                pixmap.scaled(
                    self._thumbnail.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def done(self, result: int) -> None:
        if self._fetcher is not None and self._fetcher.isRunning():
            self._fetcher.wait(500)
        super().done(result)
