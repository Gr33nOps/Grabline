"""Settings: every persisted option, organized into the sidebar sections the
embedded Settings page shows (General → About).

This dialog owns the fields and the save logic; it is normally never shown -
SettingsView lifts its tab pages into the embedded page. ``apply()`` persists
every field and is shared by both paths.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTime, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
from app.ui import chrome, components, design
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


class SettingsDialog(chrome.Dialog):
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
        general_form.addRow(self.autostart_check)
        self.updates_check = QCheckBox("Check for Grabline updates on startup")
        self.updates_check.setChecked(settings.check_updates)
        general_form.addRow(self.updates_check)
        self.start_min_check = QCheckBox("Start minimized to the tray")
        self.start_min_check.setChecked(settings.start_minimized)
        general_form.addRow(self.start_min_check)
        self.tray_min_check = QCheckBox("Minimize to the tray instead of the taskbar")
        self.tray_min_check.setChecked(settings.minimize_to_tray)
        general_form.addRow(self.tray_min_check)
        self.tray_close_check = QCheckBox("Closing the window keeps Grabline in the tray")
        self.tray_close_check.setChecked(settings.close_to_tray)
        general_form.addRow(self.tray_close_check)
        self.confirm_exit_check = QCheckBox("Confirm exit while downloads are running")
        self.confirm_exit_check.setChecked(settings.confirm_exit_active)
        general_form.addRow(self.confirm_exit_check)
        self.new_dl_combo = QComboBox()
        self.new_dl_combo.addItem("Start automatically", True)
        self.new_dl_combo.addItem("Add paused (start by hand)", False)
        self.new_dl_combo.setCurrentIndex(0 if settings.auto_start_downloads else 1)
        general_form.addRow("New downloads:", self.new_dl_combo)
        general_form.addRow(
            _note(
                "Always on by design: a single Grabline instance (the browser "
                "hands URLs to the running app). English-only for now; an "
                "update channel arrives when beta builds exist."
            )
        )

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
        downloads_form.addRow(self.categories_check)
        self.ask_save_check = QCheckBox("Ask where to save each download")
        self.ask_save_check.setChecked(settings.ask_save_dir)
        downloads_form.addRow(self.ask_save_check)
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 10)
        self.concurrent_spin.setValue(settings.max_concurrent)
        downloads_form.addRow("Simultaneous downloads:", self.concurrent_spin)
        self.free_mb_spin = QSpinBox()
        self.free_mb_spin.setRange(0, 1_000_000)
        self.free_mb_spin.setSingleStep(100)
        self.free_mb_spin.setSuffix(" MB")
        self.free_mb_spin.setSpecialValueText("Off")
        self.free_mb_spin.setValue(settings.min_free_mb)
        self.free_mb_spin.setToolTip("Warn before adding when the download drive is below this.")
        downloads_form.addRow("Low disk space warning:", self.free_mb_spin)
        downloads_form.addRow(
            _note(
                "A file that already exists is renamed (name (1).ext) - nothing "
                "is ever silently overwritten. Adding a URL already in the list "
                "asks first. In-progress data lives next to the file (.gl-part)."
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
        engine_form.addRow(
            _note(
                "Always on, nothing to configure: dynamic segmentation (free "
                "connections steal work from the slowest), smart chunk "
                "allocation, HTTP/2 where offered, IPv6, error-aware retries "
                "(rate limits back off, dead links fail fast), mirror "
                "failover, resume after crash / reboot / reconnect / power "
                "loss, and per-server capability detection. Not available: "
                "HTTP/3 and QUIC - the HTTP stack Grabline uses does not "
                "support them yet."
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
        self.clipboard_check = QCheckBox(
            "URL catcher: offer to download links copied to the clipboard"
        )
        self.clipboard_check.setChecked(settings.clipboard_watcher)
        browser_layout.addWidget(self.clipboard_check)
        browser_layout.addWidget(
            _note(
                "Per-site hover-button toggles, the button corner, download "
                "takeover, and media/stream detection live in the extension's "
                "toolbar popup - right where you see the page. File-type and "
                "size-based interception rules are on the roadmap."
            )
        )
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
        self.hq_first_check = QCheckBox(
            "Prefer highest quality over a fast start (solves YouTube's JS "
            "challenge up front; can add minutes before a download begins)"
        )
        self.hq_first_check.setChecked(settings.video_hq_first)
        self.hq_first_check.setToolTip(
            "Off: downloads start in seconds using YouTube's runtime-free "
            "clients, which can top out at 1080p. On: every video download "
            "pays the challenge-solver cost first and gets the complete "
            "format ladder (4K/8K where available)."
        )
        video_layout.addWidget(self.hq_first_check)
        defaults_form = QFormLayout()
        self.default_quality_combo = QComboBox()
        for label in ("Best", "2160p", "1440p", "1080p", "720p", "480p", "MP3", "M4A", "FLAC"):
            self.default_quality_combo.addItem(label)
        self.default_quality_combo.setCurrentText(settings.video_default_quality)
        self.default_quality_combo.setToolTip("Preselected in the quality panel.")
        defaults_form.addRow("Default quality:", self.default_quality_combo)
        self.bitrate_combo = QComboBox()
        for rate in ("128", "192", "256", "320"):
            self.bitrate_combo.addItem(f"{rate} kbps", rate)
        self.bitrate_combo.setCurrentIndex(
            max(0, self.bitrate_combo.findData(settings.audio_bitrate))
        )
        defaults_form.addRow("MP3 bitrate:", self.bitrate_combo)
        cookies_row = QHBoxLayout()
        self.cookies_edit = QLineEdit(settings.cookies_file)
        self.cookies_edit.setPlaceholderText("cookies.txt (Netscape format) - blank = off")
        cookies_browse = QPushButton("Browse…")
        cookies_browse.clicked.connect(self._browse_cookies)
        cookies_row.addWidget(self.cookies_edit, 1)
        cookies_row.addWidget(cookies_browse)
        defaults_form.addRow("Cookies file:", cookies_row)
        video_layout.addLayout(defaults_form)
        video_layout.addWidget(
            _note(
                "Chosen per download in the panel: exact quality, subtitles and "
                "their languages (embedded or .srt), clip trimming, chapters, "
                "SponsorBlock, thumbnail/metadata sidecars, and extra FFmpeg "
                "arguments. Not offered: OAuth account login (an open-source "
                "app cannot ship client secrets - the cookies file covers "
                "signed-in content) and custom filename templates (Grabline "
                "names files from the real title). yt-dlp updates ship with "
                "each Grabline release."
            )
        )
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
        torrent_form.addRow(self.dht_check)
        self.upnp_check = QCheckBox("UPnP port mapping")
        self.upnp_check.setChecked(settings.torrent_upnp)
        torrent_form.addRow(self.upnp_check)
        self.natpmp_check = QCheckBox("NAT-PMP port mapping")
        self.natpmp_check.setChecked(settings.torrent_natpmp)
        torrent_form.addRow(self.natpmp_check)
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
        torrent_form.addRow(self.sequential_check)
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
        self.encryption_combo = QComboBox()
        for label, value in (
            ("Prefer encrypted peers", "prefer"),
            ("Require encryption", "require"),
            ("Plaintext only", "off"),
        ):
            self.encryption_combo.addItem(label, value)
        self.encryption_combo.setCurrentIndex(
            max(0, self.encryption_combo.findData(settings.torrent_encryption))
        )
        torrent_form.addRow("Encryption:", self.encryption_combo)
        self.seed_minutes_spin = QSpinBox()
        self.seed_minutes_spin.setRange(0, 100_000)
        self.seed_minutes_spin.setSuffix(" min")
        self.seed_minutes_spin.setSpecialValueText("No time limit")
        self.seed_minutes_spin.setValue(settings.torrent_seed_minutes)
        self.seed_minutes_spin.setToolTip(
            "Stop seeding after this long (the ratio limit also applies)."
        )
        torrent_form.addRow("Seeding time limit:", self.seed_minutes_spin)
        self.trackers_default_edit = QPlainTextEdit()
        self.trackers_default_edit.setPlainText("\n".join(settings.torrent_trackers))
        self.trackers_default_edit.setPlaceholderText(
            "default tracker URLs for Create Torrent, one per line"
        )
        self.trackers_default_edit.setFixedHeight(56)
        torrent_form.addRow("Default trackers:", self.trackers_default_edit)
        torrent_form.addRow(
            _note(
                "PEX and web seeds are always on. How many torrents run at once "
                "is the queue system's job - see Queue Manager. Per-torrent "
                "bandwidth follows the global and scheduled limits."
            )
        )

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
        archive_form.addRow(self.extract_check)
        self.scan_check = QCheckBox("Virus-scan archives before extracting")
        self.scan_check.setChecked(settings.scan_before_extract)
        self.scan_check.setToolTip(
            "Uses a scanner already on this machine - Windows Defender or "
            "ClamAV. If none is installed, extraction stops with a message "
            "instead of pretending to scan."
        )
        archive_form.addRow(self.scan_check)
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
        self.extract_subfolder_check = QCheckBox("Extract into a folder named after the archive")
        self.extract_subfolder_check.setChecked(settings.extract_to_subfolder)
        archive_form.addRow(self.extract_subfolder_check)
        self.delete_archive_check = QCheckBox("Delete the archive after a clean extraction")
        self.delete_archive_check.setChecked(settings.delete_archive_after_extract)
        archive_form.addRow(self.delete_archive_check)
        archive_form.addRow(
            _note(
                "Formats: ZIP / TAR / GZ / BZ2 / XZ built in; RAR and 7Z via an "
                "installed 7-Zip. Right-click a finished archive for Preview "
                "archive… (extract selected files) and Extract here."
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
        self.default_tags_edit = QLineEdit(settings.default_tags)
        self.default_tags_edit.setPlaceholderText("tags for every new download, comma separated")
        files_form.addRow("Default tags:", self.default_tags_edit)
        files_form.addRow(
            _note(
                "Always on: smart filenames (page titles replace junk like "
                "videoplayback.mp4), illegal characters stripped, and "
                "name (1).ext version numbering. Categories map by extension "
                "(Video / Music / Images / Documents / Archives / Programs / "
                "Games / Torrents). Adding a duplicate URL asks first; Find "
                "Duplicate Files… (⋯ menu) hash-compares finished downloads."
            )
        )

        # ---- Queue Manager -----------------------------------------------------
        queue_form = self._add_form_tab(tabs, "Queue Manager")
        self.default_queue_combo = QComboBox()
        self.default_queue_combo.addItem("(the global default)", 0)
        for queue_row in settings.db.list_queues():
            self.default_queue_combo.addItem(queue_row.name, queue_row.id)
        idx = self.default_queue_combo.findData(settings.default_queue_id)
        self.default_queue_combo.setCurrentIndex(max(0, idx))
        self.default_queue_combo.setToolTip(
            "New downloads join this queue when no category rule claims them."
        )
        queue_form.addRow("Default queue:", self.default_queue_combo)
        queue_form.addRow(
            _note(
                "Named queues - per-queue downloads-at-once, sequential or "
                "parallel mode, priorities (their order), schedules, category "
                "auto-assign, and queue-after-queue dependencies - are managed "
                "on the Queue page in the sidebar. Unpaused queues start with "
                "Grabline. The global simultaneous-downloads limit is under "
                "Downloads."
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
        battery_row = QHBoxLayout()
        self.battery_check = QCheckBox("Pause downloads on battery, below")
        self.battery_check.setChecked(settings.pause_on_battery)
        self.battery_pct_spin = QSpinBox()
        self.battery_pct_spin.setRange(0, 100)
        self.battery_pct_spin.setSuffix(" %")
        self.battery_pct_spin.setSpecialValueText("any charge")
        self.battery_pct_spin.setValue(settings.battery_min_percent)
        battery_row.addWidget(self.battery_check)
        battery_row.addWidget(self.battery_pct_spin)
        battery_row.addStretch(1)
        scheduler_form.addRow(battery_row)
        self.network_check = QCheckBox("Wait for internet - resume the moment it reconnects")
        self.network_check.setChecked(settings.wait_for_network)
        self.network_check.setToolTip(
            "Failed downloads always retry with backoff; this also holds new "
            "starts while offline and retries immediately on reconnect."
        )
        scheduler_form.addRow(self.network_check)
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
        throttle_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.auto_throttle_check = QCheckBox("Slow downloads when other apps are using the network")
        self.auto_throttle_check.setChecked(settings.auto_throttle)
        throttle_layout.addRow(self.auto_throttle_check)
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
        extras_form = QFormLayout()
        self.bypass_edit = QLineEdit(", ".join(settings.proxy_bypass))
        self.bypass_edit.setPlaceholderText("hosts that skip the proxy, comma separated")
        extras_form.addRow("Proxy bypass:", self.bypass_edit)
        self.ua_edit = QLineEdit(settings.user_agent)
        self.ua_edit.setPlaceholderText("custom User-Agent for plain downloads (blank = default)")
        extras_form.addRow("User-Agent:", self.ua_edit)
        net_layout.addLayout(extras_form)
        net_layout.addWidget(
            _note(
                "One proxy URL covers HTTP, HTTPS, SOCKS5 and SOCKS4, with "
                "user:pass@ auth. The upload cap lives under Torrent (the only "
                "engine that uploads). The nightly full-speed window is under "
                "Download Engine. VPN status is shown on the Dashboard and "
                "never gates downloads."
            )
        )
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
        security_form.addRow(self.scan_downloads_check)
        self.enforce_https_check = QCheckBox("Warn before downloading over unencrypted HTTP")
        self.enforce_https_check.setChecked(settings.enforce_https)
        security_form.addRow(self.enforce_https_check)
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
        self.scanner_combo = QComboBox()
        for label, value in (
            ("Automatic (first found)", "auto"),
            ("Windows Defender", "defender"),
            ("ClamAV", "clamav"),
        ):
            self.scanner_combo.addItem(label, value)
        self.scanner_combo.setCurrentIndex(
            max(0, self.scanner_combo.findData(settings.scanner_pref))
        )
        security_form.addRow("Virus scanner:", self.scanner_combo)
        self.scan_ext_edit = QLineEdit(settings.scan_extensions)
        self.scan_ext_edit.setPlaceholderText(
            "only scan these types, e.g. exe, msi, zip (blank = all)"
        )
        security_form.addRow("File types to scan:", self.scan_ext_edit)
        security_form.addRow(
            _note(
                "Checksums come in MD5, SHA-1, SHA-256, SHA-512 and CRC32 - "
                "paste any of them into Verify checksum and Grabline figures "
                "out which. TLS certificates are always validated. There is "
                "deliberately no quarantine/delete action: a flagged file "
                "stays yours, because antivirus false positives are common."
            )
        )

        # ---- Notifications -----------------------------------------------------
        notify_form = self._add_form_tab(tabs, "Notifications")
        self.notify_check = QCheckBox("Show a notification when a download completes")
        self.notify_check.setChecked(settings.notify_on_complete)
        notify_form.addRow(self.notify_check)
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
        notify_form.addRow(self.open_folder_check)
        self.notify_failed_check = QCheckBox("Notify when a download fails")
        self.notify_failed_check.setChecked(settings.notify_on_failed)
        notify_form.addRow(self.notify_failed_check)
        self.notify_queue_check = QCheckBox("Notify when the whole queue finishes")
        self.notify_queue_check.setChecked(settings.notify_queue_done)
        notify_form.addRow(self.notify_queue_check)
        self.toast_spin = QSpinBox()
        self.toast_spin.setRange(1, 30)
        self.toast_spin.setSuffix(" s")
        self.toast_spin.setValue(settings.toast_seconds)
        notify_form.addRow("Notification duration:", self.toast_spin)
        quiet_row = QHBoxLayout()
        self.quiet_check = QCheckBox("Quiet hours between")
        self.quiet_check.setChecked(settings.quiet_enabled)
        self.quiet_from_edit = QTimeEdit(QTime.fromString(settings.quiet_from, "HH:mm"))
        self.quiet_from_edit.setDisplayFormat("HH:mm")
        self.quiet_to_edit = QTimeEdit(QTime.fromString(settings.quiet_to, "HH:mm"))
        self.quiet_to_edit.setDisplayFormat("HH:mm")
        quiet_row.addWidget(self.quiet_check)
        quiet_row.addWidget(self.quiet_from_edit)
        quiet_row.addWidget(QLabel("and"))
        quiet_row.addWidget(self.quiet_to_edit)
        quiet_row.addStretch(1)
        notify_form.addRow(quiet_row)
        notify_form.addRow(
            _note("Quiet hours silence notifications and sounds; downloads keep running.")
        )

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
        stats_form = QFormLayout()
        self.stats_enabled_check = QCheckBox("Record download statistics (always local-only)")
        self.stats_enabled_check.setChecked(settings.stats_enabled)
        stats_form.addRow(self.stats_enabled_check)
        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(0, 3650)
        self.retention_spin.setSuffix(" days")
        self.retention_spin.setSpecialValueText("Keep forever")
        self.retention_spin.setValue(settings.stats_retention_days)
        stats_form.addRow("Keep daily data for:", self.retention_spin)
        self.refresh_spin = QSpinBox()
        self.refresh_spin.setRange(100, 5000)
        self.refresh_spin.setSingleStep(100)
        self.refresh_spin.setSuffix(" ms")
        self.refresh_spin.setValue(settings.dashboard_refresh_ms)
        self.refresh_spin.setToolTip(
            "Dashboard sampling interval (graphs animate at 60fps regardless)."
        )
        stats_form.addRow("Dashboard refresh:", self.refresh_spin)
        stats_layout.addLayout(stats_form)
        clear_row = QHBoxLayout()
        clear_stats = QPushButton("Clear statistics…")
        clear_stats.clicked.connect(self._clear_stats)
        export_stats = QPushButton("Export CSV…")
        export_stats.clicked.connect(self._export_stats)
        clear_row.addWidget(clear_stats)
        clear_row.addWidget(export_stats)
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
        self.accent_combo = QComboBox()
        for label, value in design.ACCENT_PRESETS:
            self.accent_combo.addItem(label, value)
        self.accent_combo.setCurrentIndex(max(0, self.accent_combo.findData(settings.accent_color)))
        appearance_form.addRow("Accent color:", self.accent_combo)
        self.density_combo = QComboBox()
        self.density_combo.addItem("Comfortable", "comfortable")
        self.density_combo.addItem("Compact", "compact")
        self.density_combo.setCurrentIndex(max(0, self.density_combo.findData(settings.ui_density)))
        appearance_form.addRow("List density:", self.density_combo)
        columns_row = QHBoxLayout()
        self.column_checks: dict[str, QCheckBox] = {}
        hidden_now = set(settings.hidden_columns)
        for key, label in (
            ("size", "Size"),
            ("progress", "Progress"),
            ("speed", "Speed"),
            ("eta", "ETA"),
            ("status", "Status"),
        ):
            check = QCheckBox(label)
            check.setChecked(key not in hidden_now)
            self.column_checks[key] = check
            columns_row.addWidget(check)
        columns_row.addStretch(1)
        appearance_form.addRow("Visible columns:", columns_row)
        appearance_form.addRow(
            _note(
                "The sun/moon button at the bottom of the sidebar switches "
                "between light and dark instantly. Progress bars animate "
                "smoothly by design; a font-size control is on the roadmap."
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
        self.log_combo = QComboBox()
        for level in ("debug", "info", "warning", "error"):
            self.log_combo.addItem(level.capitalize(), level)
        self.log_combo.setCurrentIndex(max(0, self.log_combo.findData(settings.log_level)))
        advanced_form.addRow("Logging level:", self.log_combo)
        self.logfile_check = QCheckBox("Also write the log to grabline.log in the data folder")
        self.logfile_check.setChecked(settings.log_to_file)
        advanced_form.addRow(self.logfile_check)
        io_row = QHBoxLayout()
        export_btn = QPushButton("Export settings…")
        export_btn.clicked.connect(self._export_settings)
        import_btn = QPushButton("Import settings…")
        import_btn.clicked.connect(self._import_settings)
        reset_btn = QPushButton("Reset all settings…")
        reset_btn.clicked.connect(self._reset_settings)
        io_row.addWidget(export_btn)
        io_row.addWidget(import_btn)
        io_row.addWidget(reset_btn)
        io_row.addStretch(1)
        advanced_form.addRow("Backup:", io_row)
        db_row = QHBoxLayout()
        vacuum_btn = QPushButton("Compact database")
        vacuum_btn.clicked.connect(self._vacuum_db)
        integrity_btn = QPushButton("Check database")
        integrity_btn.clicked.connect(self._check_db)
        db_row.addWidget(vacuum_btn)
        db_row.addWidget(integrity_btn)
        db_row.addStretch(1)
        advanced_form.addRow("Maintenance:", db_row)
        advanced_form.addRow(
            _note(
                "Deliberately absent: a remote-control API port (Grabline "
                "never opens a network port - the browser talks over Native "
                "Messaging) and a custom yt-dlp binary (it runs as a library "
                "and updates with each release). Logging changes take effect "
                "on the next launch."
            )
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
        releases_btn = QPushButton("Changelog && releases")
        releases_btn.clicked.connect(lambda: self._open_url(f"{_PROJECT_URL}/releases"))
        report_btn = QPushButton("Report an issue")
        report_btn.clicked.connect(lambda: self._open_url(f"{_PROJECT_URL}/issues"))
        diag_btn = QPushButton("Copy diagnostics")
        diag_btn.setToolTip("Version, OS and dependency info for bug reports - no personal data.")
        diag_btn.clicked.connect(self._copy_diagnostics)
        links_row.addWidget(project_btn)
        links_row.addWidget(releases_btn)
        links_row.addWidget(report_btn)
        links_row.addWidget(diag_btn)
        links_row.addStretch(1)
        about_layout.addLayout(links_row)
        about_layout.addWidget(
            _note(
                "Built on open source: yt-dlp (video engine), PySide6/Qt "
                "(interface), libtorrent (torrents), FFmpeg (conversion), "
                "httpx, paramiko, boto3, psutil."
            )
        )
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
        # Everything hangs off one left edge - labels, fields, and spanning
        # checkbox rows - instead of the platform default's ragged mix.
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
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

    def _browse_cookies(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Cookies file", "", "cookies.txt (*.txt);;All files (*)"
        )
        if chosen:
            self.cookies_edit.setText(chosen)

    def _export_stats(self) -> None:
        path, _f = QFileDialog.getSaveFileName(
            self, "Export statistics", "grabline-stats.csv", "CSV (*.csv)"
        )
        if not path:
            return
        import csv

        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["day", "category", "host", "bytes", "files"])
            writer.writerows(self.settings.db.stats_rows())
        QMessageBox.information(self, "Grabline", f"Statistics exported to {path}")

    def _export_settings(self) -> None:
        path, _f = QFileDialog.getSaveFileName(
            self, "Export settings", "grabline-settings.json", "JSON (*.json)"
        )
        if not path:
            return
        import json as _json

        payload = self.settings.db.all_settings()
        # Never export secrets in plain text.
        for secret in ("virustotal_key", "safebrowsing_key"):
            payload.pop(secret, None)
        with open(path, "w", encoding="utf-8") as handle:
            _json.dump(payload, handle, indent=2, sort_keys=True)
        QMessageBox.information(
            self, "Grabline", f"Settings exported to {path}\n(API keys are not included.)"
        )

    def _import_settings(self) -> None:
        path, _f = QFileDialog.getOpenFileName(
            self, "Import settings", "", "JSON (*.json);;All files (*)"
        )
        if not path:
            return
        import json as _json

        try:
            with open(path, encoding="utf-8") as handle:
                payload = _json.load(handle)
            if not isinstance(payload, dict):
                raise ValueError("not a settings export")
            count = self.settings.db.import_settings({str(k): str(v) for k, v in payload.items()})
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Grabline", f"Could not import: {exc}")
            return
        QMessageBox.information(
            self,
            "Grabline",
            f"Imported {count} setting(s). Reopen Settings (or restart) to see them all.",
        )

    def _reset_settings(self) -> None:
        answer = QMessageBox.question(
            self,
            "Grabline",
            "Reset every setting to its default? Downloads and statistics are kept.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.settings.db.reset_settings()
            QMessageBox.information(
                self, "Grabline", "Settings reset. Restart Grabline to apply everywhere."
            )

    def _vacuum_db(self) -> None:
        self.settings.db.vacuum()
        QMessageBox.information(self, "Grabline", "Database compacted.")

    def _check_db(self) -> None:
        verdict = self.settings.db.integrity_check()
        if verdict == "ok":
            QMessageBox.information(self, "Grabline", "Database check: OK.")
        else:
            QMessageBox.warning(self, "Grabline", f"Database check reported:\n{verdict}")

    def _copy_diagnostics(self) -> None:
        import platform
        import sys as _sys

        lines = [f"Grabline {__version__}"]
        lines.append(f"OS: {platform.platform()}")
        lines.append(f"Python: {_sys.version.split()[0]}")
        for module, label in (
            ("yt_dlp", "yt-dlp"),
            ("PySide6", "PySide6"),
            ("libtorrent", "libtorrent"),
            ("httpx", "httpx"),
        ):
            try:
                imported = __import__(module)
                version = getattr(imported, "__version__", None) or getattr(
                    getattr(imported, "version", None), "__version__", "?"
                )
                lines.append(f"{label}: {version}")
            except Exception:
                lines.append(f"{label}: not available")
        from app.core.ffmpeg import find_ffmpeg as _find

        lines.append(f"FFmpeg: {_find(self.settings) or 'not found'}")
        QGuiApplication.clipboard().setText("\n".join(lines))
        QMessageBox.information(self, "Grabline", "Diagnostics copied to the clipboard.")

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
        self.settings.video_hq_first = self.hq_first_check.isChecked()
        self.settings.start_minimized = self.start_min_check.isChecked()
        self.settings.minimize_to_tray = self.tray_min_check.isChecked()
        self.settings.close_to_tray = self.tray_close_check.isChecked()
        self.settings.confirm_exit_active = self.confirm_exit_check.isChecked()
        self.settings.auto_start_downloads = bool(self.new_dl_combo.currentData())
        self.settings.ask_save_dir = self.ask_save_check.isChecked()
        self.settings.min_free_mb = self.free_mb_spin.value()
        self.settings.video_default_quality = self.default_quality_combo.currentText()
        self.settings.audio_bitrate = self.bitrate_combo.currentData()
        self.settings.cookies_file = self.cookies_edit.text()
        self.settings.torrent_encryption = self.encryption_combo.currentData()
        self.settings.torrent_seed_minutes = self.seed_minutes_spin.value()
        self.settings.torrent_trackers = self.trackers_default_edit.toPlainText().splitlines()
        self.settings.extract_to_subfolder = self.extract_subfolder_check.isChecked()
        self.settings.delete_archive_after_extract = self.delete_archive_check.isChecked()
        self.settings.default_tags = self.default_tags_edit.text()
        self.settings.default_queue_id = int(self.default_queue_combo.currentData() or 0)
        self.settings.battery_min_percent = self.battery_pct_spin.value()
        self.settings.proxy_bypass = [h for h in self.bypass_edit.text().split(",") if h.strip()]
        self.settings.user_agent = self.ua_edit.text()
        self.settings.scanner_pref = self.scanner_combo.currentData()
        self.settings.scan_extensions = self.scan_ext_edit.text()
        self.settings.notify_on_failed = self.notify_failed_check.isChecked()
        self.settings.notify_queue_done = self.notify_queue_check.isChecked()
        self.settings.toast_seconds = self.toast_spin.value()
        self.settings.quiet_enabled = self.quiet_check.isChecked()
        self.settings.quiet_from = self.quiet_from_edit.time().toString("HH:mm")
        self.settings.quiet_to = self.quiet_to_edit.time().toString("HH:mm")
        self.settings.stats_enabled = self.stats_enabled_check.isChecked()
        self.settings.stats_retention_days = self.retention_spin.value()
        self.settings.dashboard_refresh_ms = self.refresh_spin.value()
        self.settings.accent_color = self.accent_combo.currentData()
        self.settings.ui_density = self.density_combo.currentData()
        self.settings.hidden_columns = [
            key for key, check in self.column_checks.items() if not check.isChecked()
        ]
        self.settings.log_level = self.log_combo.currentData()
        self.settings.log_to_file = self.logfile_check.isChecked()
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
