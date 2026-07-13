"""Settings dialog: download folder, categories (F0.6), clipboard watcher
(F0.5), browser session (F0.8, with its honest consent line), concurrency,
and FFmpeg install/status (S5).
"""

from __future__ import annotations

from PySide6.QtCore import QThread, QTime, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from app.core import launcher
from app.core.errors import DownloadError
from app.core.ffmpeg import ensure_ffmpeg, find_ffmpeg
from app.core.settings import SESSION_BROWSERS, Settings
from app.ui.format import human_bytes


class _FfmpegInstaller(QThread):
    progressed = Signal(int, object)  # received bytes, total or None
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, proxy: str | None = None) -> None:
        super().__init__()
        self._proxy = proxy

    def run(self) -> None:
        try:
            path = ensure_ffmpeg(progress=self.progressed.emit, proxy=self._proxy)
            self.succeeded.emit(str(path))
        except DownloadError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(f"unexpected error: {exc}")


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Grabline - Settings")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # ---- General -------------------------------------------------------
        general_form = self._add_form_tab(tabs, "General")
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(str(settings.download_dir))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse)
        general_form.addRow("Download folder:", folder_row)
        self.categories_check = QCheckBox("Sort into Video / Music / Images / Documents / Archives")
        self.categories_check.setChecked(settings.categories_enabled)
        general_form.addRow("", self.categories_check)
        self.theme_combo = QComboBox()
        for label, value in (("Match system", "system"), ("Light", "light"), ("Dark", "dark")):
            self.theme_combo.addItem(label, value)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(settings.theme)))
        general_form.addRow("Theme:", self.theme_combo)
        self.proxy_edit = QLineEdit(settings.proxy or "")
        self.proxy_edit.setPlaceholderText(
            "http://host:port or socks5://host:port (blank = direct)"
        )
        general_form.addRow("Proxy:", self.proxy_edit)
        self.clipboard_check = QCheckBox("Offer to download URLs copied to the clipboard")
        self.clipboard_check.setChecked(settings.clipboard_watcher)
        general_form.addRow("", self.clipboard_check)
        self.autostart_check = QCheckBox("Start Grabline when I log in (minimized to the tray)")
        self.autostart_check.setChecked(launcher.autostart_enabled())
        general_form.addRow("", self.autostart_check)
        self.updates_check = QCheckBox("Check for Grabline updates on startup")
        self.updates_check.setChecked(settings.check_updates)
        general_form.addRow("", self.updates_check)

        # ---- Downloads -----------------------------------------------------
        dl_form = self._add_form_tab(tabs, "Downloads")
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 10)
        self.concurrent_spin.setValue(settings.max_concurrent)
        dl_form.addRow("Simultaneous downloads:", self.concurrent_spin)
        self.connections_spin = QSpinBox()
        self.connections_spin.setRange(1, 128)
        self.connections_spin.setValue(settings.connections)
        self.connections_spin.setToolTip(
            "8-16 saturates most connections. Beyond ~32 many servers throttle "
            "or ban the extra sockets - more is not always faster."
        )
        dl_form.addRow("Connections per download:", self.connections_spin)
        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(0, 1_000_000)
        self.speed_spin.setSingleStep(256)
        self.speed_spin.setSuffix(" KB/s")
        self.speed_spin.setSpecialValueText("Unlimited")
        self.speed_spin.setValue(settings.speed_limit_kbps)
        dl_form.addRow("Speed limit:", self.speed_spin)
        schedule_row = QHBoxLayout()
        self.schedule_check = QCheckBox("Full speed between")
        self.schedule_check.setChecked(settings.speed_schedule_enabled)
        self.full_from = QTimeEdit(QTime.fromString(settings.speed_full_from, "HH:mm"))
        self.full_from.setDisplayFormat("HH:mm")
        self.full_to = QTimeEdit(QTime.fromString(settings.speed_full_to, "HH:mm"))
        self.full_to.setDisplayFormat("HH:mm")
        schedule_row.addWidget(self.schedule_check)
        schedule_row.addWidget(self.full_from)
        schedule_row.addWidget(QLabel("and"))
        schedule_row.addWidget(self.full_to)
        schedule_row.addStretch(1)
        dl_form.addRow("Speed schedule:", schedule_row)
        window_row = QHBoxLayout()
        self.download_schedule_check = QCheckBox("Only download between")
        self.download_schedule_check.setChecked(settings.download_schedule_enabled)
        self.download_start = QTimeEdit(QTime.fromString(settings.download_start, "HH:mm"))
        self.download_start.setDisplayFormat("HH:mm")
        self.download_stop = QTimeEdit(QTime.fromString(settings.download_stop, "HH:mm"))
        self.download_stop.setDisplayFormat("HH:mm")
        window_row.addWidget(self.download_schedule_check)
        window_row.addWidget(self.download_start)
        window_row.addWidget(QLabel("and"))
        window_row.addWidget(self.download_stop)
        window_row.addStretch(1)
        dl_form.addRow("Download times:", window_row)
        retry_row = QHBoxLayout()
        self.retry_check = QCheckBox("Auto-retry failed downloads, up to")
        self.retry_check.setChecked(settings.auto_retry)
        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(0, 99)
        self.retry_spin.setValue(settings.auto_retry_max)
        self.retry_spin.setSuffix(" times")
        self.retry_spin.setSpecialValueText("Forever")
        self.retry_spin.setToolTip(
            "Forever keeps retrying with capped backoff - downloads survive "
            "internet drops, VPN reconnects, and router reboots on their own."
        )
        retry_row.addWidget(self.retry_check)
        retry_row.addWidget(self.retry_spin)
        retry_row.addStretch(1)
        dl_form.addRow("Reconnect:", retry_row)

        # ---- When finished -------------------------------------------------
        finish_form = self._add_form_tab(tabs, "When finished")
        self.notify_check = QCheckBox("Show a notification when a download completes")
        self.notify_check.setChecked(settings.notify_on_complete)
        finish_form.addRow("", self.notify_check)
        self.open_folder_check = QCheckBox("Open the folder when a download completes")
        self.open_folder_check.setChecked(settings.auto_open_folder)
        finish_form.addRow("", self.open_folder_check)
        self.extract_check = QCheckBox("Extract .zip/.tar archives automatically")
        self.extract_check.setChecked(settings.auto_extract)
        finish_form.addRow("", self.extract_check)
        self.after_combo = QComboBox()
        for label, value in (
            ("Do nothing", "nothing"),
            ("Quit Grabline", "quit"),
            ("Sleep the computer", "sleep"),
            ("Shut down the computer", "shutdown"),
        ):
            self.after_combo.addItem(label, value)
        self.after_combo.setCurrentIndex(
            max(0, self.after_combo.findData(settings.after_queue_action))
        )
        finish_form.addRow("When the queue empties:", self.after_combo)

        # ---- Browser & YouTube ---------------------------------------------
        browser_tab = QWidget()
        browser_layout = QVBoxLayout(browser_tab)
        session = QGroupBox("Browser session (advanced)")
        session_layout = QVBoxLayout(session)
        self.session_check = QCheckBox("Let Grabline use my browser's login session")
        self.session_check.setChecked(settings.use_browser_session)
        session_layout.addWidget(self.session_check)
        browser_row = QHBoxLayout()
        browser_row.addWidget(QLabel("Browser:"))
        self.browser_combo = QComboBox()
        for browser in SESSION_BROWSERS:
            self.browser_combo.addItem(browser.capitalize(), browser)
        self.browser_combo.setCurrentIndex(SESSION_BROWSERS.index(settings.session_browser))
        browser_row.addWidget(self.browser_combo, 1)
        session_layout.addLayout(browser_row)
        consent = QLabel(
            "Grabline uses your browser login automatically only when a video "
            "asks for it (age- or login-restricted); this switch just forces it "
            "on. Your real login is used only for your own content, read per "
            "download, kept in memory, never stored or sent anywhere. The first "
            "restricted download fetches a small JavaScript runtime (Deno, "
            "~40 MB, verified) that YouTube now requires - unless you already "
            "have Node or another runtime installed."
        )
        consent.setWordWrap(True)
        consent.setStyleSheet("color: gray; font-size: 11px;")
        session_layout.addWidget(consent)
        browser_layout.addWidget(session)

        pairing = QGroupBox("Browser extension")
        pairing_layout = QHBoxLayout(pairing)
        pairing_label = QLabel(
            "Pair Grabline with your browsers so the Grabline Connect "
            "extension can hand downloads over."
        )
        pairing_label.setWordWrap(True)
        pairing_layout.addWidget(pairing_label, 1)
        pair_button = QPushButton("Pair browsers")
        pair_button.clicked.connect(self._pair_browsers)
        pairing_layout.addWidget(pair_button)
        browser_layout.addWidget(pairing)
        browser_layout.addStretch(1)
        tabs.addTab(browser_tab, "Browser && YouTube")

        # ---- Tools ---------------------------------------------------------
        tools_tab = QWidget()
        tools_layout = QVBoxLayout(tools_tab)
        ffmpeg_group = QGroupBox("FFmpeg (needed for MP3, merging, and streams)")
        ffmpeg_layout = QHBoxLayout(ffmpeg_group)
        self.ffmpeg_status = QLabel()
        ffmpeg_layout.addWidget(self.ffmpeg_status, 1)
        self.ffmpeg_button = QPushButton()
        self.ffmpeg_button.clicked.connect(self._install_ffmpeg)
        ffmpeg_layout.addWidget(self.ffmpeg_button)
        self._refresh_ffmpeg_status()
        tools_layout.addWidget(ffmpeg_group)
        tools_layout.addStretch(1)
        tabs.addTab(tools_tab, "Tools")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._installer: _FfmpegInstaller | None = None

    @staticmethod
    def _add_form_tab(tabs: QTabWidget, title: str) -> QFormLayout:
        """Add a tab whose body is a top-aligned form, and return that form."""
        page = QWidget()
        form = QFormLayout(page)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        tabs.addTab(page, title)
        return form

    def _browse_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose download folder", self.folder_edit.text()
        )
        if chosen:
            self.folder_edit.setText(chosen)

    def _pair_browsers(self) -> None:
        from app.native_host.install import install as install_host

        try:
            written = install_host()
        except OSError as exc:
            QMessageBox.warning(self, "Grabline", f"Pairing failed: {exc}")
            return
        QMessageBox.information(
            self,
            "Grabline",
            f"Registered with {len(written)} browser location(s).\n\n"
            "Now install (or reload) the Grabline Connect extension in your "
            "browser - its toolbar popup should say “connected”.",
        )

    def _refresh_ffmpeg_status(self) -> None:
        path = find_ffmpeg(self.settings)
        if path:
            self.ffmpeg_status.setText(f"Found: {path}")
            self.ffmpeg_button.setText("Reinstall")
        else:
            self.ffmpeg_status.setText("Not found")
            self.ffmpeg_button.setText("Install FFmpeg")

    def _install_ffmpeg(self) -> None:
        progress = QProgressDialog("Downloading FFmpeg…", "Hide", 0, 0, self)
        progress.setWindowTitle("Grabline")
        progress.setMinimumDuration(0)
        installer = _FfmpegInstaller(self.settings.proxy)
        self._installer = installer

        def on_progress(received: int, total: object) -> None:
            if isinstance(total, int) and total > 0:
                progress.setMaximum(100)
                progress.setValue(int(received / total * 100))
            progress.setLabelText(f"Downloading FFmpeg… {human_bytes(received)}")

        def on_success(path: str) -> None:
            progress.close()
            self._refresh_ffmpeg_status()
            QMessageBox.information(self, "Grabline", f"FFmpeg installed and verified:\n{path}")

        def on_failure(message: str) -> None:
            progress.close()
            self._refresh_ffmpeg_status()
            QMessageBox.warning(self, "Grabline", message)

        installer.progressed.connect(on_progress)
        installer.succeeded.connect(on_success)
        installer.failed.connect(on_failure)
        installer.start()

    def _save(self) -> None:
        self.settings.download_dir = self.folder_edit.text().strip() or str(
            self.settings.download_dir
        )
        self.settings.categories_enabled = self.categories_check.isChecked()
        self.settings.clipboard_watcher = self.clipboard_check.isChecked()
        self.settings.use_browser_session = self.session_check.isChecked()
        self.settings.session_browser = self.browser_combo.currentData()
        self.settings.max_concurrent = self.concurrent_spin.value()
        self.settings.connections = self.connections_spin.value()
        self.settings.speed_limit_kbps = self.speed_spin.value()
        self.settings.speed_schedule_enabled = self.schedule_check.isChecked()
        self.settings.speed_full_from = self.full_from.time().toString("HH:mm")
        self.settings.speed_full_to = self.full_to.time().toString("HH:mm")
        self.settings.download_schedule_enabled = self.download_schedule_check.isChecked()
        self.settings.download_start = self.download_start.time().toString("HH:mm")
        self.settings.download_stop = self.download_stop.time().toString("HH:mm")
        self.settings.check_updates = self.updates_check.isChecked()
        self.settings.auto_retry = self.retry_check.isChecked()
        self.settings.auto_retry_max = self.retry_spin.value()
        self.settings.theme = self.theme_combo.currentData()
        self.settings.proxy = self.proxy_edit.text().strip() or None
        self.settings.notify_on_complete = self.notify_check.isChecked()
        self.settings.auto_open_folder = self.open_folder_check.isChecked()
        self.settings.auto_extract = self.extract_check.isChecked()
        self.settings.after_queue_action = self.after_combo.currentData()
        try:
            # The autostart file/registry entry IS the setting - no DB copy
            # that could drift from what the OS will actually do at login.
            launcher.set_autostart(self.autostart_check.isChecked())
        except OSError as exc:
            QMessageBox.warning(self, "Grabline", f"Could not update autostart: {exc}")
        self.accept()

    def done(self, result: int) -> None:
        if self._installer is not None and self._installer.isRunning():
            self._installer.wait(1000)
        super().done(result)
