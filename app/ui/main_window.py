"""The queue window (F0.4) and the add-URL flow: paste a URL, the resolver
routes it in a background thread, and Smart Engine hits get the quality panel.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from PySide6.QtCore import (
    QEvent,
    QItemSelection,
    QItemSelectionModel,
    QPoint,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.core import (
    archive,
    convert,
    crawler,
    dupes,
    listio,
    naming,
    reputation,
    rss,
    security,
    update,
    verify,
    virusscan,
)
from app.core.batch import expand_all, expand_pattern, extract_urls
from app.core.errors import DownloadError
from app.core.ffmpeg import find_ffmpeg
from app.core.manager import DownloadManager, JobView
from app.core.models import JobKind, JobStatus
from app.core.resolver import Resolution, Resolver
from app.core.settings import Settings
from app.engines import cloud as cloud_engine
from app.engines import torrent as torrent_engine
from app.engines.smart import option_for_label
from app.ui import chrome, components, design, icons, motion, theme, work_threads
from app.ui.archive_dialog import ArchiveDialog
from app.ui.batch_dialog import BatchImportDialog, BatchImportThread
from app.ui.cloud_dialog import CloudFolderDialog, prompt_cloud_url
from app.ui.dashboard import DashboardDialog
from app.ui.dashboard_view import DashboardView
from app.ui.detail_drawer import DetailDrawer
from app.ui.dupes_dialog import DupesDialog
from app.ui.format import human_bytes
from app.ui.gallery_panel import GalleryPanel
from app.ui.gif_dialog import GifDialog
from app.ui.inspector_dialog import InspectorDialog
from app.ui.link_panel import LinkPanel
from app.ui.playlist_panel import PlaylistPanel
from app.ui.quality_panel import QualityPanel
from app.ui.queue_dialog import QueueManagerDialog
from app.ui.queue_view import QueueView
from app.ui.security_dialog import SecurityDialog
from app.ui.settings_dialog import SettingsDialog
from app.ui.settings_view import SettingsView
from app.ui.setup_dialog import SetupDialog
from app.ui.tools_view import ToolsView
from app.ui.torrent_dialog import AddTorrentDialog, CreateTorrentDialog

#: Table columns: an icon, name, size, progress, speed, ETA, status.
_COLUMNS = ("", "Name", "Size", "Progress", "Speed", "ETA", "Status")
_COL_ICON, _COL_NAME, _COL_SIZE, _COL_PROGRESS, _COL_SPEED, _COL_ETA, _COL_STATUS = range(7)
_VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}

#: Filter key -> the statuses it shows (empty tuple = everything).
_FILTER_STATUSES: dict[str, tuple[JobStatus, ...]] = {
    "all": (),
    "active": (JobStatus.DOWNLOADING, JobStatus.QUEUED, JobStatus.PAUSED),
    "completed": (JobStatus.COMPLETED,),
    "failed": (JobStatus.FAILED, JobStatus.CANCELLED),
}


class _ScanFlagged(DownloadError):
    """A pre-extract virus scan flagged the archive. Advisory, not fatal: the
    caller asks the user whether to extract anyway."""

    def __init__(self, scanner: str, detail: str) -> None:
        super().__init__(f"{scanner} flagged this archive")
        self.scanner = scanner
        self.detail = detail


class MainWindow(QMainWindow):
    #: Emitted when a download finishes (display name, file path) and when the
    #: last active/queued download drains, so __main__ can toast and act.
    job_completed = Signal(str, str)
    job_failed = Signal(str, str)  # display name, error text
    queue_drained = Signal()

    def __init__(self, manager: DownloadManager, settings: Settings) -> None:
        super().__init__()
        self.manager = manager
        self.settings = settings
        self.resolver = Resolver()
        self.close_to_tray = False
        self.setWindowTitle("Grabline")
        self.resize(1040, 600)
        self.setMinimumSize(760, 420)
        self.setAcceptDrops(True)  # drop URLs (or text with URLs) onto the window
        # Custom chrome: no native title bar; ours draws the caption controls.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self._resizer = chrome.EdgeResizer(self)

        # State that per-row rendering + the theme toggle rely on.
        self._retintable: list[components.IconButton | components.SidebarButton] = []
        self._nav: dict[str, components.SidebarButton] = {}
        self._progress_bars: dict[int, motion.SmoothProgressBar] = {}
        self._pills: dict[int, components.StatusPill] = {}
        self._speed_smoothers: dict[int, motion.SpeedSmoother] = {}
        #: Force-removed jobs hidden immediately; cancelling a running worker
        #: is asynchronous, so its row would otherwise linger for seconds.
        self._removing: set[int] = set()
        #: True while a right-click selects its row - selection then must not
        #: pop the details drawer (that is a left-click affordance).
        self._suppress_drawer = False
        #: True while inside a handoff's modal dialog, to stop the 1s handoff
        #: timer re-entering through the nested event loop and stacking dialogs.
        self._in_handoff = False
        #: Set once shutdown() runs; the pollers become no-ops so a late tick
        #: (e.g. the 15s RSS singleShot, which stop() cannot cancel) never
        #: touches the database after it closes.
        self._shutting_down = False

        # Shell: a 48px icon rail on the left, the stacked content on the right.
        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_downloads_page())  # index 0
        self._dashboard_view = DashboardView(self.manager)
        self._pages.addWidget(self._dashboard_view)  # index 1
        self._queue_view = QueueView(self.manager)
        self._pages.addWidget(self._queue_view)  # index 2
        self._tools_view = ToolsView(
            {
                "grab_site": self._grab_site,
                "inspect_url": self._inspect_url_prompt,
                "search_torrents": self._search_torrents,
                "create_torrent": self._create_torrent,
                "find_duplicates": self._find_duplicates,
                "import_links": self._import_links,
                "import_list": self._import_list,
                "export_list": self._export_list,
            }
        )
        self._pages.addWidget(self._tools_view)  # index 3
        self._settings_view = SettingsView(self.settings, self._on_settings_applied)
        self._pages.addWidget(self._settings_view)  # index 4
        self._page_index = {"downloads": 0, "dashboard": 1, "queue": 2, "tools": 3, "settings": 4}
        shell = QWidget()
        row = QHBoxLayout(shell)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._build_sidebar())
        row.addWidget(self._pages, 1)
        central = QWidget()
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self._title_bar = chrome.TitleBar(self)
        column.addWidget(self._title_bar)
        column.addWidget(shell, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Ready")
        # A global activity indicator: whenever anything is working in the
        # background (analyzing, hashing, extracting, converting, listing,
        # crawling…) this shimmer runs next to the status text, so a wait is
        # never a mystery. Permanent widgets survive showMessage().
        self._busy_ops = 0
        self._busy_bar = motion.SmoothProgressBar()
        self._busy_bar.setFixedWidth(90)
        self._busy_bar.hide()
        self._busy_count = components.role_label("", "muted", size=design.FONT["small"])
        self._busy_count.hide()
        self.statusBar().addPermanentWidget(self._busy_count)
        self.statusBar().addPermanentWidget(self._busy_bar)
        self._status_info = components.role_label("", "muted", size=design.FONT["small"])
        self.statusBar().addPermanentWidget(self._status_info)

        self._row_job_ids: list[int] = []
        self._last_views: dict[int, JobView] = {}
        #: Speed measured once per poll, shared by the rows, drawer and toolbar.
        self._speeds: dict[int, float] = {}
        self._selected_ids: set[int] = set()
        self.clipboard_suppressor: Callable[[str], None] | None = None
        self._prev_status: dict[int, JobStatus] = {}
        self._was_active = False
        self._resolve_threads: list[work_threads.ResolveThread] = []
        self._file_ops: set[work_threads.FileOpThread] = set()
        self._auto_extracted: set[int] = set()
        self._scanned: set[int] = set()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(500)
        # Grabline Connect drops URLs into the handoffs table; pick them up.
        self._handoff_timer = QTimer(self)
        self._handoff_timer.timeout.connect(self._poll_handoffs)
        self._handoff_timer.start(1000)
        # RSS torrent feeds: poll on the configured interval (plus once soon
        # after launch so a restart doesn't wait half an hour).
        self._rss_timer = QTimer(self)
        self._rss_timer.timeout.connect(self._poll_rss)
        self._rss_timer.start(self.settings.rss_interval_minutes * 60_000)
        QTimer.singleShot(15_000, self._poll_rss)
        self.refresh()

    # ------------------------------------------------------------- shell

    def _build_sidebar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Sidebar")
        bar.setFixedWidth(48)
        lay = QVBoxLayout(bar)
        lay.setContentsMargins(5, 10, 5, 10)
        lay.setSpacing(2)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        nav = (
            ("downloads", "download", "Downloads", lambda: self._switch_view("downloads")),
            ("dashboard", "dashboard", "Dashboard", lambda: self._switch_view("dashboard")),
            ("queue", "queue", "Queue manager", lambda: self._switch_view("queue")),
            ("tools", "tools", "Tools", lambda: self._switch_view("tools")),
        )
        for key, icon_name, tip, handler in nav:
            btn = components.SidebarButton(icon_name, tip)
            btn.clicked.connect(handler)
            self._nav[key] = btn
            self._retintable.append(btn)
            lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
        self._nav["downloads"].set_active(True)

        lay.addStretch(1)

        # Settings anchors the bottom of the rail. Theme switching lives in
        # Settings → Appearance - no quick toggle here.
        settings_btn = components.SidebarButton("settings", "Settings")
        settings_btn.clicked.connect(lambda: self._switch_view("settings"))
        self._nav["settings"] = settings_btn
        self._retintable.append(settings_btn)
        lay.addWidget(settings_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        return bar

    def _build_downloads_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._build_toolbar())
        col.addWidget(self._build_filter_bar())
        # table + slide-in detail drawer side by side
        split = QWidget()
        srow = QHBoxLayout(split)
        srow.setContentsMargins(0, 0, 0, 0)
        srow.setSpacing(0)
        srow.addWidget(self._build_table(), 1)
        self._drawer = DetailDrawer(
            self.manager,
            on_open_folder=self._open_view_folder,
            on_copy_url=self._copy_view_url,
            on_copy_hash=lambda v: self._copy_hash(Path(v.dest_dir) / v.filename),
            on_remove=self._remove_from_drawer,
        )
        srow.addWidget(self._drawer)
        col.addWidget(split, 1)
        return page

    def _copy_view_url(self, view: JobView) -> None:
        if self.clipboard_suppressor is not None:
            self.clipboard_suppressor(view.url)
        QGuiApplication.clipboard().setText(view.url)
        self.statusBar().showMessage("URL copied", 3000)

    def _open_view_folder(self, view: JobView) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(view.dest_dir))

    def _remove_from_drawer(self, view: JobView) -> None:
        self.manager.remove(view.id, force=True)
        self._removing.add(view.id)
        self._drawer.hide()
        self.refresh()

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Toolbar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 6, 10, 6)
        lay.setSpacing(2)

        def add_btn(
            icon_name: str, label: str, handler: object, *, danger: bool = False, tip: str = ""
        ) -> None:
            btn = components.IconButton(icon_name, label, danger=danger, tooltip=tip)
            btn.clicked.connect(handler)
            self._retintable.append(btn)
            lay.addWidget(btn)

        # One labeled primary action; secondary add-sources are icons with
        # tooltips. (Also what lets the toolbar fit a 760px window.)
        add_url = QPushButton("  Add URL")
        add_url.setProperty("accent", "true")
        add_url.setCursor(Qt.CursorShape.PointingHandCursor)
        # accent_on is white in every palette/preset, so no retint needed.
        add_url.setIcon(icons.svg_icon("add", theme.current().accent_on))
        add_url.setIconSize(QSize(16, 16))
        add_url.setToolTip("Add a download from a URL")
        add_url.clicked.connect(self._add_url)
        lay.addWidget(add_url)
        add_btn("torrent", "", self._add_torrent_file, tip="Add a .torrent file")
        add_btn("cloud", "", self._add_cloud, tip="Add a cloud/server download")
        lay.addWidget(self._sep())
        add_btn("pause", "", self._pause_selected, tip="Pause the selected downloads")
        add_btn("resume", "", self._resume_selected, tip="Resume the selected downloads")
        add_btn("cancel", "", self._cancel_selected, tip="Cancel the selected downloads")
        add_btn(
            "trash",
            "",
            self._remove_selected,
            danger=True,
            tip="Remove the selected downloads from the list (files stay on disk)",
        )
        lay.addWidget(self._sep())
        add_btn("folder", "", self._open_folder, tip="Open the download folder")
        lay.addStretch(1)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search downloads…")
        self.search_box.setClearButtonEnabled(True)
        # Compresses first when the window narrows, so the toolbar never
        # overlaps itself at the 760px minimum window width.
        self.search_box.setMinimumWidth(96)
        self.search_box.setMaximumWidth(210)
        self.search_box.textChanged.connect(lambda _t: self._apply_filter())
        lay.addWidget(self.search_box)
        lay.addWidget(self._sep())

        self.speed_line = motion.Sparkline()
        lay.addWidget(self.speed_line)
        self._total_speed = components.role_label("—", "strong", size=design.FONT["h2"], bold=True)
        self._total_speed.setFont(design.numeric_font(self._total_speed.font()))
        lay.addWidget(self._total_speed)
        return bar

    def _sep(self) -> QFrame:
        s = QFrame()
        s.setObjectName("Separator")
        s.setFixedSize(1, 18)
        return s

    def _build_filter_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("FilterBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(2)
        self._filter = "all"
        self._filter_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ("all", "All"),
            ("active", "Active"),
            ("completed", "Completed"),
            ("failed", "Failed"),
        ):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, k=key: self._set_filter(k))
            self._filter_buttons[key] = btn
            lay.addWidget(btn)
        lay.addStretch(1)
        # Housekeeping lives with the list it acts on: visible only while
        # there is something completed to clear.
        clear = QPushButton("Clear completed")
        clear.setCursor(Qt.CursorShape.PointingHandCursor)
        clear.setToolTip("Remove the completed downloads from the list (files stay on disk)")
        clear.clicked.connect(self._clear_completed)
        clear.hide()
        self._clear_completed_btn = clear
        lay.addWidget(clear)
        self._style_filter_buttons()
        return bar

    def _style_filter_buttons(self) -> None:
        p = theme.current()
        for key, btn in self._filter_buttons.items():
            active = key == self._filter
            color = p.accent if active else p.text2
            border = p.accent if active else "transparent"
            weight = 600 if active else 400
            btn.setStyleSheet(
                f"QPushButton {{ border: none; background: transparent; padding: 8px 12px;"
                f" color: {color}; font-weight: {weight};"
                f" border-bottom: 2px solid {border}; }}"
                f" QPushButton:hover {{ color: {p.text}; }}"
            )
        self._clear_completed_btn.setStyleSheet(
            f"QPushButton {{ border: none; background: transparent; padding: 8px 12px;"
            f" color: {p.text3}; border-bottom: 2px solid transparent; }}"
            f" QPushButton:hover {{ color: {p.text}; }}"
        )

    def _set_filter(self, key: str) -> None:
        self._filter = key
        self._style_filter_buttons()
        self._apply_filter()

    def _build_table(self) -> QWidget:
        self.table = QTableWidget(0, len(_COLUMNS), self)
        self.table.setObjectName("JobsTable")  # full-bleed styling in the QSS
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_row_menu)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        self.table.setColumnWidth(_COL_ICON, 30)
        self.table.setColumnWidth(_COL_SIZE, 92)
        self.table.setColumnWidth(_COL_PROGRESS, 150)
        self.table.setColumnWidth(_COL_SPEED, 100)
        self.table.setColumnWidth(_COL_ETA, 84)
        # Hugging pills need less room than the old filled chips did.
        self.table.setColumnWidth(_COL_STATUS, 116)
        header.setStretchLastSection(False)
        # Header alignment matches its column's content: text left, numbers
        # right. (Qt centers headers by default, matching nothing.)
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        for col, align in (
            (_COL_NAME, left),
            (_COL_SIZE, right),
            (_COL_PROGRESS, left),
            (_COL_SPEED, right),
            (_COL_ETA, right),
            (_COL_STATUS, left),
        ):
            item = self.table.horizontalHeaderItem(col)
            if item is not None:
                item.setTextAlignment(align)
        from PySide6.QtWidgets import QHeaderView

        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        # The empty state: one quiet line naming the action that exists,
        # instead of a bare surface. Purely visual; hidden once rows appear.
        self._empty_label = components.role_label(
            "Nothing here yet — paste a link or press Add URL", "muted"
        )
        self._empty_label.setParent(self.table.viewport())
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.hide()
        self._apply_table_prefs()
        return self.table

    def _apply_table_prefs(self) -> None:
        """Appearance prefs: row density and which columns are visible."""
        compact = self.settings.ui_density == "compact"
        self.table.verticalHeader().setDefaultSectionSize(26 if compact else 34)
        hidden = set(self.settings.hidden_columns)
        toggles = {
            "size": _COL_SIZE,
            "progress": _COL_PROGRESS,
            "speed": _COL_SPEED,
            "eta": _COL_ETA,
            "status": _COL_STATUS,
        }
        for key, column in toggles.items():
            self.table.setColumnHidden(column, key in hidden)

    def _switch_view(self, key: str) -> None:
        """Sidebar navigation between the embedded pages."""
        if key not in self._page_index:
            return
        for nav_key, btn in self._nav.items():
            btn.set_active(nav_key == key)
        self._pages.setCurrentIndex(self._page_index[key])

    def _on_settings_applied(self) -> None:
        """Live-apply after the Settings page saves: theme (may have changed),
        rate/schedule/proxy, and retint the chrome."""
        app = QApplication.instance()
        if isinstance(app, QApplication):
            theme.apply_theme(app, self.settings.theme, accent=self.settings.accent_color or None)
        self.manager.reload_settings()
        self._apply_table_prefs()
        self._retint_all()
        self.statusBar().showMessage("Settings saved", 4000)

    def _retint_all(self) -> None:
        self._title_bar.retint()
        for btn in self._retintable:
            btn.retint()
        self._tools_view.retint()
        self._style_filter_buttons()
        # Rebuild rows so per-row widgets (pills, bars) repaint in the new theme.
        self._row_job_ids = []
        self._progress_bars.clear()
        self._pills.clear()
        self.refresh()

    def open_setup(self) -> None:
        SetupDialog(self).exec()

    def shutdown(self) -> None:
        """Quiesce the window before the app closes the database. Stop the
        polling timers (so no tick touches a closed connection), then wait for
        this window's own worker threads to finish. A file-op or resolve thread
        is parented to the window; if it were still running when the window is
        destroyed at exit, Qt would abort the process. These workers wrap
        bounded operations (a subprocess convert, a network resolve), so the
        wait terminates."""
        self._shutting_down = True
        for timer in (self._timer, self._handoff_timer, self._rss_timer):
            timer.stop()
        for worker in [*self._file_ops, *self._resolve_threads]:
            worker.wait(8000)

    def _poll_handoffs(self) -> None:
        # Gallery/links handoffs open a modal dialog (exec) whose nested event
        # loop keeps this 1s timer firing. Without a guard, rapid browser
        # clicks re-enter here and stack modal dialogs on top of each other.
        # The guard makes a re-entrant tick a no-op; any handoffs that arrived
        # meanwhile are simply claimed on the next poll after the modal closes.
        if self._shutting_down or self._in_handoff:
            return
        self._in_handoff = True
        try:
            self._drain_handoffs()
        finally:
            self._in_handoff = False

    def _drain_handoffs(self) -> None:
        for handoff in self.manager.db.claim_handoffs():
            if handoff.source == "gallery" and handoff.payload:
                self._open_gallery(list(handoff.payload), handoff.page_title)
            elif handoff.source == "links" and handoff.payload:
                self._open_links(list(handoff.payload), handoff.page_title)
            elif handoff.source == "torrent" or torrent_engine.is_torrent_source(handoff.url):
                # 'Open with Grabline' on a .torrent / magnet, from any source.
                self.add_torrent_source(handoff.url)
            elif handoff.source == "cloud" or cloud_engine.is_cloud_scheme(handoff.url):
                self.add_cloud_source(handoff.url)
            else:
                self.begin_add_url(
                    handoff.url,
                    page_title=handoff.page_title,
                    quality=handoff.quality,
                    fallbacks=handoff.payload,
                    headers=handoff.headers,
                )

    def _open_gallery(self, urls: list[str], page_title: str | None) -> None:
        """F2.2: the extension collected a page's images - pick and batch."""
        panel = GalleryPanel(urls, page_title=page_title, parent=self)
        if panel.exec() != GalleryPanel.DialogCode.Accepted:
            return
        for url in panel.selected_urls():
            self.manager.add_url(url)
        self.refresh()

    def _open_links(self, urls: list[str], page_title: str | None) -> None:
        """The extension collected a page's downloadable links - pick, then
        queue them through the resolver like a batch import."""
        panel = LinkPanel(urls, page_title=page_title, parent=self)
        if panel.exec() != LinkPanel.DialogCode.Accepted:
            return
        self._run_batch(panel.selected_urls())

    # ------------------------------------------------------------- actions

    def _add_url(self) -> None:
        url, accepted = QInputDialog.getText(
            self, "Add download", "URL (ranges like file[1-20].jpg expand):"
        )
        if not (accepted and url.strip()):
            return
        expanded = expand_pattern(url.strip())
        if len(expanded) > 1:
            self._run_batch(expanded)  # a pattern: queue them all at defaults
        else:
            self.begin_add_url(expanded[0])

    def _import_links(self) -> None:
        """F2.4: paste/load many URLs; they queue at defaults, no panels."""
        dialog = BatchImportDialog(self)
        if dialog.exec() != BatchImportDialog.DialogCode.Accepted:
            return
        self._run_batch(dialog.urls())

    def _grab_site(self) -> None:
        """Crawl a page (optionally deeper) and pick from the files it finds."""
        url, accepted = QInputDialog.getText(self, "Grab site", "Page URL:")
        url = url.strip()
        if not (accepted and url):
            return
        depth, accepted = QInputDialog.getInt(
            self,
            "Grab site",
            "How many levels deep to follow links?",
            value=0,
            minValue=0,
            maxValue=3,
        )
        if not accepted:
            return
        self.statusBar().showMessage(f"Scanning {url} …")
        proxy = self.settings.proxy

        def done(result: object) -> None:
            found = cast(list[str], result)
            self.statusBar().showMessage(f"Found {len(found)} file link(s)", 6000)
            if found:
                self._open_links(found, url)
            else:
                QMessageBox.information(
                    self, "Grabline", "No downloadable files found on that page."
                )

        self._run_file_op(partial(crawler.crawl, url, depth=depth, proxy=proxy), done)

    def _export_list(self) -> None:
        path, _f = QFileDialog.getSaveFileName(
            self, "Export download list", "grabline-downloads.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            count = listio.write_file(self.manager.db, Path(path))
        except OSError as exc:
            QMessageBox.warning(self, "Grabline", f"Could not export: {exc}")
            return
        self.statusBar().showMessage(f"Exported {count} download(s)", 6000)

    def _import_list(self) -> None:
        path, _f = QFileDialog.getOpenFileName(
            self, "Import download list", "", "JSON (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            count = listio.read_file(self.manager.db, Path(path))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Grabline", f"Could not import: {exc}")
            return
        self.statusBar().showMessage(f"Imported {count} download(s)", 6000)
        self.refresh()

    def check_for_updates(self, *, quiet: bool) -> None:
        """Look for a newer release; ``quiet`` skips the 'up to date' notice."""
        if not quiet:
            self.statusBar().showMessage("Checking for updates…")
        proxy = self.settings.proxy

        def done(result: object) -> None:
            self.statusBar().showMessage("Ready")  # never leave "Checking…" stuck
            if result is not None:
                tag, name, url = cast("tuple[str, str, str]", result)
                box = QMessageBox(self)
                box.setWindowTitle("Grabline")
                box.setText(
                    f"Grabline {tag} is available (you have {__version__}).\n\n"
                    "Update now downloads the installer and opens it."
                )
                update_btn = box.addButton("Update now", QMessageBox.ButtonRole.AcceptRole)
                site_btn = box.addButton("Download page", QMessageBox.ButtonRole.ActionRole)
                box.addButton(QMessageBox.StandardButton.Cancel)
                box.exec()
                if box.clickedButton() is update_btn:
                    self._download_and_run_installer(name, url)
                elif box.clickedButton() is site_btn:
                    QDesktopServices.openUrl(QUrl(update.WEBSITE_DOWNLOAD_URL))
            elif not quiet:
                QMessageBox.information(self, "Grabline", "You have the latest version.")

        def failed(_error: object) -> None:
            self.statusBar().showMessage("Ready")
            if not quiet:
                QMessageBox.information(self, "Grabline", "Could not check for updates right now.")

        self._run_file_op(partial(update.installer_update, proxy), done, failed)

    def _download_and_run_installer(self, name: str, url: str) -> None:
        """Fetch the new installer to the download folder and open it - the
        closest we get to auto-update without a signed self-updater."""
        from PySide6.QtWidgets import QProgressBar, QProgressDialog

        progress = QProgressDialog(f"Downloading {name}…", "Cancel", 0, 100, self)
        progress.setWindowTitle("Grabline update")
        progress.setMinimumDuration(0)
        bar = QProgressBar(progress)
        bar.setRange(0, 100)
        bar.setTextVisible(False)  # the themed 5px bar has no room for "42%"
        progress.setBar(bar)
        proxy = self.settings.proxy
        dest = str(self.settings.download_dir)

        relay = work_threads.ProgressRelay(self)
        relay.tick.connect(progress.setValue)

        def report(received: int, total: object) -> None:
            # Called on the worker thread: emitting a signal is thread-safe
            # (queued to the GUI thread); starting a QTimer here is not.
            if isinstance(total, int) and total > 0:
                relay.tick.emit(int(received / total * 100))

        def done(result: object) -> None:
            progress.close()
            path = str(result)
            self.statusBar().showMessage(f"Update downloaded: {path}", 8000)
            # Open the installer; the user finishes the (unsigned) wizard.
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

        def failed(error: object) -> None:
            progress.close()
            answer = QMessageBox.question(
                self,
                "Grabline",
                f"Could not download the update ({error}).\nOpen the download page instead?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(update.WEBSITE_DOWNLOAD_URL))

        self._run_file_op(
            lambda: update.download_installer(url, dest, name, proxy=proxy, progress=report),
            done,
            failed,
        )

    def _run_batch(self, urls: list[str]) -> None:
        """Queue many URLs through the resolver at sensible defaults."""
        if not urls:
            return
        thread = BatchImportThread(self.manager, self.settings, urls)
        self._busy_begin()
        thread.progress.connect(
            lambda done, total: self.statusBar().showMessage(f"Importing {done}/{total} …")
        )
        thread.summary.connect(self._on_batch_summary)
        thread.finished.connect(self._busy_end)
        thread.start_tracked()

    def _on_batch_summary(self, queued: int, skipped: object) -> None:
        items = cast(list[tuple[str, str]], skipped)
        message = f"Imported {queued} download(s)"
        if items:
            message += f", skipped {len(items)}"
        self.statusBar().showMessage(message, 10000)
        if items:
            detail = "\n".join(f"• {url} - {reason}" for url, reason in items[:10])
            if len(items) > 10:
                detail += f"\n… and {len(items) - 10} more"
            QMessageBox.information(self, "Grabline - import finished", f"{message}.\n\n{detail}")
        self.refresh()

    def begin_add_url(
        self,
        url: str,
        page_title: str | None = None,
        quality: str | None = None,
        fallbacks: tuple[str, ...] = (),
        headers: dict[str, str] | None = None,
        allow_duplicate: bool = False,
    ) -> None:
        """Entry point shared by the toolbar, tray, clipboard, and extension.
        A ``quality`` label (F1.3 in-page panel) skips the quality dialog;
        ``fallbacks`` are sniffed stream URLs tried in order if ``url``
        resolves to nothing (blob players on streaming sites); ``headers``
        are browser cookies/referer passed through for login-gated files."""
        if not allow_duplicate:
            existing = self.manager.find_existing(url)
            if existing is not None:
                what = (
                    "was already downloaded"
                    if existing.status is JobStatus.COMPLETED
                    else "is already in the list"
                )
                answer = QMessageBox.question(
                    self,
                    "Grabline",
                    f"{existing.filename} {what}.\nDownload it again?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    self.statusBar().showMessage("Ready")
                    return

        # Low-disk warning (advisory, Settings → Downloads): free space on the
        # download drive below the configured floor still lets you proceed.
        floor_mb = self.settings.min_free_mb
        if floor_mb:
            import shutil as _shutil

            try:
                free_mb = _shutil.disk_usage(str(self.settings.download_dir)).free // (1024 * 1024)
            except OSError:
                free_mb = None
            if free_mb is not None and free_mb < floor_mb:
                answer = QMessageBox.warning(
                    self,
                    "Grabline",
                    f"Only {free_mb} MB free on the download drive "
                    f"(warning floor: {floor_mb} MB). Download anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    self.statusBar().showMessage("Ready")
                    return
        # Advisory URL security: warn on plain HTTP (instant) and, if a Safe
        # Browsing key is set, check the URL off-thread. Both only warn - the
        # user can always proceed.
        scheme = urlsplit(url).scheme.lower()
        if self.settings.enforce_https and scheme == "http" and not self._confirm_insecure(url):
            self.statusBar().showMessage("Ready")
            return
        args = (page_title, quality, fallbacks, headers)
        if self.settings.safebrowsing_key and scheme in ("http", "https"):
            self._safebrowsing_then_resolve(url, args)
            return
        self._resolve_and_queue(url, *args)

    def _confirm_insecure(self, url: str) -> bool:
        answer = QMessageBox.warning(
            self,
            "Grabline",
            f"{url}\n\nThis download is over unencrypted HTTP - it could be "
            "tampered with in transit. Download anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _safebrowsing_then_resolve(
        self, url: str, args: tuple[str | None, str | None, tuple[str, ...], dict[str, str] | None]
    ) -> None:
        key = self.settings.safebrowsing_key
        proxy = self.settings.proxy
        self.statusBar().showMessage("Checking Safe Browsing …")

        def done(result: object) -> None:
            threat = str(result) if result else ""
            if threat:
                answer = QMessageBox.warning(
                    self,
                    "Grabline",
                    f"{url}\n\nGoogle Safe Browsing flags this as {threat}. Download anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    self.statusBar().showMessage("Ready")
                    return
            self._resolve_and_queue(url, *args)

        self._run_file_op(
            lambda: reputation.safebrowsing_check(url, key, proxy=proxy),
            done,
            lambda _e: self._resolve_and_queue(url, *args),  # a failed check never blocks
        )

    def _resolve_and_queue(
        self,
        url: str,
        page_title: str | None,
        quality: str | None,
        fallbacks: tuple[str, ...],
        headers: dict[str, str] | None,
    ) -> None:
        # The in-page quality panel already chose - skip analysis entirely and
        # let the download's single extraction do everything (formats resolve
        # at download time, the file is named from the real title). This is
        # what makes a hover-button YouTube add start as fast as any other
        # site: one extraction instead of two.
        if quality and self.resolver.smart.matches(url):
            option = option_for_label(quality)
            if option is not None:
                # The page title is often just the site name ("YouTube") -
                # queue with a placeholder and fetch the real title via the
                # site's oEmbed endpoint, which answers in well under a second.
                placeholder = naming.clean_page_title(page_title) or "Fetching title…"
                job = self.manager.add_smart_entry(
                    url,
                    placeholder,
                    option,
                    use_session=self.settings.use_browser_session,
                    session_browser=self.settings.session_browser,
                    extras={"name_from_metadata": True},
                )
                self.statusBar().showMessage(f"Queued ({option.label})", 5000)
                self.refresh()
                self._fetch_quick_title(job.id, url)
                return
        self.statusBar().showMessage(f"Analyzing {url} …")
        self._busy_begin()
        thread = work_threads.ResolveThread(
            self.resolver, url, self.settings, page_title, quality, fallbacks, headers, self
        )
        thread.resolved.connect(self._on_resolved)

        def _resolve_finished() -> None:
            self._resolve_threads.remove(thread)
            self._busy_end()
            thread.deleteLater()

        thread.finished.connect(_resolve_finished)
        self._resolve_threads.append(thread)
        thread.start()

    def _ask_dest(self) -> str | None:
        """Settings → Downloads 'Ask where to save': a folder for this add,
        "" when the setting is off (use defaults), or None on cancel."""
        if not self.settings.ask_save_dir:
            return ""
        chosen = QFileDialog.getExistingDirectory(
            self, "Save this download to", str(self.settings.download_dir)
        )
        return chosen or None

    def _fetch_quick_title(self, job_id: int, url: str) -> None:
        """Replace a queued job's placeholder name with the real video title
        (oEmbed, ~instant). Best effort - the download's own metadata naming
        corrects the file at completion regardless."""
        from app.core import titles

        proxy = self.settings.proxy

        def done(result: object) -> None:
            title = str(result) if result else ""
            if not title or self.manager.db.get_job(job_id) is None:
                return
            self.manager.db.update_job_title(job_id, title)
            self.refresh()

        self._run_file_op(lambda: titles.quick_title(url, proxy), done, lambda _e: None)

    def _on_resolved(
        self,
        resolution: Resolution,
        page_title: str | None,
        quality: str | None = None,
        fallbacks: tuple[str, ...] = (),
        headers: dict[str, str] | None = None,
    ) -> None:
        self.statusBar().showMessage("Ready")
        if resolution.kind is None:
            if fallbacks:
                # The page itself had nothing - try the stream it played.
                self.statusBar().showMessage("Page had no direct media - trying its stream …")
                self.begin_add_url(
                    fallbacks[0],
                    page_title=page_title,
                    quality=quality,
                    fallbacks=tuple(fallbacks[1:]),
                    headers=headers,
                )
                return
            QMessageBox.information(self, "Grabline", resolution.message or "No media found.")
            return
        if resolution.kind is JobKind.TORRENT:
            self.add_torrent_source(resolution.url)
            return
        if resolution.kind is JobKind.CLOUD:
            self.add_cloud_source(resolution.url)
            return
        if (
            quality
            and resolution.kind is JobKind.SMART
            and resolution.media is not None
            and (option := option_for_label(quality, resolution.media.options)) is not None
        ):
            # F1.3: the quality was already chosen in the page - no dialog.
            dest = self._ask_dest()
            if dest is None:
                return
            self.manager.add_smart(
                resolution.url,
                resolution.media,
                option,
                dest_dir=dest or None,
                use_session=self.settings.use_browser_session,
                session_browser=self.settings.session_browser,
            )
            self.statusBar().showMessage(f"Queued {resolution.media.title} ({option.label})", 5000)
            self.refresh()
            return
        dest = self._ask_dest()
        if dest is None:
            return
        if resolution.kind is JobKind.SMART and resolution.playlist is not None:
            playlist_panel = PlaylistPanel(
                resolution.playlist,
                preselect_cap=self.settings.playlist_batch_cap,
                parent=self,
            )
            if playlist_panel.exec() != PlaylistPanel.DialogCode.Accepted:
                return
            batch_option = playlist_panel.selected_option()
            for entry in playlist_panel.selected_entries():
                self.manager.add_smart_entry(
                    entry.url,
                    entry.title,
                    batch_option,
                    dest_dir=dest or None,
                    use_session=self.settings.use_browser_session,
                    session_browser=self.settings.session_browser,
                )
        elif resolution.kind is JobKind.SMART and resolution.media is not None:
            quality_panel = QualityPanel(
                resolution.media, self, default_label=self.settings.video_default_quality
            )
            if quality_panel.exec() != QualityPanel.DialogCode.Accepted:
                return
            option = quality_panel.selected_option()
            if option is None:
                return
            self.manager.add_smart(
                resolution.url,
                resolution.media,
                option,
                dest_dir=dest or None,
                subtitles=quality_panel.subtitles_config(),
                trim=quality_panel.trim_range(),
                extras=quality_panel.extras_config(),
                use_session=self.settings.use_browser_session,
                session_browser=self.settings.session_browser,
            )
        elif resolution.kind is JobKind.HLS:
            variant = None
            if quality and resolution.variants:
                # F1.3: a label from the in-page panel picks the variant too.
                wanted = quality.strip().lower()
                variant = next(
                    (v for v in resolution.variants if v.label.lower() == wanted),
                    resolution.variants[0],
                )
            elif len(resolution.variants) > 1:
                labels = [v.description for v in resolution.variants]
                choice, accepted = QInputDialog.getItem(
                    self, "Stream quality", "Pick a quality for this stream:", labels, 0, False
                )
                if not accepted:
                    return
                variant = resolution.variants[labels.index(choice)]
            elif resolution.variants:
                variant = resolution.variants[0]
            self.manager.add_hls(
                resolution.url, dest_dir=dest or None, title=page_title, variant=variant
            )
        else:
            # F1.8 name fixer: prefer Content-Disposition, then rescue ugly
            # URL names (videoplayback.mp4 …) with the page title.
            probe = resolution.probe
            filename = (
                probe.filename
                if probe is not None and probe.filename
                else naming.improved_filename(
                    resolution.url,
                    page_title,
                    probe.content_type if probe is not None else None,
                )
            )
            # Any remaining sniffed stream URLs ride along as mirrors: if this
            # URL later dies for good, the download switches to the next one.
            self.manager.add_url(
                resolution.url,
                dest_dir=dest or None,
                filename=filename,
                headers=headers or None,
                mirrors=list(fallbacks) or None,
            )
        self.refresh()

    def _selected_job_ids(self) -> list[int]:
        rows = self.table.selectionModel().selectedRows()
        ids = [self._row_job_ids[i.row()] for i in rows if 0 <= i.row() < len(self._row_job_ids)]
        # Selection can be lost when the table rebuilds mid-download; fall back
        # to the ids we remembered so the toolbar buttons keep working.
        if not ids:
            ids = [job_id for job_id in self._selected_ids if job_id in self._row_job_ids]
        return ids

    def _on_selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        self._selected_ids = {
            self._row_job_ids[i.row()] for i in rows if 0 <= i.row() < len(self._row_job_ids)
        }
        # Right-click must never pop the drawer. Qt updates the selection on
        # the right-button PRESS itself - before customContextMenuRequested
        # runs - so the suppress flag alone missed it; also gate on the live
        # mouse state.
        if self._suppress_drawer or (QApplication.mouseButtons() & Qt.MouseButton.RightButton):
            return
        # A single selection opens the detail drawer; multi/empty closes it.
        if len(self._selected_ids) == 1:
            (job_id,) = tuple(self._selected_ids)
            view = self._last_views.get(job_id)
            if view is not None:
                self._drawer.show_view(view, self._smoothed_speed(view))
        else:
            self._drawer.hide()

    def _pause_selected(self) -> None:
        for job_id in self._selected_job_ids():
            self.manager.pause(job_id)

    def _resume_selected(self) -> None:
        for job_id in self._selected_job_ids():
            self.manager.resume(job_id)

    def _cancel_selected(self) -> None:
        for job_id in self._selected_job_ids():
            self.manager.cancel(job_id)

    def _remove_selected(self) -> None:
        """Remove the selected downloads from the list, whatever state they are
        in - a running one is cancelled and dropped. Completed files stay on
        disk; a partial file is discarded with the job."""
        job_ids = self._selected_job_ids()
        for job_id in job_ids:
            self.manager.remove(job_id, force=True)
            self._removing.add(job_id)
        if job_ids:
            self.refresh()

    def _clear_completed(self) -> None:
        for view in list(self._last_views.values()):
            if view.status is JobStatus.COMPLETED:
                self.manager.remove(view.id)
        self.refresh()

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.settings.download_dir)))

    def _open_settings(self) -> None:
        if SettingsDialog(self.settings, self).exec() == SettingsDialog.DialogCode.Accepted:
            self.manager.reload_settings()
            app = QApplication.instance()
            if isinstance(app, QApplication):
                theme.apply_theme(app, self.settings.theme)

    # -------------------------------------------------------- row actions

    def _view_for_row(self, row: int) -> JobView | None:
        if 0 <= row < len(self._row_job_ids):
            return self._last_views.get(self._row_job_ids[row])
        return None

    def _show_row_menu(self, position: QPoint) -> None:
        row = self.table.rowAt(position.y())
        view = self._view_for_row(row)
        if view is None:
            return
        # Select the row for the actions below, but never pop the details
        # drawer from a right-click - that is a left-click affordance.
        self._suppress_drawer = True
        try:
            self.table.selectRow(row)
        finally:
            self._suppress_drawer = False
        menu = QMenu(self)
        file_path = Path(view.dest_dir) / view.filename
        open_file = menu.addAction("Open file")
        open_file.setEnabled(view.status is JobStatus.COMPLETED and file_path.exists())
        open_folder = menu.addAction("Open folder")
        copy_url = menu.addAction("Copy URL")
        copy_magnet = menu.addAction("Copy magnet link")
        copy_magnet.setVisible(view.kind is JobKind.TORRENT)
        redownload = menu.addAction("Download again")
        # Convert to… - every FFmpeg target that makes sense for this file,
        # grouped Video / Audio / Image, plus the tuned GIF dialog.
        ffmpeg_path = find_ffmpeg(self.settings)
        convert_menu = menu.addMenu("Convert to")
        convertible = (
            view.status is JobStatus.COMPLETED and file_path.exists() and ffmpeg_path is not None
        )
        sections = convert.targets_for(file_path) if convertible else {}
        convert_menu.setEnabled(bool(sections))
        if ffmpeg_path is None:
            convert_menu.setToolTip("Install FFmpeg in Settings → Video Downloader")
        convert_actions: dict[QAction, str] = {}
        to_gif: QAction | None = None
        if file_path.suffix.lower() in _VIDEO_SUFFIXES:
            to_gif = convert_menu.addAction("GIF…")
            convert_menu.addSeparator()
        for section, formats in sections.items():
            section_action = convert_menu.addAction(section)
            section_action.setEnabled(False)  # a small group heading
            for fmt in formats:
                if f".{fmt}" == file_path.suffix.lower():
                    continue  # converting to itself is pointless
                action = convert_menu.addAction(fmt.upper())
                convert_actions[action] = fmt
            convert_menu.addSeparator()
        limit_speed = menu.addAction("Limit speed…")
        limit_speed.setEnabled(view.status is not JobStatus.COMPLETED)
        set_connections = menu.addAction("Connections…")
        set_connections.setEnabled(view.status is not JobStatus.COMPLETED)

        done = view.status is JobStatus.COMPLETED and file_path.exists()
        copy_hash = menu.addAction("Copy SHA-256")
        copy_hash.setEnabled(done)
        verify_hash = menu.addAction("Verify checksum…")
        verify_hash.setEnabled(done)
        security_action = menu.addAction("Security check…")
        security_action.setEnabled(done)
        inspect_action = menu.addAction("Inspect…")
        inspect_action.setEnabled(view.kind in (JobKind.DIRECT, JobKind.SMART, JobKind.HLS))
        extract_here = menu.addAction("Extract here")
        extract_here.setEnabled(done and archive.is_archive(file_path))
        preview_archive = menu.addAction("Preview archive…")
        preview_archive.setEnabled(done and archive.is_archive(file_path))

        move_menu = menu.addMenu("Move to")
        favorites = self.settings.favorite_folders
        move_menu.setEnabled(done and bool(favorites))
        if not favorites:
            move_menu.setToolTip("Add favorite folders in Settings")
        move_actions = {move_menu.addAction(folder): folder for folder in favorites}
        tags_action = menu.addAction("Tags && notes…")

        queue_menu = menu.addMenu("Queue")
        default_queue_action = queue_menu.addAction("Default")
        default_queue_action.setCheckable(True)
        default_queue_action.setChecked(view.queue_id is None)
        queue_actions: dict[QAction, int] = {}
        for named_queue in self.manager.list_queues():
            queue_action = queue_menu.addAction(named_queue.name)
            queue_action.setCheckable(True)
            queue_action.setChecked(view.queue_id == named_queue.id)
            queue_actions[queue_action] = named_queue.id
        start_after = menu.addAction("Start after…")
        start_after.setEnabled(view.status in (JobStatus.QUEUED, JobStatus.PAUSED))
        start_at = menu.addAction("Start at…")
        start_at.setEnabled(view.status in (JobStatus.QUEUED, JobStatus.PAUSED))

        pending = view.status in (JobStatus.QUEUED, JobStatus.PAUSED)
        queue_menu = menu.addMenu("Move in queue")
        queue_menu.setEnabled(pending)
        move_top = queue_menu.addAction("To top")
        move_up = queue_menu.addAction("Up")
        move_down = queue_menu.addAction("Down")
        move_bottom = queue_menu.addAction("To bottom")

        menu.addSeparator()
        # Force remove: works whatever the state, mid-download included.
        remove = menu.addAction("Remove from list")
        chosen = menu.exec(self.table.viewport().mapToGlobal(position))
        if chosen is open_file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path)))
        elif chosen is open_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(view.dest_dir))
        elif chosen is copy_url:
            if self.clipboard_suppressor is not None:
                self.clipboard_suppressor(view.url)  # don't offer our own copy back
            QGuiApplication.clipboard().setText(view.url)
        elif chosen is copy_magnet:
            self._copy_magnet(view)
        elif chosen is redownload:
            self.begin_add_url(view.url, allow_duplicate=True)
        elif to_gif is not None and chosen is to_gif and ffmpeg_path is not None:
            GifDialog(ffmpeg_path, file_path, self).exec()
        elif chosen in convert_actions and ffmpeg_path is not None:
            self._convert_file(file_path, convert_actions[chosen], ffmpeg_path)
        elif chosen is limit_speed:
            self._limit_speed(view)
        elif chosen is set_connections:
            self._set_connections(view)
        elif chosen is copy_hash:
            self._copy_hash(file_path)
        elif chosen is verify_hash:
            self._verify_hash(file_path)
        elif chosen is security_action:
            SecurityDialog(file_path, view.url, self.settings, self).exec()
        elif chosen is inspect_action:
            self._inspect_job(view, file_path)
        elif chosen is extract_here:
            self._extract(file_path)
        elif chosen is preview_archive:
            self._preview_archive(file_path)
        elif chosen in move_actions:
            self._move_to(view, move_actions[chosen])
        elif chosen is tags_action:
            self._edit_tags(view)
        elif chosen is default_queue_action:
            self.manager.set_job_queue(view.id, None)
        elif chosen in queue_actions:
            self.manager.set_job_queue(view.id, queue_actions[chosen])
        elif chosen is start_after:
            self._pick_start_after(view)
        elif chosen is start_at:
            self._pick_start_at(view)
        elif chosen is move_top:
            self.manager.move_to_top(view.id)
        elif chosen is move_up:
            self.manager.move_up(view.id)
        elif chosen is move_down:
            self.manager.move_down(view.id)
        elif chosen is move_bottom:
            self.manager.move_to_bottom(view.id)
        elif chosen is remove:
            self.manager.remove(view.id, force=True)
            self._removing.add(view.id)
            self.refresh()

    def _busy_begin(self) -> None:
        self._busy_ops += 1
        self._busy_bar.show()
        self._busy_bar.set_indeterminate(True)
        self._busy_count.setText(f"{self._busy_ops} tasks" if self._busy_ops > 1 else "")
        self._busy_count.setVisible(self._busy_ops > 1)

    def _busy_end(self) -> None:
        self._busy_ops = max(0, self._busy_ops - 1)
        if self._busy_ops == 0:
            self._busy_bar.set_indeterminate(False)
            self._busy_bar.hide()
            self._busy_count.hide()
        else:
            self._busy_count.setText(f"{self._busy_ops} tasks" if self._busy_ops > 1 else "")
            self._busy_count.setVisible(self._busy_ops > 1)

    def _run_file_op(
        self,
        work: Callable[[], object],
        on_done: Callable[[object], None],
        on_error: Callable[[object], None] | None = None,
    ) -> None:
        thread = work_threads.FileOpThread(work, self)
        self._file_ops.add(thread)
        self._busy_begin()

        def deliver(result: object, error: object) -> None:
            self._busy_end()
            if error is not None:
                if on_error is not None:
                    on_error(error)
                else:
                    QMessageBox.warning(self, "Grabline", str(error))
            else:
                on_done(result)

        def cleanup() -> None:
            # Only after run() fully returned: safe to let the object go.
            self._file_ops.discard(thread)
            thread.deleteLater()

        thread.done.connect(deliver)
        thread.finished.connect(cleanup)
        thread.start()

    def _convert_file(self, path: Path, target_format: str, ffmpeg_path: str) -> None:
        """Convert a finished file with FFmpeg, silently in the background."""
        self.statusBar().showMessage(f"Converting {path.name} to {target_format.upper()} …")

        def done(result: object) -> None:
            self.statusBar().showMessage(f"Converted: {Path(str(result)).name}", 8000)

        self._run_file_op(lambda: convert.convert(ffmpeg_path, path, target_format), done)

    def _copy_hash(self, path: Path) -> None:
        self.statusBar().showMessage(f"Hashing {path.name} …")

        def done(result: object) -> None:
            QGuiApplication.clipboard().setText(str(result))
            self.statusBar().showMessage(f"SHA-256 copied for {path.name}", 6000)

        self._run_file_op(lambda: verify.hash_file(path), done)

    def _verify_hash(self, path: Path) -> None:
        expected, accepted = QInputDialog.getText(
            self,
            "Verify checksum",
            f"Paste the expected MD5 / SHA-1 / SHA-256 / SHA-512 / CRC32 for {path.name}:",
        )
        if not (accepted and expected.strip()):
            return
        self.statusBar().showMessage(f"Verifying {path.name} …")

        def done(result: object) -> None:
            if result:
                QMessageBox.information(self, "Grabline", f"{path.name} matches the checksum.")
            else:
                QMessageBox.warning(self, "Grabline", f"{path.name} does NOT match the checksum.")

        self._run_file_op(lambda: verify.verify_file(path, expected.strip()), done)

    def _archive_work(
        self,
        path: Path,
        members: list[str] | None = None,
        passwords: tuple[str, ...] = (),
        *,
        scan: bool = True,
    ) -> Callable[[], object]:
        """Extraction work for a background thread: the optional virus scan
        first, then the extraction itself. A detection does not block - it
        raises _ScanFlagged so the caller can ask the user whether to go on."""

        def work() -> object:
            pref = self.settings.scanner_pref
            if (
                scan
                and self.settings.scan_before_extract
                and virusscan.find_scanner(pref) is not None
            ):
                result = virusscan.scan(path, pref)
                if not result.clean:
                    raise _ScanFlagged(result.scanner, result.detail)
            dest = path.parent / path.stem if self.settings.extract_to_subfolder else None
            extracted = archive.extract(path, dest, passwords=passwords, members=members)
            if self.settings.delete_archive_after_extract and members is None:
                # Only after a full, clean extraction - never on partial picks.
                path.unlink(missing_ok=True)
            return extracted

        return work

    def _extract(
        self,
        path: Path,
        members: list[str] | None = None,
        new_password: str | None = None,
        *,
        scan: bool = True,
    ) -> None:
        passwords = self.settings.archive_passwords
        if new_password:
            passwords = (new_password, *passwords)
        self.statusBar().showMessage(f"Extracting {path.name} …")

        def done(result: object) -> None:
            if new_password:
                # Remember what worked - next time it's tried automatically.
                self.settings.archive_passwords = (
                    new_password,
                    *self.settings.archive_passwords,
                )
            self.statusBar().showMessage(f"Extracted to {Path(str(result)).name}", 6000)

        def failed(error: object) -> None:
            if isinstance(error, _ScanFlagged):
                detail = f"\n\n{error.detail}" if error.detail else ""
                answer = QMessageBox.warning(
                    self,
                    "Grabline",
                    f"{error.scanner} flagged {path.name}.{detail}\n\n"
                    "Antivirus false positives are common. Extract it anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer == QMessageBox.StandardButton.Yes:
                    self._extract(path, members, new_password, scan=False)
                return
            if isinstance(error, archive.PasswordRequired):
                password, accepted = QInputDialog.getText(
                    self,
                    "Archive password",
                    f"{path.name} is password-protected. Password:",
                    QLineEdit.EchoMode.Password,
                )
                if accepted and password:
                    self._extract(path, members, new_password=password)
                return
            QMessageBox.warning(self, "Grabline", str(error))

        self._run_file_op(self._archive_work(path, members, passwords, scan=scan), done, failed)

    def _preview_archive(self, path: Path) -> None:
        self.statusBar().showMessage(f"Reading {path.name} …")

        def opened(result: object) -> None:
            self.statusBar().clearMessage()
            entries = cast("tuple[archive.ArchiveEntry, ...]", result)
            dialog = ArchiveDialog(path.name, entries, self)
            if dialog.exec() == ArchiveDialog.DialogCode.Accepted:
                self._extract(path, members=dialog.selected_members())

        self._run_file_op(lambda: archive.list_entries(path), opened)

    def _move_to(self, view: JobView, folder: str) -> None:
        self.statusBar().showMessage(f"Moving {view.filename} …")

        def done(result: object) -> None:
            self.statusBar().showMessage(f"Moved to {result}", 6000)
            self.refresh()

        self._run_file_op(lambda: self.manager.move_job_file(view.id, folder), done)

    def _edit_tags(self, view: JobView) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Tags & notes - {view.display_name}")
        dialog.setMinimumWidth(420)
        form = QFormLayout(dialog)
        tags_edit = QLineEdit(view.tags)
        tags_edit.setPlaceholderText("comma, separated, labels")
        form.addRow("Tags:", tags_edit)
        notes_edit = QPlainTextEdit(view.notes)
        notes_edit.setPlaceholderText("Anything worth remembering about this download.")
        form.addRow("Notes:", notes_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.manager.set_job_tags(view.id, tags_edit.text())
            self.manager.set_job_notes(view.id, notes_edit.toPlainText())
            self.refresh()

    def _find_duplicates(self) -> None:
        """Hash-compare every completed download and offer to delete the
        extra byte-identical copies (keeping one of each)."""
        owners: dict[Path, int] = {}
        for view in self._last_views.values():
            if view.status is JobStatus.COMPLETED:
                owners[Path(view.dest_dir) / view.filename] = view.id
        if not owners:
            QMessageBox.information(self, "Grabline", "No completed downloads to compare.")
            return
        self.statusBar().showMessage("Comparing files …")

        def done(result: object) -> None:
            self.statusBar().showMessage("Ready")
            groups = cast("list[list[Path]]", result)
            if not groups:
                QMessageBox.information(self, "Grabline", "No duplicate files found.")
                return
            dialog = DupesDialog(groups, self)
            if dialog.exec() != DupesDialog.DialogCode.Accepted:
                return
            doomed = dialog.selected_paths()
            if not doomed:
                return
            answer = QMessageBox.warning(
                self,
                "Grabline",
                f"Permanently delete {len(doomed)} duplicate file(s)? One copy of each is kept.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            for path in doomed:
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    QMessageBox.warning(self, "Grabline", f"Could not delete {path.name}: {exc}")
                    continue
                job_id = owners.get(path)
                if job_id is not None:
                    self.manager.remove(job_id)
            self.statusBar().showMessage(f"Removed {len(doomed)} duplicate file(s)", 6000)
            self.refresh()

        self._run_file_op(lambda: dupes.find_duplicates(list(owners)), done)

    # ------------------------------------------------------------ dashboard

    def _open_dashboard(self) -> None:
        DashboardDialog(self.manager, self).exec()

    # ------------------------------------------------------------- security

    def _advisory_scan(self, view: JobView, file_path: Path) -> None:
        """Opt-in post-download check. Runs the report off-thread; only speaks
        up if something is worth a look - never blocks, never deletes."""
        if not file_path.exists():
            return
        allowed = self.settings.scan_extensions
        if allowed:
            wanted = {e.strip().lower().lstrip(".") for e in allowed.split(",") if e.strip()}
            if file_path.suffix.lower().lstrip(".") not in wanted:
                return  # the user scoped scanning to specific types
        key = self.settings.virustotal_key
        proxy = self.settings.proxy
        pref = self.settings.scanner_pref

        def work() -> object:
            return security.check_file(
                file_path, url=view.url, virustotal_key=key, proxy=proxy, scanner_pref=pref
            )

        def done(result: object) -> None:
            report = cast("security.SecurityReport", result)
            if report.level is security.Risk.WARNING:
                # Only a real warning interrupts; the file is already saved.
                answer = QMessageBox.warning(
                    self,
                    "Grabline - security",
                    f"{view.display_name}\n\n"
                    + "\n".join(f"• {f}" for f in report.findings)
                    + "\n\nThe file is saved and usable - this is advice only. "
                    "Open the full report?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer == QMessageBox.StandardButton.Yes:
                    SecurityDialog(file_path, view.url, self.settings, self).exec()
            elif report.level is security.Risk.CAUTION:
                self.statusBar().showMessage(f"{view.display_name}: {report.findings[0]}", 8000)

        self._run_file_op(work, done, lambda _e: None)  # a scan error is silent

    # ------------------------------------------------------------ inspector

    def _inspect_url_prompt(self) -> None:
        url, accepted = QInputDialog.getText(self, "Inspect URL", "URL to inspect:")
        if accepted and url.strip():
            InspectorDialog(url.strip(), proxy=self.settings.proxy, parent=self).exec()

    def _inspect_job(self, view: JobView, file_path: Path) -> None:
        mirrors = ()
        job = self.manager.db.get_job(view.id)
        if job is not None:
            mirrors = tuple(job.options.get("mirrors") or ())
        checksum_work = None
        if view.status is JobStatus.COMPLETED and file_path.exists():
            checksum_work = lambda: verify.hash_file(file_path)  # noqa: E731
        InspectorDialog(
            view.url,
            mirrors=mirrors,
            checksum_work=checksum_work,
            proxy=self.settings.proxy,
            parent=self,
        ).exec()

    # --------------------------------------------------------------- queues

    def _open_queue_manager(self) -> None:
        QueueManagerDialog(self.manager, self).exec()
        self.refresh()

    def _pick_start_after(self, view: JobView) -> None:
        """Job dependency: hold this download until a chosen one finishes."""
        others = [
            v
            for v in self._last_views.values()
            if v.id != view.id and v.status is not JobStatus.COMPLETED
        ]
        if not others:
            QMessageBox.information(self, "Grabline", "No other unfinished downloads to wait for.")
            return
        labels = ["(nothing - start normally)"] + [v.display_name for v in others]
        choice, accepted = QInputDialog.getItem(
            self,
            "Start after",
            f"Start {view.display_name} only after:",
            labels,
            editable=False,
        )
        if not accepted:
            return
        index = labels.index(choice)
        self.manager.set_job_after(view.id, None if index == 0 else others[index - 1].id)

    def _pick_start_at(self, view: JobView) -> None:
        """Download later: hold this download until a chosen date and time."""
        from PySide6.QtCore import QDateTime
        from PySide6.QtWidgets import QDateTimeEdit

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Start at - {view.display_name}")
        form = QFormLayout(dialog)
        when_edit = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        when_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        when_edit.setCalendarPopup(True)
        form.addRow("Start no earlier than:", when_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Reset
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Reset).setText("Start normally")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        buttons.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(
            lambda: dialog.done(2)
        )
        form.addRow(buttons)
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            from datetime import datetime as _datetime

            when = cast("_datetime", when_edit.dateTime().toPython())
            self.manager.set_job_start_at(view.id, when)
            self.statusBar().showMessage(
                f"{view.display_name} starts {when_edit.dateTime().toString('yyyy-MM-dd HH:mm')}",
                6000,
            )
        elif result == 2:
            self.manager.set_job_start_at(view.id, None)

    # ---------------------------------------------------------------- cloud

    def _add_cloud(self) -> None:
        url = prompt_cloud_url(self)
        if url:
            self.add_cloud_source(url)

    def add_cloud_source(self, url: str) -> None:
        """Queue a cloud protocol download. A URL ending in '/' is treated as a
        folder: its files are listed and offered in a picker."""
        if url.rstrip().endswith("/"):
            self.statusBar().showMessage("Listing remote folder …")

            def listed(result: object) -> None:
                self.statusBar().clearMessage()
                files = cast("list[cloud_engine.RemoteFile]", result)
                if not files:
                    QMessageBox.information(self, "Grabline", "That folder is empty.")
                    return
                dialog = CloudFolderDialog(url, files, self)
                if dialog.exec() != CloudFolderDialog.DialogCode.Accepted:
                    return
                for file_url in dialog.selected_urls():
                    self.manager.add_cloud(file_url)
                self.statusBar().showMessage(f"Queued {len(dialog.selected_urls())} file(s)", 5000)
                self.refresh()

            self._run_file_op(lambda: self.manager.list_cloud_folder(url), listed)
            return
        self.manager.add_cloud(url)
        self.statusBar().showMessage("Queued cloud download", 5000)
        self.refresh()

    # ------------------------------------------------------------- torrents

    def _copy_magnet(self, view: JobView) -> None:
        if view.url.lower().startswith("magnet:"):
            magnet = view.url
            if self.clipboard_suppressor is not None:
                self.clipboard_suppressor(magnet)
            QGuiApplication.clipboard().setText(magnet)
            self.statusBar().showMessage("Magnet link copied", 4000)
            return

        def done(result: object) -> None:
            magnet = str(result)
            if self.clipboard_suppressor is not None:
                self.clipboard_suppressor(magnet)
            QGuiApplication.clipboard().setText(magnet)
            self.statusBar().showMessage("Magnet link copied", 4000)

        self._run_file_op(
            lambda: torrent_engine.magnet_from_torrent(
                torrent_engine.fetch_torrent_bytes(view.url, proxy=self.settings.proxy)
            ),
            done,
        )

    def _add_torrent_file(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Add torrent", "", "Torrents (*.torrent);;All files (*)"
        )
        if chosen:
            self.add_torrent_source(chosen)

    def add_torrent_source(self, source: str) -> None:
        """Open the add-torrent dialog for a magnet link, a local .torrent
        path, or an http(s) .torrent URL - the one entry point used by the
        menu, the resolver, drag-and-drop, and 'open with Grabline'."""
        default_dir = self.settings.torrent_dir or self.settings.download_dir
        if source.lower().startswith("magnet:"):
            name = torrent_engine.magnet_display_name(source) or "Magnet link"
            self._open_add_torrent(source, name, None, default_dir)
            return
        self.statusBar().showMessage("Reading torrent …")

        def loaded(result: object) -> None:
            self.statusBar().clearMessage()
            meta = cast("torrent_engine.TorrentMeta", result)
            self._open_add_torrent(source, meta.name, meta, default_dir)

        self._run_file_op(
            lambda: torrent_engine.parse_torrent(
                torrent_engine.fetch_torrent_bytes(source, proxy=self.settings.proxy)
            ),
            loaded,
        )

    def _open_add_torrent(self, source: str, name: str, meta: object, default_dir: Path) -> None:
        dialog = AddTorrentDialog(
            name,
            cast("torrent_engine.TorrentMeta | None", meta),
            default_dir,
            sequential_default=self.settings.torrent_sequential,
            parent=self,
        )
        if dialog.exec() != AddTorrentDialog.DialogCode.Accepted:
            return
        self.manager.add_torrent(
            source, dest_dir=dialog.dest_dir() or default_dir, name=name, options=dialog.options()
        )
        self.statusBar().showMessage(f"Queued torrent {name}", 5000)
        self.refresh()

    def _create_torrent(self) -> None:
        dialog = CreateTorrentDialog(self)
        if self.settings.torrent_trackers:  # Settings → Torrent: default trackers
            dialog.trackers_edit.setPlainText("\n".join(self.settings.torrent_trackers))
        if dialog.exec() != CreateTorrentDialog.DialogCode.Accepted:
            return
        source = dialog.source()
        target, _ = QFileDialog.getSaveFileName(
            self, "Save torrent as", f"{source.name}.torrent", "Torrents (*.torrent)"
        )
        if not target:
            return
        self.statusBar().showMessage("Hashing pieces …")

        def work() -> object:
            data = torrent_engine.create_torrent_file(
                source,
                trackers=dialog.trackers(),
                web_seeds=dialog.web_seeds(),
                comment=dialog.comment(),
                private=dialog.private(),
            )
            Path(target).write_bytes(data)
            return target

        def done(result: object) -> None:
            self.statusBar().showMessage(f"Torrent created: {result}", 8000)

        self._run_file_op(work, done)

    def _search_torrents(self) -> None:
        template = self.settings.torrent_search_url
        if "%s" not in template:
            QMessageBox.information(
                self,
                "Grabline",
                "Set a search URL first (Settings → Torrent), e.g.\n"
                "https://example.com/search?q=%s",
            )
            return
        query, accepted = QInputDialog.getText(self, "Search torrents", "Search for:")
        if accepted and query.strip():
            from urllib.parse import quote

            QDesktopServices.openUrl(QUrl(template.replace("%s", quote(query.strip()))))

    def _poll_rss(self) -> None:
        """Check the RSS feeds and queue new matching torrent items."""
        if self._shutting_down:  # the 15s singleShot outlives timer.stop()
            return
        feeds = self.settings.rss_feeds
        if not feeds:
            return
        seen = set(self.settings.rss_seen)
        proxy = self.settings.proxy

        def work() -> object:
            found: list[tuple[str, str]] = []  # (guid, link)
            for line in feeds:
                url, needle = rss.parse_feed_line(line)
                try:
                    items = rss.fetch_feed(url, proxy=proxy)
                except DownloadError:
                    continue  # a dead feed shouldn't spam errors every poll
                for item in rss.matching_items(items, needle):
                    if item.guid not in seen and torrent_engine.is_torrent_source(item.link):
                        found.append((item.guid, item.link))
            return found

        def done(result: object) -> None:
            found = cast("list[tuple[str, str]]", result)
            if not found:
                return
            for guid, link in found:
                self.manager.add_torrent(link)
                seen.add(guid)
            self.settings.rss_seen = list(seen)
            self.statusBar().showMessage(f"RSS: queued {len(found)} torrent(s)", 6000)
            self.refresh()

        self._run_file_op(work, done, lambda _e: None)  # quiet - it's a background poll

    def _set_connections(self, view: JobView) -> None:
        connections, accepted = QInputDialog.getInt(
            self,
            "Connections",
            f"Parallel connections for this download\n"
            f"(0 = automatic; beyond ~32 servers often throttle)  -  {view.display_name}",
            value=0,
            minValue=0,
            maxValue=128,
        )
        if accepted:
            self.manager.set_job_connections(view.id, connections)

    def _limit_speed(self, view: JobView) -> None:
        kbps, accepted = QInputDialog.getInt(
            self,
            "Limit speed",
            f"Max speed for this download in KB/s\n(0 = no limit)  -  {view.display_name}",
            value=view.speed_limit_kbps,
            minValue=0,
            maxValue=1_000_000,
            step=256,
        )
        if accepted:
            self.manager.set_job_speed(view.id, kbps)

    # ------------------------------------------------------------- refresh

    def refresh(self) -> None:
        if self._shutting_down:
            return
        views = self.manager.snapshot()
        # Optimistic removal: a force-removed running job stays in the DB until
        # its worker actually stops - hide it from the list right away.
        present = {view.id for view in views}
        self._removing &= present
        if self._removing:
            views = [view for view in views if view.id not in self._removing]
        self._detect_transitions(views)
        self._measure_speeds(views)
        self._update_speed_line(views)
        self._last_views = {view.id: view for view in views}
        ids = [view.id for view in views]
        if ids != self._row_job_ids:
            self._rebuild_rows(views)
            self._restore_selection()
        for row, view in enumerate(views):
            self._update_row(row, view)
        self._update_filter_counts(views)
        self._update_status_info(views)
        self._apply_filter()
        self._empty_label.setGeometry(self.table.viewport().rect())
        self._empty_label.setVisible(not views)
        # Keep an open detail drawer live.
        drawer_id = self._drawer.current_id()
        if self._drawer.isVisible() and drawer_id is not None:
            live = self._last_views.get(drawer_id)
            if live is not None:
                self._drawer.show_view(live, self._smoothed_speed(live))
            else:
                self._drawer.hide()

    def _update_filter_counts(self, views: list[JobView]) -> None:
        counts = {
            "all": len(views),
            "active": sum(
                1
                for v in views
                if v.status in (JobStatus.DOWNLOADING, JobStatus.QUEUED, JobStatus.PAUSED)
            ),
            "completed": sum(1 for v in views if v.status is JobStatus.COMPLETED),
            "failed": sum(1 for v in views if v.status in (JobStatus.FAILED, JobStatus.CANCELLED)),
        }
        labels = {"all": "All", "active": "Active", "completed": "Completed", "failed": "Failed"}
        for key, btn in self._filter_buttons.items():
            btn.setText(f"{labels[key]}  {counts[key]}")
        self._clear_completed_btn.setVisible(counts["completed"] > 0)

    def _update_status_info(self, views: list[JobView]) -> None:
        active = sum(1 for v in views if v.status is JobStatus.DOWNLOADING)
        done = sum(1 for v in views if v.status is JobStatus.COMPLETED)
        self._status_info.setText(
            f"{len(views)} items · {active} active · {done} completed"
            f"     Grabline v{__version__} · No telemetry"
        )

    def _restore_selection(self) -> None:
        """Re-select the remembered jobs after a rebuild so the toolbar keeps
        acting on what the user picked (multi-selection preserved)."""
        present = [job_id for job_id in self._selected_ids if job_id in self._row_job_ids]
        if not present:
            return
        model = self.table.model()
        selection = QItemSelection()
        for job_id in present:
            row = self._row_job_ids.index(job_id)
            selection.select(model.index(row, 0), model.index(row, len(_COLUMNS) - 1))
        self.table.blockSignals(True)
        self.table.selectionModel().select(
            selection, QItemSelectionModel.SelectionFlag.ClearAndSelect
        )
        self.table.blockSignals(False)

    def _update_speed_line(self, views: list[JobView]) -> None:
        """The toolbar total: the sum of the per-download speeds already
        measured this poll. Summing settled rates (rather than differencing a
        total that drops every time a download finishes) keeps it steady."""
        total = sum(self._speeds.get(v.id, 0.0) for v in views if v.status is JobStatus.DOWNLOADING)
        self.speed_line.push(total)
        self._total_speed.setText(motion.fmt_speed(total))

    def _detect_transitions(self, views: list[JobView]) -> None:
        """Notify on newly finished downloads and when the queue drains."""
        active_now = False
        for view in views:
            previous = self._prev_status.get(view.id)
            if view.status in (JobStatus.DOWNLOADING, JobStatus.QUEUED):
                active_now = True
            if (
                previous is not None
                and previous is not JobStatus.FAILED
                and view.status is JobStatus.FAILED
            ):
                self.job_failed.emit(view.display_name, view.error or "download failed")
            just_completed = (
                previous is not None
                and previous is not JobStatus.COMPLETED
                and view.status is JobStatus.COMPLETED
            )
            if just_completed:
                file_path = Path(view.dest_dir) / view.filename
                self.job_completed.emit(view.display_name, str(file_path))
                if self.settings.scan_downloads and view.id not in self._scanned:
                    self._scanned.add(view.id)
                    self._advisory_scan(view, file_path)
                if self.settings.auto_open_folder:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(view.dest_dir))
                if (
                    self.settings.auto_extract
                    and view.id not in self._auto_extracted
                    and archive.is_archive(file_path)
                    and file_path.exists()
                ):
                    self._auto_extracted.add(view.id)
                    self.statusBar().showMessage(f"Extracting {file_path.name} …")

                    # Failures stay in the status bar - a modal mid-queue would
                    # interrupt; the row menu's Preview archive… can prompt.
                    def extract_failed(error: object, name: str = file_path.name) -> None:
                        self.statusBar().showMessage(f"Did not extract {name}: {error}", 10000)

                    self._run_file_op(
                        self._archive_work(file_path, passwords=self.settings.archive_passwords),
                        lambda r: self.statusBar().showMessage(
                            f"Extracted {Path(str(r)).name}", 6000
                        ),
                        extract_failed,
                    )
        if self._was_active and not active_now:
            self.queue_drained.emit()
        self._was_active = active_now
        self._prev_status = {view.id: view.status for view in views}

    def _apply_filter(self) -> None:
        needle = self.search_box.text().strip().lower()
        statuses = _FILTER_STATUSES.get(self._filter, ())
        for row in range(self.table.rowCount()):
            view = self._view_for_row(row)
            matches_search = not needle or (
                view is not None
                and (
                    needle in view.display_name.lower()
                    or needle in view.url.lower()
                    or needle in view.tags.lower()
                    or needle in view.notes.lower()
                )
            )
            matches_tab = not statuses or (view is not None and view.status in statuses)
            self.table.setRowHidden(row, not (matches_search and matches_tab))

    def _rebuild_rows(self, views: list[JobView]) -> None:
        self.table.setRowCount(len(views))
        self._row_job_ids = [view.id for view in views]
        self._progress_bars.clear()
        self._pills.clear()
        for row, view in enumerate(views):
            # icon
            icon_item = QTableWidgetItem()
            icon_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, _COL_ICON, icon_item)
            right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            num_font = design.numeric_font(self.table.font())
            for col in (_COL_NAME, _COL_SIZE, _COL_SPEED, _COL_ETA):
                item = QTableWidgetItem("")
                if col != _COL_NAME:  # numbers: right-aligned, tabular digits
                    item.setTextAlignment(right)
                    item.setFont(num_font)
                self.table.setItem(row, col, item)
            bar = motion.SmoothProgressBar()
            self.table.setCellWidget(row, _COL_PROGRESS, self._pad(bar))
            self._progress_bars[view.id] = bar
            pill = components.StatusPill(view.status.value)
            self.table.setCellWidget(row, _COL_STATUS, self._pad(pill))
            self._pills[view.id] = pill

    @staticmethod
    def _pad(widget: QWidget) -> QWidget:
        """Wrap a cell widget with a little horizontal padding so it doesn't
        touch the gridless cell edges. The holder is transparent (see the
        #CellHolder rule) so row hover/selection paint straight through."""
        holder = QWidget()
        holder.setObjectName("CellHolder")
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.addWidget(widget)
        return holder

    def _cell(self, row: int, column: int) -> QTableWidgetItem:
        item = self.table.item(row, column)
        assert item is not None  # _rebuild_rows creates every cell
        return item

    def _update_row(self, row: int, view: JobView) -> None:
        p = theme.current()
        # type icon
        ext = view.filename
        name = icons.type_icon_name(
            view.kind.value if view.kind.value in ("torrent", "cloud") else ext
        )
        self._cell(row, _COL_ICON).setIcon(icons.svg_icon(name, self._type_color(view)))

        name_item = self._cell(row, _COL_NAME)
        # No URL tooltip - hover text was clutter; the details drawer has it.
        # Small suffix markers surface tags and notes at a glance.
        markers = ""
        if view.tags:
            markers += "  🏷"
        if view.notes:
            markers += "  📝"
        name_item.setText(view.display_name + markers)
        if markers:
            name_item.setToolTip(
                (f"Tags: {view.tags}\n" if view.tags else "") + ("Has notes" if view.notes else "")
            )
        else:
            name_item.setToolTip("")

        self._cell(row, _COL_SIZE).setText(human_bytes(view.total_size) if view.total_size else "—")

        bar = self._progress_bars.get(view.id)
        if bar is not None:
            if view.total_size:
                bar.set_value(view.downloaded / view.total_size)
            elif view.status is JobStatus.DOWNLOADING:
                bar.set_indeterminate(True)
            else:
                bar.set_value(1.0 if view.status is JobStatus.COMPLETED else 0.0)
            bar.set_color(design.status_color(p, view.status.value))

        speed = self._smoothed_speed(view)
        speed_item = self._cell(row, _COL_SPEED)
        speed_item.setText(motion.fmt_speed(speed) if view.status is JobStatus.DOWNLOADING else "—")
        # Speed is data, not an action: primary text while moving, muted idle.
        speed_item.setForeground(QColor(p.text if speed > 0 else p.text3))

        eta = "—"
        if view.status is JobStatus.DOWNLOADING and speed > 1 and view.total_size:
            eta = motion.fmt_eta((view.total_size - view.downloaded) / speed)
        self._cell(row, _COL_ETA).setText(eta)

        pill = self._pills.get(view.id)
        if pill is not None:
            pill.set_status(view.status.value)
            pill.setToolTip(view.error or "")

    @staticmethod
    def _type_color(view: JobView) -> str:
        p = theme.current()
        return {
            JobKind.TORRENT: p.accent,
            JobKind.CLOUD: p.g_ndown,
            JobKind.SMART: p.g_ndown,
            JobKind.HLS: p.g_ndown,
        }.get(view.kind, p.text2)

    def _measure_speeds(self, views: list[JobView]) -> None:
        """Measure every running download's speed once per poll.

        Exactly once: the rows, the drawer and the toolbar total all read the
        cached numbers afterwards. Measuring per caller used to feed a second,
        zero-elapsed sample into the selected download's smoother every poll,
        which dragged its readout to zero.
        """
        now = time.monotonic()
        running = {v.id for v in views if v.status is JobStatus.DOWNLOADING}
        for job_id in list(self._speed_smoothers):
            if job_id not in running:
                self._speed_smoothers.pop(job_id, None)  # a finished job starts fresh
        speeds: dict[int, float] = {}
        for view in views:
            if view.id in running:
                smoother = self._speed_smoothers.setdefault(view.id, motion.SpeedSmoother())
                speeds[view.id] = smoother.push_total(now, view.downloaded)
            else:
                speeds[view.id] = 0.0
        self._speeds = speeds

    def _smoothed_speed(self, view: JobView) -> float:
        """This download's speed as measured by :meth:`_measure_speeds` for the
        current poll."""
        return self._speeds.get(view.id, 0.0)

    # ---------------------------------------------------------- drag & drop

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        data = event.mimeData()
        if data.hasUrls() or data.hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        data = event.mimeData()
        # A .torrent file dropped from the file manager opens as a torrent.
        for dropped in data.urls():
            local = dropped.toLocalFile()
            if local and local.lower().endswith(".torrent"):
                event.acceptProposedAction()
                self.add_torrent_source(local)
                return
        text_parts = [url.toString() for url in data.urls()]
        if data.hasText():
            text_parts.append(data.text())
        magnets = [p for p in text_parts[-1:] if p.strip().lower().startswith("magnet:")]
        if magnets:
            event.acceptProposedAction()
            self.add_torrent_source(magnets[0].strip())
            return
        clouds = [p for p in text_parts[-1:] if cloud_engine.is_cloud_scheme(p.strip())]
        if clouds:
            event.acceptProposedAction()
            self.add_cloud_source(clouds[0].strip())
            return
        urls = expand_all(extract_urls("\n".join(text_parts)))
        if not urls:
            return
        event.acceptProposedAction()
        if len(urls) > 1:
            self._run_batch(urls)
        else:
            self.begin_add_url(urls[0])

    # --------------------------------------------------------------- close

    def changeEvent(self, event: QEvent) -> None:
        # Minimize-to-tray (Settings → General): hide instead of the taskbar.
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self.close_to_tray  # tray is available
            and self.settings.minimize_to_tray
        ):
            QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    def _active_download_count(self) -> int:
        return sum(1 for v in self._last_views.values() if v.status is JobStatus.DOWNLOADING)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.close_to_tray and self.settings.close_to_tray and self.isVisible():
            event.ignore()
            self.hide()
            return
        active = self._active_download_count()
        if active and self.settings.confirm_exit_active:
            answer = QMessageBox.question(
                self,
                "Grabline",
                f"{active} download(s) are still running - quit anyway?\n"
                "(Progress is saved; they resume next launch.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()
