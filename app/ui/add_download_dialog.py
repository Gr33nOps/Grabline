"""The Download Info dialog: a fast, IDM-style confirmation shown when a
download starts from the browser. It carries the name, category, save location
and - for a video URL - a quality choice, with Start / Download Later / Cancel.
It opens instantly (no analysis, generic quality tiers that resolve at download
time) so it feels as quick as clicking Download in IDM.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui import chrome, components, design

#: Auto-sort categories (mirrors app/core/categories.py) offered in the picker.
CATEGORIES = ["Video", "Music", "Images", "Documents", "Archives", "Programs", "Games", "Torrents"]
#: Generic quality choices for a video URL - resolved at download time, so the
#: dialog needs no analysis to show them (mirrors the app's quality tiers).
VIDEO_QUALITIES = ["Best", "1080p", "720p", "480p", "MP3", "M4A", "FLAC"]


class AddDownloadDialog(chrome.Dialog):
    def __init__(
        self,
        url: str,
        *,
        suggested_name: str,
        category: str,
        download_dir: str,
        with_quality: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Download")
        self.setMinimumWidth(540)
        self._base_dir = download_dir
        self._outcome: str | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(
            components.role_label("Download File Info", "strong", size=design.FONT["h1"], bold=True)
        )

        form = QFormLayout()
        self._name = QLineEdit(suggested_name)
        form.addRow("Name", self._name)

        url_label = components.role_label(url, "muted")
        url_label.setWordWrap(True)
        form.addRow("URL", url_label)

        self._category = QComboBox()
        self._category.addItems(CATEGORIES)
        if category in CATEGORIES:
            self._category.setCurrentText(category)
        self._category.currentTextChanged.connect(self._category_changed)
        form.addRow("Category", self._category)

        self._directory = QLineEdit(str(Path(download_dir) / self._category.currentText()))
        self._dir_edited = False
        self._directory.textEdited.connect(lambda _t: setattr(self, "_dir_edited", True))
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse)
        save_row = QHBoxLayout()
        save_row.setContentsMargins(0, 0, 0, 0)
        save_row.addWidget(self._directory, 1)
        save_row.addWidget(browse)
        save_widget = QWidget()
        save_widget.setLayout(save_row)
        form.addRow("Save to", save_widget)

        self._quality: QComboBox | None = None
        if with_quality:
            self._quality = QComboBox()
            self._quality.addItems(VIDEO_QUALITIES)
            form.addRow("Quality", self._quality)
        layout.addLayout(form)

        self._dont_ask = QCheckBox("Start downloads immediately from now on (change in Settings)")
        layout.addWidget(self._dont_ask)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        later = QPushButton("Download Later")
        later.clicked.connect(self._later)
        start = components.accent_button("Start Download")
        start.setDefault(True)
        start.clicked.connect(self._start)
        for button in (cancel, later, start):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        components.cap_field_widths(self, width=380)

    # ------------------------------------------------------------ internals

    def _category_changed(self, category: str) -> None:
        # Follow the category with the save folder until the user edits it.
        if not self._dir_edited:
            self._directory.setText(str(Path(self._base_dir) / category))

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Save to", self._directory.text())
        if chosen:
            self._directory.setText(chosen)
            self._dir_edited = True

    def _start(self) -> None:
        self._outcome = "start"
        self.accept()

    def _later(self) -> None:
        self._outcome = "later"
        self.accept()

    # -------------------------------------------------------------- result

    def outcome(self) -> str | None:
        """ "start", "later", or None when cancelled."""
        return self._outcome

    def chosen_name(self) -> str:
        return self._name.text().strip()

    def chosen_category(self) -> str:
        return self._category.currentText()

    def chosen_directory(self) -> str:
        return self._directory.text().strip()

    def chosen_quality(self) -> str | None:
        return self._quality.currentText() if self._quality is not None else None

    def dont_ask_again(self) -> bool:
        return self._dont_ask.isChecked()
