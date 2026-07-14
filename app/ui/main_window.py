"""The queue window (F0.4) and the add-URL flow: paste a URL, the resolver
routes it in a background thread, and Smart Engine hits get the quality panel.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import cast

from PySide6.QtCore import (
    QItemSelection,
    QItemSelectionModel,
    QPoint,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
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
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.core import archive, crawler, dupes, listio, naming, rss, update, verify, virusscan
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
from app.ui import theme
from app.ui.archive_dialog import ArchiveDialog
from app.ui.batch_dialog import BatchImportDialog, BatchImportThread
from app.ui.cloud_dialog import CloudFolderDialog, prompt_cloud_url
from app.ui.dupes_dialog import DupesDialog
from app.ui.format import human_bytes
from app.ui.gallery_panel import GalleryPanel
from app.ui.gif_dialog import GifDialog
from app.ui.link_panel import LinkPanel
from app.ui.playlist_panel import PlaylistPanel
from app.ui.quality_panel import QualityPanel
from app.ui.queue_dialog import QueueManagerDialog
from app.ui.settings_dialog import SettingsDialog
from app.ui.setup_dialog import SetupDialog
from app.ui.sparkline import Sparkline
from app.ui.torrent_dialog import AddTorrentDialog, CreateTorrentDialog

_COLUMNS = ("Name", "Size", "Progress", "Speed", "Status")
_VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}

#: Dashboard tabs: label -> the statuses it shows (empty tuple = everything).
_TABS: tuple[tuple[str, tuple[JobStatus, ...]], ...] = (
    ("All", ()),
    ("Active", (JobStatus.DOWNLOADING, JobStatus.QUEUED, JobStatus.PAUSED)),
    ("Completed", (JobStatus.COMPLETED,)),
    ("Failed", (JobStatus.FAILED, JobStatus.CANCELLED)),
)


class _ResolveThread(QThread):
    # Resolution, page_title (str|None), quality label (str|None, F1.3),
    # fallback URLs (tuple[str,...]), extra HTTP headers (dict[str,str])
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
    ) -> None:
        super().__init__()
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


class _FileOpThread(QThread):
    """Runs a slow file operation (hashing, extraction) off the UI thread."""

    done = Signal(object, object)  # result, error Exception | None

    def __init__(self, work: Callable[[], object]) -> None:
        super().__init__()
        self._work = work

    def run(self) -> None:
        try:
            self.done.emit(self._work(), None)
        except (OSError, DownloadError, ValueError) as exc:
            # The exception object itself, so handlers can distinguish
            # PasswordRequired from a plain failure; str(error) still works.
            self.done.emit(None, exc)


class MainWindow(QMainWindow):
    #: Emitted when a download finishes (display name) and when the last
    #: active/queued download drains, so __main__ can toast and act.
    job_completed = Signal(str)
    queue_drained = Signal()

    def __init__(self, manager: DownloadManager, settings: Settings) -> None:
        super().__init__()
        self.manager = manager
        self.settings = settings
        self.resolver = Resolver()
        self.close_to_tray = False
        self.setWindowTitle("Grabline")
        self.resize(880, 440)
        self.setAcceptDrops(True)  # drop URLs (or text with URLs) onto the window

        self._build_menu()

        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        for label, handler in (
            ("Add URL", self._add_url),
            ("Import Links", self._import_links),
            ("Pause", self._pause_selected),
            ("Resume", self._resume_selected),
            ("Cancel", self._cancel_selected),
            ("Remove", self._remove_selected),
            ("Open Folder", self._open_folder),
            ("Settings", self._open_settings),
        ):
            action = QAction(label, self)
            action.triggered.connect(handler)
            toolbar.addAction(action)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search downloads…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setMaximumWidth(220)
        self.search_box.textChanged.connect(lambda _text: self._apply_filter())
        toolbar.addWidget(self.search_box)
        self.speed_line = Sparkline()
        toolbar.addWidget(self.speed_line)

        self.tabs = QTabBar()
        for label, _statuses in _TABS:
            self.tabs.addTab(label)
        self.tabs.currentChanged.connect(lambda _i: self._apply_filter())

        self.table = QTableWidget(0, len(_COLUMNS), self)
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # Extended: Ctrl/Shift-click to pick many rows and pause/remove them
        # together (clean up finished downloads in one go).
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_row_menu)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 320)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 120)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        container_layout.addWidget(self.tabs)
        container_layout.addWidget(self.table)
        self.setCentralWidget(container)
        self.statusBar().showMessage("Ready")

        self._row_job_ids: list[int] = []
        self._last_views: dict[int, JobView] = {}
        self._rates: dict[int, tuple[float, int]] = {}
        self._speed_ema: dict[int, float] = {}
        self._selected_ids: set[int] = set()
        self.clipboard_suppressor: Callable[[str], None] | None = None
        self._prev_status: dict[int, JobStatus] = {}
        self._was_active = False
        self._agg: tuple[float, int] | None = None  # (monotonic time, total bytes)
        self._agg_ema: float | None = None
        self._resolve_threads: list[_ResolveThread] = []
        self._file_ops: set[_FileOpThread] = set()
        self._auto_extracted: set[int] = set()
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

    def _build_menu(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        for label, handler in (
            ("Add URL…", self._add_url),
            ("Add Torrent File…", self._add_torrent_file),
            ("Add Cloud Download…", self._add_cloud),
            ("Import Links…", self._import_links),
            ("Grab Site…", self._grab_site),
        ):
            action = QAction(label, self)
            action.triggered.connect(handler)
            file_menu.addAction(action)
        file_menu.addSeparator()
        for label, handler in (
            ("Create Torrent…", self._create_torrent),
            ("Search Torrents…", self._search_torrents),
        ):
            action = QAction(label, self)
            action.triggered.connect(handler)
            file_menu.addAction(action)
        file_menu.addSeparator()
        for label, handler in (
            ("Import List…", self._import_list),
            ("Export List…", self._export_list),
        ):
            action = QAction(label, self)
            action.triggered.connect(handler)
            file_menu.addAction(action)
        file_menu.addSeparator()
        queue_manager = QAction("Queue Manager…", self)
        queue_manager.triggered.connect(self._open_queue_manager)
        file_menu.addAction(queue_manager)
        clear_done = QAction("Clear Completed", self)
        clear_done.triggered.connect(self._clear_completed)
        file_menu.addAction(clear_done)
        find_dupes = QAction("Find Duplicate Files…", self)
        find_dupes.triggered.connect(self._find_duplicates)
        file_menu.addAction(find_dupes)
        file_menu.addSeparator()
        setup = QAction("Browser Setup…", self)
        setup.triggered.connect(self.open_setup)
        file_menu.addAction(setup)
        updates = QAction("Check for Updates…", self)
        updates.triggered.connect(lambda: self.check_for_updates(quiet=False))
        file_menu.addAction(updates)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit)
        file_menu.addAction(quit_action)

    def _quit(self) -> None:
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.quit()

    def open_setup(self) -> None:
        SetupDialog(self).exec()

    def _poll_handoffs(self) -> None:
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
            if result is not None:
                tag, url = cast("tuple[str, str]", result)
                answer = QMessageBox.question(
                    self,
                    "Grabline",
                    f"Grabline {tag} is available (you have {__version__}).\n"
                    "Open the download page?",
                )
                if answer == QMessageBox.StandardButton.Yes:
                    QDesktopServices.openUrl(QUrl(url))
            elif not quiet:
                QMessageBox.information(self, "Grabline", "You have the latest version.")

        self._run_file_op(partial(update.check_for_update, proxy), done)

    def _run_batch(self, urls: list[str]) -> None:
        """Queue many URLs through the resolver at sensible defaults."""
        if not urls:
            return
        thread = BatchImportThread(self.manager, self.settings, urls)
        thread.progress.connect(
            lambda done, total: self.statusBar().showMessage(f"Importing {done}/{total} …")
        )
        thread.summary.connect(self._on_batch_summary)
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
                if answer is not QMessageBox.StandardButton.Yes:
                    self.statusBar().showMessage("Ready")
                    return
        self.statusBar().showMessage(f"Analyzing {url} …")
        thread = _ResolveThread(
            self.resolver, url, self.settings, page_title, quality, fallbacks, headers
        )
        thread.resolved.connect(self._on_resolved)
        thread.finished.connect(lambda: self._resolve_threads.remove(thread))
        self._resolve_threads.append(thread)
        thread.start()

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
            self.manager.add_smart(
                resolution.url,
                resolution.media,
                option,
                use_session=self.settings.use_browser_session,
                session_browser=self.settings.session_browser,
            )
            self.statusBar().showMessage(f"Queued {resolution.media.title} ({option.label})", 5000)
            self.refresh()
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
                    use_session=self.settings.use_browser_session,
                    session_browser=self.settings.session_browser,
                )
        elif resolution.kind is JobKind.SMART and resolution.media is not None:
            quality_panel = QualityPanel(resolution.media, self)
            if quality_panel.exec() != QualityPanel.DialogCode.Accepted:
                return
            option = quality_panel.selected_option()
            if option is None:
                return
            self.manager.add_smart(
                resolution.url,
                resolution.media,
                option,
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
            self.manager.add_hls(resolution.url, title=page_title, variant=variant)
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
        """Remove the selected downloads from the list (files stay on disk).
        A download that is still running is skipped - cancel it first."""
        removed = 0
        for job_id in self._selected_job_ids():
            view = self._last_views.get(job_id)
            if view is not None and view.status is JobStatus.DOWNLOADING:
                continue
            self.manager.remove(job_id)
            removed += 1
        if removed:
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
        self.table.selectRow(row)
        menu = QMenu(self)
        file_path = Path(view.dest_dir) / view.filename
        open_file = menu.addAction("Open file")
        open_file.setEnabled(view.status is JobStatus.COMPLETED and file_path.exists())
        open_folder = menu.addAction("Open folder")
        copy_url = menu.addAction("Copy URL")
        copy_magnet = menu.addAction("Copy magnet link")
        copy_magnet.setVisible(view.kind is JobKind.TORRENT)
        redownload = menu.addAction("Download again")
        to_gif = menu.addAction("Convert to GIF…")
        ffmpeg_path = find_ffmpeg(self.settings)
        to_gif.setEnabled(
            view.status is JobStatus.COMPLETED
            and file_path.exists()
            and file_path.suffix.lower() in _VIDEO_SUFFIXES
            and ffmpeg_path is not None
        )
        limit_speed = menu.addAction("Limit speed…")
        limit_speed.setEnabled(view.status is not JobStatus.COMPLETED)
        set_connections = menu.addAction("Connections…")
        set_connections.setEnabled(view.status is not JobStatus.COMPLETED)

        done = view.status is JobStatus.COMPLETED and file_path.exists()
        copy_hash = menu.addAction("Copy SHA-256")
        copy_hash.setEnabled(done)
        verify_hash = menu.addAction("Verify checksum…")
        verify_hash.setEnabled(done)
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

        pending = view.status in (JobStatus.QUEUED, JobStatus.PAUSED)
        queue_menu = menu.addMenu("Move in queue")
        queue_menu.setEnabled(pending)
        move_top = queue_menu.addAction("To top")
        move_up = queue_menu.addAction("Up")
        move_down = queue_menu.addAction("Down")
        move_bottom = queue_menu.addAction("To bottom")

        menu.addSeparator()
        remove = menu.addAction("Remove from list")
        remove.setEnabled(view.status is not JobStatus.DOWNLOADING)
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
        elif chosen is to_gif and ffmpeg_path is not None:
            GifDialog(ffmpeg_path, file_path, self).exec()
        elif chosen is limit_speed:
            self._limit_speed(view)
        elif chosen is set_connections:
            self._set_connections(view)
        elif chosen is copy_hash:
            self._copy_hash(file_path)
        elif chosen is verify_hash:
            self._verify_hash(file_path)
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
        elif chosen is move_top:
            self.manager.move_to_top(view.id)
        elif chosen is move_up:
            self.manager.move_up(view.id)
        elif chosen is move_down:
            self.manager.move_down(view.id)
        elif chosen is move_bottom:
            self.manager.move_to_bottom(view.id)
        elif chosen is remove:
            self.manager.remove(view.id)
            self.refresh()

    def _run_file_op(
        self,
        work: Callable[[], object],
        on_done: Callable[[object], None],
        on_error: Callable[[object], None] | None = None,
    ) -> None:
        thread = _FileOpThread(work)
        self._file_ops.add(thread)

        def finished(result: object, error: object) -> None:
            self._file_ops.discard(thread)
            if error is not None:
                if on_error is not None:
                    on_error(error)
                else:
                    QMessageBox.warning(self, "Grabline", str(error))
            else:
                on_done(result)

        thread.done.connect(finished)
        thread.start()

    def _copy_hash(self, path: Path) -> None:
        self.statusBar().showMessage(f"Hashing {path.name} …")

        def done(result: object) -> None:
            QGuiApplication.clipboard().setText(str(result))
            self.statusBar().showMessage(f"SHA-256 copied for {path.name}", 6000)

        self._run_file_op(lambda: verify.hash_file(path), done)

    def _verify_hash(self, path: Path) -> None:
        expected, accepted = QInputDialog.getText(
            self, "Verify checksum", f"Paste the expected MD5/SHA-1/SHA-256 for {path.name}:"
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
    ) -> Callable[[], object]:
        """Extraction work for a background thread: the optional virus scan
        first, then the extraction itself."""

        def work() -> object:
            if self.settings.scan_before_extract:
                result = virusscan.scan(path)
                if not result.clean:
                    detail = f" ({result.detail})" if result.detail else ""
                    raise DownloadError(
                        f"{result.scanner} flagged {path.name}{detail} - not extracting."
                    )
            return archive.extract(path, passwords=passwords, members=members)

        return work

    def _extract(
        self, path: Path, members: list[str] | None = None, new_password: str | None = None
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

        self._run_file_op(self._archive_work(path, members, passwords), done, failed)

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
            if answer is not QMessageBox.StandardButton.Yes:
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
                "Set a search URL first (Settings → Torrents), e.g.\n"
                "https://example.com/search?q=%s",
            )
            return
        query, accepted = QInputDialog.getText(self, "Search torrents", "Search for:")
        if accepted and query.strip():
            from urllib.parse import quote

            QDesktopServices.openUrl(QUrl(template.replace("%s", quote(query.strip()))))

    def _poll_rss(self) -> None:
        """Check the RSS feeds and queue new matching torrent items."""
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
        views = self.manager.snapshot()
        self._detect_transitions(views)
        self._update_speed_line(views)
        self._last_views = {view.id: view for view in views}
        ids = [view.id for view in views]
        if ids != self._row_job_ids:
            self._rebuild_rows(views)
            self._restore_selection()
        for row, view in enumerate(views):
            self._update_row(row, view)
        self._apply_filter()

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
        total = sum(v.downloaded for v in views if v.status is JobStatus.DOWNLOADING)
        now = time.monotonic()
        if self._agg is not None:
            elapsed = now - self._agg[0]
            if elapsed > 0:
                # Clamp: a finishing job leaves the sum and would read negative.
                instant = max(0, total - self._agg[1]) / elapsed
                self._agg_ema = (
                    instant if self._agg_ema is None else self._agg_ema * 0.6 + instant * 0.4
                )
                self.speed_line.push(self._agg_ema)
        self._agg = (now, total)

    def _detect_transitions(self, views: list[JobView]) -> None:
        """Notify on newly finished downloads and when the queue drains."""
        active_now = False
        for view in views:
            previous = self._prev_status.get(view.id)
            if view.status in (JobStatus.DOWNLOADING, JobStatus.QUEUED):
                active_now = True
            just_completed = (
                previous is not None
                and previous is not JobStatus.COMPLETED
                and view.status is JobStatus.COMPLETED
            )
            if just_completed:
                self.job_completed.emit(view.display_name)
                if self.settings.auto_open_folder:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(view.dest_dir))
                file_path = Path(view.dest_dir) / view.filename
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
        tab_statuses = _TABS[self.tabs.currentIndex()][1] if self.tabs.currentIndex() >= 0 else ()
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
            matches_tab = not tab_statuses or (view is not None and view.status in tab_statuses)
            self.table.setRowHidden(row, not (matches_search and matches_tab))

    def _rebuild_rows(self, views: list[JobView]) -> None:
        self.table.setRowCount(len(views))
        self._row_job_ids = [view.id for view in views]
        for row in range(len(views)):
            for column in range(len(_COLUMNS)):
                if column == 2:
                    bar = QProgressBar()
                    bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setCellWidget(row, column, bar)
                else:
                    self.table.setItem(row, column, QTableWidgetItem(""))

    def _cell(self, row: int, column: int) -> QTableWidgetItem:
        item = self.table.item(row, column)
        assert item is not None  # _rebuild_rows creates every cell
        return item

    def _update_row(self, row: int, view: JobView) -> None:
        name_item = self._cell(row, 0)
        name_item.setText(view.display_name)
        name_item.setToolTip(view.url)

        size_text = human_bytes(view.total_size) if view.total_size is not None else "?"
        self._cell(row, 1).setText(size_text)

        bar = self.table.cellWidget(row, 2)
        if isinstance(bar, QProgressBar):
            if view.total_size:
                bar.setRange(0, 1000)
                bar.setValue(int(view.downloaded / view.total_size * 1000))
            elif view.status is JobStatus.DOWNLOADING:
                bar.setRange(0, 0)  # indeterminate
            else:
                bar.setRange(0, 1000)
                bar.setValue(1000 if view.status is JobStatus.COMPLETED else 0)

        self._cell(row, 3).setText(self._speed_text(view))

        status_item = self._cell(row, 4)
        status_item.setText(view.status.value)
        status_item.setToolTip(view.error or "")

    def _speed_text(self, view: JobView) -> str:
        if view.status is not JobStatus.DOWNLOADING:
            self._rates.pop(view.id, None)
            self._speed_ema.pop(view.id, None)
            return ""
        now = time.monotonic()
        previous = self._rates.get(view.id)
        self._rates[view.id] = (now, view.downloaded)
        if previous is None:
            return "…"
        elapsed = now - previous[0]
        if elapsed <= 0:
            return f"{human_bytes(self._speed_ema.get(view.id, 0.0))}/s"
        instant = max(0, view.downloaded - previous[1]) / elapsed
        # Exponential moving average: progress is checkpointed in bursts, so a
        # single zero-delta sample must not drop the display to 0 B/s.
        ema = self._speed_ema.get(view.id)
        smoothed = instant if ema is None else ema * 0.6 + instant * 0.4
        self._speed_ema[view.id] = smoothed
        return f"{human_bytes(smoothed)}/s"

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

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.close_to_tray and self.isVisible():
            event.ignore()
            self.hide()
        else:
            event.accept()
