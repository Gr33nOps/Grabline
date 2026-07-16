"""Settings: every persisted option, organized into the sidebar sections the
embedded Settings page shows (General → About).

This dialog owns the fields and the save logic; it is normally never shown -
SettingsView lifts its tab pages into the embedded page. ``apply()`` persists
every field and is shared by both paths.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTime, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.core import launcher, paths
from app.core.errors import DownloadError
from app.core.ffmpeg import ensure_ffmpeg, find_ffmpeg
from app.core.settings import SESSION_BROWSERS, Settings
from app.ui import components
from app.ui.format import human_bytes

_PROJECT_URL = "https://github.com/Gr33nOps/Grabline"


def _note(text: str) -> QLabel:
    """A muted, wrapping explanation label (theme-following)."""
    label = components.role_label(text, "muted")
    label.setWordWrap(True)
    return label


def _parse_rename_rules(text: str) -> list[tuple[str, str]]:
    """'find -> replace' per line; a line without '->' deletes the text."""
    rules: list[tuple[str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        find, _, replace = line.partition("->")
        if find.strip():
            rules.append((find.strip(), replace.strip()))
    return rules


def _parse_host_limits(text: str) -> dict[str, int]:
    """'host = KB/s' per line -> {host: kbps}; bad lines are dropped."""
    limits: dict[str, int] = {}
    for line in text.splitlines():
        host, _, value = line.partition("=")
        host = host.strip().lower()
        try:
            kbps = int(value.strip())
        except ValueError:
            continue
        if host and kbps > 0:
            limits[host] = kbps
    return limits


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
        self.tabs = tabs  # exposed so SettingsView can embed the pages
        layout.addWidget(tabs)

        # ---- General ---------------------------------------------------------
        general_form = self._add_form_tab(tabs, "General")
        self.autostart_check = QCheckBox("Start Grabline when I log in (minimized to the tray)")
        self.autostart_check.setChecked(launcher.autostart_enabled())
        general_form.addRow("", self.autostart_check)
        self.clipboard_check = QCheckBox("Offer to download URLs copied to the clipboard")
        self.clipboard_check.setChecked(settings.clipboard_watcher)
        general_form.addRow("", self.clipboard_check)
        self.updates_check = QCheckBox("Check for Grabline updates on startup")
        self.updates_check.setChecked(settings.check_updates)
        general_form.addRow("", self.updates_check)

        # ---- Downloads -------------------------------------------------------
        downloads_form = self._add_form_tab(tabs, "Downloads")
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(str(settings.download_dir))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse)
        downloads_form.addRow("Download folder:", folder_row)
        self.categories_check = QCheckBox(
            "Sort into Video / Music / Images / Documents / Archives / Programs / Games / Torrents"
        )
        self.categories_check.setChecked(settings.categories_enabled)
        downloads_form.addRow("", self.categories_check)
        downloads_form.addRow(
            _note(
                "Adding a URL that is already in the list asks before downloading "
                "it again, and completed files always stay on disk when a download "
                "is removed from the list."
            )
        )

        # ---- Download Engine -------------------------------------------------
        engine_form = self._add_form_tab(tabs, "Download Engine")
        self.connections_spin = QSpinBox()
        self.connections_spin.setRange(1, 128)
        self.connections_spin.setValue(settings.connections)
        self.connections_spin.setToolTip(
            "8-16 saturates most connections. Beyond ~32 many servers throttle "
            "or ban the extra sockets - more is not always faster."
        )
        engine_form.addRow("Connections per download:", self.connections_spin)
        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(0, 1_000_000)
        self.speed_spin.setSingleStep(256)
        self.speed_spin.setSuffix(" KB/s")
        self.speed_spin.setSpecialValueText("Unlimited")
        self.speed_spin.setValue(settings.speed_limit_kbps)
        engine_form.addRow("Speed limit:", self.speed_spin)
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
        engine_form.addRow("Speed schedule:", schedule_row)
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
        engine_form.addRow("Reconnect:", retry_row)
        engine_form.addRow(
            _note(
                "Right-click a download for per-download overrides: its own "
                "speed limit, connection count, and mirrors."
            )
        )

        # ---- Browser Integration ---------------------------------------------
        browser_tab = QWidget()
        browser_layout = QVBoxLayout(browser_tab)
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
        session_layout.addWidget(
            _note(
                "Grabline uses your browser login automatically only when a video "
                "asks for it (age- or login-restricted); this switch just forces it "
                "on. Your real login is used only for your own content, read per "
                "download, kept in memory, never stored or sent anywhere."
            )
        )
        browser_layout.addWidget(session)
        browser_layout.addStretch(1)
        tabs.addTab(browser_tab, "Browser Integration")

        # ---- Video Downloader ------------------------------------------------
        video_tab = QWidget()
        video_layout = QVBoxLayout(video_tab)
        ffmpeg_group = QGroupBox("FFmpeg (needed for MP3, merging, and streams)")
        ffmpeg_layout = QHBoxLayout(ffmpeg_group)
        self.ffmpeg_status = QLabel()
        ffmpeg_layout.addWidget(self.ffmpeg_status, 1)
        self.ffmpeg_button = QPushButton()
        self.ffmpeg_button.clicked.connect(self._install_ffmpeg)
        ffmpeg_layout.addWidget(self.ffmpeg_button)
        self._refresh_ffmpeg_status()
        video_layout.addWidget(ffmpeg_group)
        playlist_form = QFormLayout()
        self.playlist_cap_spin = QSpinBox()
        self.playlist_cap_spin.setRange(1, 500)
        self.playlist_cap_spin.setValue(settings.playlist_batch_cap)
        self.playlist_cap_spin.setToolTip(
            "Opening a playlist preselects this many entries; you can always "
            "tick more or fewer before queueing."
        )
        playlist_form.addRow("Preselect playlist entries:", self.playlist_cap_spin)
        video_layout.addLayout(playlist_form)
        video_layout.addWidget(_note(self._js_runtime_text()))
        video_layout.addWidget(
            _note(
                "Per-video choices - quality, MP3/M4A/FLAC, subtitles, clip "
                "trimming, chapters, SponsorBlock - are offered in the panel "
                "when you add a video."
            )
        )
        video_layout.addStretch(1)
        tabs.addTab(video_tab, "Video Downloader")

        # ---- Torrent ----------------------------------------------------------
        torrent_form = self._add_form_tab(tabs, "Torrent")
        self.torrent_port_spin = QSpinBox()
        self.torrent_port_spin.setRange(1024, 65535)
        self.torrent_port_spin.setValue(settings.torrent_port)
        torrent_form.addRow("Listen port:", self.torrent_port_spin)
        self.dht_check = QCheckBox("DHT (find peers without trackers; needed for magnets)")
        self.dht_check.setChecked(settings.torrent_dht)
        torrent_form.addRow("", self.dht_check)
        self.upnp_check = QCheckBox("UPnP port mapping")
        self.upnp_check.setChecked(settings.torrent_upnp)
        torrent_form.addRow("", self.upnp_check)
        self.natpmp_check = QCheckBox("NAT-PMP port mapping")
        self.natpmp_check.setChecked(settings.torrent_natpmp)
        torrent_form.addRow("", self.natpmp_check)
        seed_row = QHBoxLayout()
        self.seed_check = QCheckBox("Seed after downloading, up to ratio")
        self.seed_check.setChecked(settings.torrent_seed)
        self.ratio_spin = QDoubleSpinBox()
        self.ratio_spin.setRange(0.0, 100.0)
        self.ratio_spin.setSingleStep(0.5)
        self.ratio_spin.setSpecialValueText("Forever")
        self.ratio_spin.setValue(settings.torrent_ratio_limit)
        seed_row.addWidget(self.seed_check)
        seed_row.addWidget(self.ratio_spin)
        seed_row.addStretch(1)
        torrent_form.addRow("Seeding:", seed_row)
        self.upload_spin = QSpinBox()
        self.upload_spin.setRange(0, 1_000_000)
        self.upload_spin.setSingleStep(64)
        self.upload_spin.setSuffix(" KB/s")
        self.upload_spin.setSpecialValueText("Unlimited")
        self.upload_spin.setValue(settings.torrent_upload_kbps)
        torrent_form.addRow("Upload limit:", self.upload_spin)
        self.sequential_check = QCheckBox("Sequential download by default (stream-friendly)")
        self.sequential_check.setChecked(settings.torrent_sequential)
        torrent_form.addRow("", self.sequential_check)
        torrent_dir_row = QHBoxLayout()
        self.torrent_dir_edit = QLineEdit(str(settings.torrent_dir) if settings.torrent_dir else "")
        self.torrent_dir_edit.setPlaceholderText("blank = the download folder")
        torrent_browse = QPushButton("Browse…")
        torrent_browse.clicked.connect(self._browse_torrent_folder)
        torrent_dir_row.addWidget(self.torrent_dir_edit, 1)
        torrent_dir_row.addWidget(torrent_browse)
        torrent_form.addRow("Save torrents to:", torrent_dir_row)
        self.search_url_edit = QLineEdit(settings.torrent_search_url)
        self.search_url_edit.setPlaceholderText("https://example.com/search?q=%s")
        self.search_url_edit.setToolTip(
            "Search Torrents… opens this in your browser with %s replaced by the query."
        )
        torrent_form.addRow("Search URL:", self.search_url_edit)
        self.rss_edit = QPlainTextEdit()
        self.rss_edit.setPlainText("\n".join(settings.rss_feeds))
        self.rss_edit.setPlaceholderText("feed URL, or:  feed URL | filter text\none per line")
        self.rss_edit.setFixedHeight(72)
        self.rss_edit.setToolTip(
            "Checked periodically; new items whose link is a torrent/magnet "
            "(and whose title contains the filter, if given) are queued "
            "automatically."
        )
        torrent_form.addRow("RSS feeds:", self.rss_edit)
        self.rss_interval_spin = QSpinBox()
        self.rss_interval_spin.setRange(5, 1440)
        self.rss_interval_spin.setSuffix(" min")
        self.rss_interval_spin.setValue(settings.rss_interval_minutes)
        torrent_form.addRow("Check feeds every:", self.rss_interval_spin)

        # ---- Cloud Downloads ---------------------------------------------------
        cloud_tab = QWidget()
        cloud_layout = QVBoxLayout(cloud_tab)
        cloud_layout.addWidget(
            _note(
                "Download from cloud storage and file servers. Paste an sftp://, "
                "ftp://, ftps://, scp://, s3:// or webdav:// address (Add Cloud "
                "Download), or a public Google Drive / Dropbox / OneDrive / "
                "Nextcloud share link into Add URL - share links download at full "
                "speed with no account needed."
            )
        )
        accounts_row = QHBoxLayout()
        manage_accounts = QPushButton("Manage saved logins…")
        manage_accounts.clicked.connect(self._manage_cloud_accounts)
        accounts_row.addWidget(manage_accounts)
        accounts_row.addStretch(1)
        cloud_layout.addLayout(accounts_row)
        cloud_layout.addWidget(
            _note(
                "Passwords and key passphrases are stored in your system keychain. "
                "Several accounts per host are supported; the right one is chosen "
                "automatically by the address you download."
            )
        )
        cloud_layout.addWidget(
            _note(
                "Not supported: Mega and Proton Drive (end-to-end encrypted) and "
                "iCloud (no public API)."
            )
        )
        cloud_layout.addStretch(1)
        tabs.addTab(cloud_tab, "Cloud Downloads")

        # ---- Archive Manager ---------------------------------------------------
        archive_form = self._add_form_tab(tabs, "Archive Manager")
        self.extract_check = QCheckBox(
            "Extract archives automatically (zip/tar/gz/bz2/xz; rar/7z with 7z installed)"
        )
        self.extract_check.setChecked(settings.auto_extract)
        archive_form.addRow("", self.extract_check)
        self.scan_check = QCheckBox("Virus-scan archives before extracting")
        self.scan_check.setChecked(settings.scan_before_extract)
        self.scan_check.setToolTip(
            "Uses a scanner already on this machine - Windows Defender or "
            "ClamAV. If none is installed, extraction stops with a message "
            "instead of pretending to scan."
        )
        archive_form.addRow("", self.scan_check)
        self.passwords_edit = QPlainTextEdit()
        self.passwords_edit.setPlainText("\n".join(settings.archive_passwords))
        self.passwords_edit.setPlaceholderText("one password per line")
        self.passwords_edit.setFixedHeight(72)
        self.passwords_edit.setToolTip(
            "Tried in order when an archive is encrypted. Passwords you type "
            "into the extract prompt are remembered here too. Stored locally, "
            "unencrypted - same trust level as the downloaded files."
        )
        archive_form.addRow("Archive passwords:", self.passwords_edit)
        archive_form.addRow(
            _note(
                "Right-click a finished archive for Preview archive… (extract "
                "selected files) and Extract here."
            )
        )

        # ---- File Management ---------------------------------------------------
        files_form = self._add_form_tab(tabs, "File Management")
        self.favorites_edit = QPlainTextEdit()
        self.favorites_edit.setPlainText("\n".join(settings.favorite_folders))
        self.favorites_edit.setPlaceholderText("one folder per line, e.g. /home/me/Movies")
        self.favorites_edit.setFixedHeight(72)
        self.favorites_edit.setToolTip(
            "Quick destinations shown under 'Move to' when you right-click a finished download."
        )
        files_form.addRow("Favorite folders:", self.favorites_edit)
        self.rename_edit = QPlainTextEdit()
        self.rename_edit.setPlainText(
            "\n".join(f"{find} -> {replace}" for find, replace in settings.rename_rules)
        )
        self.rename_edit.setPlaceholderText("find -> replace   (one rule per line)")
        self.rename_edit.setFixedHeight(72)
        self.rename_edit.setToolTip(
            "Applied in order to every new download's name (never the "
            "extension). Example:  [SPONSORED] ->\nleaves the rest of the "
            "name intact."
        )
        files_form.addRow("Rename rules:", self.rename_edit)
        files_form.addRow(
            _note(
                "Find Duplicate Files… (in the sidebar's More menu) hash-compares "
                "completed downloads and offers to delete the extra copies."
            )
        )

        # ---- Queue Manager -----------------------------------------------------
        queue_form = self._add_form_tab(tabs, "Queue Manager")
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 10)
        self.concurrent_spin.setValue(settings.max_concurrent)
        queue_form.addRow("Simultaneous downloads:", self.concurrent_spin)
        queue_form.addRow(
            _note(
                "This is the global limit. Named queues - each with its own "
                "downloads-at-once, schedule, category, and queue-after-queue "
                "dependencies - are managed on the Queue page in the sidebar."
            )
        )

        # ---- Scheduler ---------------------------------------------------------
        scheduler_form = self._add_form_tab(tabs, "Scheduler")
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
        scheduler_form.addRow("Download times:", window_row)
        days_row = QHBoxLayout()
        self.day_checks: list[QCheckBox] = []
        enabled_days = set(settings.download_days)
        for index, label in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
            check = QCheckBox(label)
            check.setChecked(index in enabled_days)
            self.day_checks.append(check)
            days_row.addWidget(check)
        days_row.addStretch(1)
        scheduler_form.addRow("Days:", days_row)
        self.battery_check = QCheckBox("Pause downloads while on battery")
        self.battery_check.setChecked(settings.pause_on_battery)
        scheduler_form.addRow("", self.battery_check)
        self.network_check = QCheckBox("Wait for internet - resume the moment it reconnects")
        self.network_check.setChecked(settings.wait_for_network)
        self.network_check.setToolTip(
            "Failed downloads always retry with backoff; this also holds new "
            "starts while offline and retries immediately on reconnect."
        )
        scheduler_form.addRow("", self.network_check)
        self.after_combo = QComboBox()
        for label, value in (
            ("Do nothing", "nothing"),
            ("Quit Grabline", "quit"),
            ("Sleep the computer", "sleep"),
            ("Hibernate the computer", "hibernate"),
            ("Shut down the computer", "shutdown"),
            ("Lock the computer", "lock"),
        ):
            self.after_combo.addItem(label, value)
        self.after_combo.setCurrentIndex(
            max(0, self.after_combo.findData(settings.after_queue_action))
        )
        scheduler_form.addRow("When the queue empties:", self.after_combo)
        scheduler_form.addRow(
            _note(
                "Right-click a download for one-off scheduling: Start at… a "
                "chosen time, or Start after… another download finishes."
            )
        )

        # ---- Network -----------------------------------------------------------
        net_tab = QWidget()
        net_layout = QVBoxLayout(net_tab)
        proxy_form = QFormLayout()
        self.proxy_edit = QLineEdit(settings.proxy or "")
        self.proxy_edit.setPlaceholderText(
            "http(s):// · socks5:// · socks4:// host:port  (blank = direct)"
        )
        self.proxy_edit.setToolTip(
            "HTTP, HTTPS, SOCKS5 and SOCKS4 are supported, with user:pass@ auth. "
            "The proxy applies to every download, including torrents."
        )
        proxy_form.addRow("Proxy:", self.proxy_edit)
        net_layout.addLayout(proxy_form)
        net_layout.addWidget(_note(self._vpn_status_text()))

        throttle_group = QGroupBox("Automatic throttle (polite mode)")
        throttle_layout = QFormLayout(throttle_group)
        self.auto_throttle_check = QCheckBox("Slow downloads when other apps are using the network")
        self.auto_throttle_check.setChecked(settings.auto_throttle)
        throttle_layout.addRow("", self.auto_throttle_check)
        self.throttle_limit_spin = QSpinBox()
        self.throttle_limit_spin.setRange(1, 1_000_000)
        self.throttle_limit_spin.setSuffix(" KB/s")
        self.throttle_limit_spin.setValue(settings.auto_throttle_kbps)
        throttle_layout.addRow("Slow down to:", self.throttle_limit_spin)
        self.throttle_threshold_spin = QSpinBox()
        self.throttle_threshold_spin.setRange(1, 1_000_000)
        self.throttle_threshold_spin.setSuffix(" KB/s")
        self.throttle_threshold_spin.setValue(settings.auto_throttle_threshold_kbps)
        self.throttle_threshold_spin.setToolTip(
            "How much other (non-Grabline) network traffic counts as 'busy'."
        )
        throttle_layout.addRow("When others use over:", self.throttle_threshold_spin)
        net_layout.addWidget(throttle_group)

        host_group = QGroupBox("Per-host speed limits")
        host_layout = QVBoxLayout(host_group)
        host_layout.addWidget(QLabel("One 'host = KB/s' per line, e.g.  cdn.example.com = 500"))
        self.host_limits_edit = QPlainTextEdit()
        self.host_limits_edit.setPlainText(
            "\n".join(f"{host} = {kbps}" for host, kbps in settings.host_limits.items())
        )
        self.host_limits_edit.setPlaceholderText("cdn.example.com = 500")
        self.host_limits_edit.setFixedHeight(90)
        host_layout.addWidget(self.host_limits_edit)
        net_layout.addWidget(host_group)
        net_layout.addStretch(1)
        tabs.addTab(net_tab, "Network")

        # ---- Security ----------------------------------------------------------
        security_form = self._add_form_tab(tabs, "Security")
        security_form.addRow(
            _note(
                "These checks only ever warn - a flagged file is kept and stays "
                "usable, and you decide. Antivirus false positives are common."
            )
        )
        self.scan_downloads_check = QCheckBox(
            "Security-check every finished download (local virus scan + VirusTotal if set)"
        )
        self.scan_downloads_check.setChecked(settings.scan_downloads)
        security_form.addRow("", self.scan_downloads_check)
        self.enforce_https_check = QCheckBox("Warn before downloading over unencrypted HTTP")
        self.enforce_https_check.setChecked(settings.enforce_https)
        security_form.addRow("", self.enforce_https_check)
        self.virustotal_edit = QLineEdit(settings.virustotal_key)
        self.virustotal_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.virustotal_edit.setPlaceholderText("your VirusTotal API key (optional)")
        self.virustotal_edit.setToolTip(
            "Only the file's SHA-256 hash is sent to VirusTotal, never the file "
            "itself. Get a free key at virustotal.com."
        )
        security_form.addRow("VirusTotal key:", self.virustotal_edit)
        self.safebrowsing_edit = QLineEdit(settings.safebrowsing_key)
        self.safebrowsing_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.safebrowsing_edit.setPlaceholderText("your Google Safe Browsing API key (optional)")
        self.safebrowsing_edit.setToolTip(
            "When set, a download's URL is checked against Google Safe Browsing "
            "before it starts. The URL is sent to Google, so this is opt-in."
        )
        security_form.addRow("Safe Browsing key:", self.safebrowsing_edit)
        security_form.addRow(
            _note(
                "TLS certificates are always validated - a download over HTTPS "
                "with a bad certificate fails on its own."
            )
        )

        # ---- Notifications -----------------------------------------------------
        notify_form = self._add_form_tab(tabs, "Notifications")
        self.notify_check = QCheckBox("Show a notification when a download completes")
        self.notify_check.setChecked(settings.notify_on_complete)
        notify_form.addRow("", self.notify_check)
        sound_row = QHBoxLayout()
        self.sound_check = QCheckBox("Play a sound")
        self.sound_check.setChecked(settings.sound_on_complete)
        self.sound_file_edit = QLineEdit(settings.sound_file)
        self.sound_file_edit.setPlaceholderText("blank = system sound")
        sound_browse = QPushButton("Browse…")
        sound_browse.clicked.connect(self._browse_sound)
        sound_row.addWidget(self.sound_check)
        sound_row.addWidget(self.sound_file_edit, 1)
        sound_row.addWidget(sound_browse)
        notify_form.addRow("On completion:", sound_row)
        self.open_folder_check = QCheckBox("Open the folder when a download completes")
        self.open_folder_check.setChecked(settings.auto_open_folder)
        notify_form.addRow("", self.open_folder_check)

        # ---- Statistics --------------------------------------------------------
        stats_tab = QWidget()
        stats_layout = QVBoxLayout(stats_tab)
        self.stats_label = QLabel()
        self._refresh_stats_label()
        stats_layout.addWidget(self.stats_label)
        stats_layout.addWidget(
            _note(
                "Live graphs and per-server / per-category breakdowns are on the "
                "Dashboard page in the sidebar. Statistics are stored locally and "
                "never sent anywhere."
            )
        )
        clear_row = QHBoxLayout()
        clear_stats = QPushButton("Clear statistics…")
        clear_stats.clicked.connect(self._clear_stats)
        clear_row.addWidget(clear_stats)
        clear_row.addStretch(1)
        stats_layout.addLayout(clear_row)
        stats_layout.addStretch(1)
        tabs.addTab(stats_tab, "Statistics")

        # ---- Appearance --------------------------------------------------------
        appearance_form = self._add_form_tab(tabs, "Appearance")
        self.theme_combo = QComboBox()
        for label, value in (("Match system", "system"), ("Light", "light"), ("Dark", "dark")):
            self.theme_combo.addItem(label, value)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(settings.theme)))
        appearance_form.addRow("Theme:", self.theme_combo)
        appearance_form.addRow(
            _note(
                "The sun/moon button at the bottom of the sidebar switches "
                "between light and dark instantly."
            )
        )

        # ---- Advanced ----------------------------------------------------------
        advanced_form = self._add_form_tab(tabs, "Advanced")
        self.script_edit = QLineEdit(settings.script_on_complete)
        self.script_edit.setPlaceholderText("e.g. /usr/bin/my-script --scan")
        self.script_edit.setToolTip(
            "Run after every finished download; the file's full path is "
            "appended as the last argument. Runs directly, never via a shell."
        )
        advanced_form.addRow("Run command:", self.script_edit)
        self.ffmpeg_override_edit = QLineEdit(settings.ffmpeg_path or "")
        self.ffmpeg_override_edit.setPlaceholderText("blank = found automatically")
        self.ffmpeg_override_edit.setToolTip(
            "A specific ffmpeg binary to use instead of the automatically found/installed one."
        )
        advanced_form.addRow("FFmpeg path override:", self.ffmpeg_override_edit)
        data_label = QLabel(str(paths.data_dir()))
        data_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        advanced_form.addRow("Data folder:", data_label)
        advanced_form.addRow(
            _note("Holds the download list, settings, and statistics (grabline.db).")
        )

        # ---- About -------------------------------------------------------------
        about_tab = QWidget()
        about_layout = QVBoxLayout(about_tab)
        head = QHBoxLayout()
        head.addWidget(components.app_logo(44))
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        name_label = components.role_label("Grabline", "strong")
        font = name_label.font()
        font.setPointSize(font.pointSize() + 5)
        font.setBold(True)
        name_label.setFont(font)
        title_box.addWidget(name_label)
        title_box.addWidget(components.role_label(f"Version {__version__}", "muted"))
        head.addSpacing(10)
        head.addLayout(title_box)
        head.addStretch(1)
        about_layout.addLayout(head)
        about_layout.addSpacing(6)
        about_layout.addWidget(
            _note(
                "A fast, open-source download manager. Free software under the "
                "AGPL-3.0 license. No telemetry - Grabline never phones home; "
                "the only network requests are the ones you ask for."
            )
        )
        links_row = QHBoxLayout()
        project_btn = QPushButton("Project page")
        project_btn.clicked.connect(lambda: self._open_url(_PROJECT_URL))
        releases_btn = QPushButton("Releases")
        releases_btn.clicked.connect(lambda: self._open_url(f"{_PROJECT_URL}/releases/latest"))
        report_btn = QPushButton("Report an issue")
        report_btn.clicked.connect(lambda: self._open_url(f"{_PROJECT_URL}/issues"))
        links_row.addWidget(project_btn)
        links_row.addWidget(releases_btn)
        links_row.addWidget(report_btn)
        links_row.addStretch(1)
        about_layout.addLayout(links_row)
        about_layout.addStretch(1)
        tabs.addTab(about_tab, "About")

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

    @staticmethod
    def _js_runtime_text() -> str:
        from app.core import jsruntime

        runtime = jsruntime.detect_js_runtime()
        if runtime is not None:
            return f"JavaScript runtime (for YouTube): {runtime[0]} at {runtime[1]}."
        return (
            "JavaScript runtime (for YouTube): none found - Deno (~40 MB, "
            "verified) is installed automatically on the first YouTube download."
        )

    @staticmethod
    def _open_url(url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def _refresh_stats_label(self) -> None:
        total_bytes, total_files = self.settings.db.lifetime_bytes()
        self.stats_label.setText(
            f"Lifetime: {human_bytes(total_bytes)} downloaded across {total_files} file(s)."
        )

    def _clear_stats(self) -> None:
        answer = QMessageBox.question(
            self,
            "Grabline",
            "Clear all download statistics? The download list itself is not touched.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.settings.db.clear_stats()
            self._refresh_stats_label()

    def _browse_sound(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Completion sound", "", "Sounds (*.wav *.oga *.ogg *.aiff *.mp3);;All files (*)"
        )
        if chosen:
            self.sound_file_edit.setText(chosen)

    def _manage_cloud_accounts(self) -> None:
        from app.core.credentials import CredentialStore
        from app.ui.cloud_dialog import CloudAccountsDialog

        CloudAccountsDialog(CredentialStore(self.settings.db), self).exec()

    @staticmethod
    def _vpn_status_text() -> str:
        from app.core import net

        interfaces = net.active_vpn_interfaces()
        if interfaces:
            return f"VPN detected: active on {', '.join(interfaces)}."
        return "VPN detected: none (no tunnel interface is up)."

    def _browse_torrent_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Save torrents to", self.torrent_dir_edit.text() or str(Path.home())
        )
        if chosen:
            self.torrent_dir_edit.setText(chosen)

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
        if self.apply():
            self.accept()

    def apply(self) -> bool:
        """Persist every field. Returns False (without saving) if the proxy is
        malformed. Shared by the modal Save button and the embedded page."""
        from app.core import net

        proxy_error = net.validate_proxy(self.proxy_edit.text())
        if proxy_error is not None:
            QMessageBox.warning(self, "Grabline", proxy_error)
            return False
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
        self.settings.download_days = [
            index for index, check in enumerate(self.day_checks) if check.isChecked()
        ]
        self.settings.pause_on_battery = self.battery_check.isChecked()
        self.settings.wait_for_network = self.network_check.isChecked()
        self.settings.sound_on_complete = self.sound_check.isChecked()
        self.settings.sound_file = self.sound_file_edit.text()
        self.settings.script_on_complete = self.script_edit.text()
        self.settings.theme = self.theme_combo.currentData()
        self.settings.proxy = self.proxy_edit.text().strip() or None
        self.settings.auto_throttle = self.auto_throttle_check.isChecked()
        self.settings.auto_throttle_kbps = self.throttle_limit_spin.value()
        self.settings.auto_throttle_threshold_kbps = self.throttle_threshold_spin.value()
        self.settings.host_limits = _parse_host_limits(self.host_limits_edit.toPlainText())
        self.settings.notify_on_complete = self.notify_check.isChecked()
        self.settings.auto_open_folder = self.open_folder_check.isChecked()
        self.settings.auto_extract = self.extract_check.isChecked()
        self.settings.scan_before_extract = self.scan_check.isChecked()
        self.settings.scan_downloads = self.scan_downloads_check.isChecked()
        self.settings.enforce_https = self.enforce_https_check.isChecked()
        self.settings.virustotal_key = self.virustotal_edit.text()
        self.settings.safebrowsing_key = self.safebrowsing_edit.text()
        self.settings.archive_passwords = self.passwords_edit.toPlainText().splitlines()
        self.settings.favorite_folders = self.favorites_edit.toPlainText().splitlines()
        self.settings.rename_rules = _parse_rename_rules(self.rename_edit.toPlainText())
        self.settings.playlist_batch_cap = self.playlist_cap_spin.value()
        self.settings.ffmpeg_path = self.ffmpeg_override_edit.text().strip() or None
        self.settings.torrent_port = self.torrent_port_spin.value()
        self.settings.torrent_dht = self.dht_check.isChecked()
        self.settings.torrent_upnp = self.upnp_check.isChecked()
        self.settings.torrent_natpmp = self.natpmp_check.isChecked()
        self.settings.torrent_seed = self.seed_check.isChecked()
        self.settings.torrent_ratio_limit = self.ratio_spin.value()
        self.settings.torrent_upload_kbps = self.upload_spin.value()
        self.settings.torrent_sequential = self.sequential_check.isChecked()
        self.settings.torrent_dir = self.torrent_dir_edit.text().strip() or None
        self.settings.torrent_search_url = self.search_url_edit.text()
        self.settings.rss_feeds = self.rss_edit.toPlainText().splitlines()
        self.settings.rss_interval_minutes = self.rss_interval_spin.value()
        self.settings.after_queue_action = self.after_combo.currentData()
        try:
            # The autostart file/registry entry IS the setting - no DB copy
            # that could drift from what the OS will actually do at login.
            launcher.set_autostart(self.autostart_check.isChecked())
        except OSError as exc:
            QMessageBox.warning(self, "Grabline", f"Could not update autostart: {exc}")
        return True

    def done(self, result: int) -> None:
        if self._installer is not None and self._installer.isRunning():
            self._installer.wait(1000)
        super().done(result)
