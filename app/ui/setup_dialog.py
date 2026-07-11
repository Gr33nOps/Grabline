"""First-run Browser Setup wizard: pair the native host, put the extension at
a stable path, and give each browser the shortest free install path."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core import browser_setup
from app.native_host import install as host_install


class SetupDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Grabline - Browser Setup")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Two quick steps connect Grabline to your browser. Everything here "
            "is free; Chrome and Brave need one manual 'Load unpacked' until the "
            "extension is on the Chrome Web Store."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # Step 1 - pair the native host.
        layout.addWidget(self._heading("1. Pair Grabline with your browsers"))
        pair_row = QHBoxLayout()
        self._pair_status = QLabel("Not paired yet.")
        pair_button = QPushButton("Pair now")
        pair_button.clicked.connect(self._pair)
        pair_row.addWidget(self._pair_status, 1)
        pair_row.addWidget(pair_button)
        layout.addLayout(pair_row)

        # Step 2 - the extension.
        layout.addWidget(self._heading("2. Add the extension"))

        # One-click path: open the store listing in the user's default browser,
        # where they click a single "Add". No app can install an extension
        # itself - the browser only accepts one from its own store. Shown only
        # when that browser has a live store listing; otherwise the manual
        # "Load unpacked" path below applies.
        browser = browser_setup.default_browser()
        store_url = browser_setup.extension_install_url()
        if browser and store_url:
            add_button = QPushButton(f"➜  Add Grabline to {browser[1]}")
            add_button.setStyleSheet("font-weight: 600; padding: 6px;")
            add_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(store_url)))
            layout.addWidget(add_button)
            hint = QLabel(
                f"Opens the store page in {browser[1]} - click <b>Add</b> there. "
                "Or use the manual folder below for any browser."
            )
            hint.setWordWrap(True)
            hint.setStyleSheet("color: gray; font-size: 11px;")
            layout.addWidget(hint)

        folder_row = QHBoxLayout()
        self._folder_edit = QLineEdit()
        self._folder_edit.setReadOnly(True)
        open_folder = QPushButton("Open folder")
        open_folder.clicked.connect(self._open_folder)
        copy_path = QPushButton("Copy path")
        copy_path.clicked.connect(self._copy_path)
        folder_row.addWidget(self._folder_edit, 1)
        folder_row.addWidget(open_folder)
        folder_row.addWidget(copy_path)
        layout.addLayout(folder_row)

        chrome_row = QHBoxLayout()
        chrome_hint = QLabel(
            "Chrome / Edge / Brave: open the extensions page, enable Developer "
            "mode, click Load unpacked, and choose the folder above."
        )
        chrome_hint.setWordWrap(True)
        copy_url = QPushButton("Copy chrome://extensions")
        copy_url.clicked.connect(lambda: QGuiApplication.clipboard().setText("chrome://extensions"))
        chrome_row.addWidget(chrome_hint, 1)
        chrome_row.addWidget(copy_url)
        layout.addLayout(chrome_row)

        firefox_hint = QLabel(
            "Firefox: about:debugging → This Firefox → Load Temporary Add-on → "
            "pick manifest.json in that folder (permanent install comes with the "
            "free add-on signing)."
        )
        firefox_hint.setWordWrap(True)
        firefox_hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(firefox_hint)

        # Detected browsers, for reassurance.
        detected = [b.name for b in browser_setup.detect_browsers() if b.installed]
        if detected:
            found = QLabel("Detected: " + ", ".join(detected))
            found.setStyleSheet("color: gray; font-size: 11px;")
            layout.addWidget(found)

        # Verify.
        verify_row = QHBoxLayout()
        self._verify_status = QLabel("")
        verify_button = QPushButton("Check connection")
        verify_button.clicked.connect(self._verify)
        verify_row.addWidget(self._verify_status, 1)
        verify_row.addWidget(verify_button)
        layout.addLayout(verify_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._prepare_extension()

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight: 600; margin-top: 8px;")
        return label

    def _prepare_extension(self) -> None:
        try:
            path = browser_setup.install_extension_files()
            self._folder_edit.setText(str(path))
        except (OSError, FileNotFoundError) as exc:
            self._folder_edit.setText(f"(could not prepare extension: {exc})")

    def _pair(self) -> None:
        try:
            written = host_install.install()
        except OSError as exc:
            self._pair_status.setText(f"Pairing failed: {exc}")
            return
        self._pair_status.setText(f"Paired with {len(written)} browser location(s).")

    def _open_folder(self) -> None:
        path = self._folder_edit.text()
        if path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _copy_path(self) -> None:
        QGuiApplication.clipboard().setText(self._folder_edit.text())

    def _verify(self) -> None:
        healthy, lines = host_install.check()
        if healthy:
            self._verify_status.setText("Connected - the app and browser can talk.")
        else:
            fail = next((line for line in lines if line.startswith("FAIL")), "not paired yet")
            self._verify_status.setText(fail.removeprefix("FAIL ").strip() or "not paired yet")
