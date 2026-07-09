"""The queue window (F0.4) and the add-URL flow: paste a URL, the resolver
routes it in a background thread, and Smart Engine hits get the quality panel.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import cast

from PySide6.QtCore import QPoint, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
)

from app.core import naming
from app.core.ffmpeg import find_ffmpeg
from app.core.manager import DownloadManager, JobView
from app.core.models import JobKind, JobStatus
from app.core.resolver import Resolution, Resolver
from app.core.settings import Settings
from app.engines.smart import option_for_label
from app.ui.batch_dialog import BatchImportDialog, BatchImportThread
from app.ui.format import human_bytes
from app.ui.gallery_panel import GalleryPanel
from app.ui.gif_dialog import GifDialog
from app.ui.playlist_panel import PlaylistPanel
from app.ui.quality_panel import QualityPanel
from app.ui.settings_dialog import SettingsDialog

_COLUMNS = ("Name", "Size", "Progress", "Speed", "Status")
_VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}


class _ResolveThread(QThread):
    # Resolution, page_title (str | None), quality label (str | None, F1.3),
    # fallback URLs (tuple[str, ...] - sniffed streams to try if this one dies)
    resolved = Signal(object, object, object, object)

    def __init__(
        self,
        resolver: Resolver,
        url: str,
        settings: Settings,
        page_title: str | None,
        quality: str | None = None,
        fallbacks: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self._resolver = resolver
        self._url = url
        self._page_title = page_title
        self._quality = quality
        self._fallbacks = fallbacks
        self._use_session = settings.use_browser_session
        self._browser = settings.session_browser

    def run(self) -> None:
        resolution = self._resolver.resolve(
            self._url, use_session=self._use_session, session_browser=self._browser
        )
        self.resolved.emit(resolution, self._page_title, self._quality, self._fallbacks)


class MainWindow(QMainWindow):
    def __init__(self, manager: DownloadManager, settings: Settings) -> None:
        super().__init__()
        self.manager = manager
        self.settings = settings
        self.resolver = Resolver()
        self.close_to_tray = False
        self.setWindowTitle("Grabline")
        self.resize(880, 440)

        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        for label, handler in (
            ("Add URL", self._add_url),
            ("Import Links", self._import_links),
            ("Pause", self._pause_selected),
            ("Resume", self._resume_selected),
            ("Cancel", self._cancel_selected),
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

        self.table = QTableWidget(0, len(_COLUMNS), self)
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_row_menu)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 320)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 120)
        self.setCentralWidget(self.table)
        self.statusBar().showMessage("Ready")

        self._row_job_ids: list[int] = []
        self._last_views: dict[int, JobView] = {}
        self._rates: dict[int, tuple[float, int]] = {}
        self._resolve_threads: list[_ResolveThread] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(500)
        # Grabline Connect drops URLs into the handoffs table; pick them up.
        self._handoff_timer = QTimer(self)
        self._handoff_timer.timeout.connect(self._poll_handoffs)
        self._handoff_timer.start(1000)
        self.refresh()

    def _poll_handoffs(self) -> None:
        for handoff in self.manager.db.claim_handoffs():
            if handoff.source == "gallery" and handoff.payload:
                self._open_gallery(list(handoff.payload), handoff.page_title)
            else:
                self.begin_add_url(
                    handoff.url,
                    page_title=handoff.page_title,
                    quality=handoff.quality,
                    fallbacks=handoff.payload,
                )

    def _open_gallery(self, urls: list[str], page_title: str | None) -> None:
        """F2.2: the extension collected a page's images - pick and batch."""
        panel = GalleryPanel(urls, page_title=page_title, parent=self)
        if panel.exec() != GalleryPanel.DialogCode.Accepted:
            return
        for url in panel.selected_urls():
            self.manager.add_url(url)
        self.refresh()

    # ------------------------------------------------------------- actions

    def _add_url(self) -> None:
        url, accepted = QInputDialog.getText(self, "Add download", "URL:")
        if accepted and url.strip():
            self.begin_add_url(url.strip())

    def _import_links(self) -> None:
        """F2.4: paste/load many URLs; they queue at defaults, no panels."""
        dialog = BatchImportDialog(self)
        if dialog.exec() != BatchImportDialog.DialogCode.Accepted:
            return
        urls = dialog.urls()
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
    ) -> None:
        """Entry point shared by the toolbar, tray, clipboard, and extension.
        A ``quality`` label (F1.3 in-page panel) skips the quality dialog;
        ``fallbacks`` are sniffed stream URLs tried in order if ``url``
        resolves to nothing (blob players on streaming sites)."""
        self.statusBar().showMessage(f"Analyzing {url} …")
        thread = _ResolveThread(self.resolver, url, self.settings, page_title, quality, fallbacks)
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
                )
                return
            QMessageBox.information(self, "Grabline", resolution.message or "No media found.")
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
            self.manager.add_url(resolution.url, filename=filename)
        self.refresh()

    def _selected_job_id(self) -> int | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._row_job_ids):
            return self._row_job_ids[row]
        return None

    def _pause_selected(self) -> None:
        job_id = self._selected_job_id()
        if job_id is not None:
            self.manager.pause(job_id)

    def _resume_selected(self) -> None:
        job_id = self._selected_job_id()
        if job_id is not None:
            self.manager.resume(job_id)

    def _cancel_selected(self) -> None:
        job_id = self._selected_job_id()
        if job_id is not None:
            self.manager.cancel(job_id)

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.settings.download_dir)))

    def _open_settings(self) -> None:
        if SettingsDialog(self.settings, self).exec() == SettingsDialog.DialogCode.Accepted:
            self.manager.reload_settings()

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
        redownload = menu.addAction("Download again")
        to_gif = menu.addAction("Convert to GIF…")
        ffmpeg_path = find_ffmpeg(self.settings)
        to_gif.setEnabled(
            view.status is JobStatus.COMPLETED
            and file_path.exists()
            and file_path.suffix.lower() in _VIDEO_SUFFIXES
            and ffmpeg_path is not None
        )
        menu.addSeparator()
        remove = menu.addAction("Remove from list")
        remove.setEnabled(view.status is not JobStatus.DOWNLOADING)
        chosen = menu.exec(self.table.viewport().mapToGlobal(position))
        if chosen is open_file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path)))
        elif chosen is open_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(view.dest_dir))
        elif chosen is copy_url:
            QGuiApplication.clipboard().setText(view.url)
        elif chosen is redownload:
            self.begin_add_url(view.url)
        elif chosen is to_gif and ffmpeg_path is not None:
            GifDialog(ffmpeg_path, file_path, self).exec()
        elif chosen is remove:
            self.manager.remove(view.id)
            self.refresh()

    # ------------------------------------------------------------- refresh

    def refresh(self) -> None:
        views = self.manager.snapshot()
        self._last_views = {view.id: view for view in views}
        ids = [view.id for view in views]
        if ids != self._row_job_ids:
            self._rebuild_rows(views)
        for row, view in enumerate(views):
            self._update_row(row, view)
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self.search_box.text().strip().lower()
        for row in range(self.table.rowCount()):
            view = self._view_for_row(row)
            visible = not needle or (
                view is not None
                and (needle in view.display_name.lower() or needle in view.url.lower())
            )
            self.table.setRowHidden(row, not visible)

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
            return ""
        now = time.monotonic()
        previous = self._rates.get(view.id)
        self._rates[view.id] = (now, view.downloaded)
        if previous is None:
            return ""
        elapsed = now - previous[0]
        if elapsed <= 0:
            return ""
        speed = max(0, view.downloaded - previous[1]) / elapsed
        return f"{human_bytes(speed)}/s"

    # --------------------------------------------------------------- close

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.close_to_tray and self.isVisible():
            event.ignore()
            self.hide()
        else:
            event.accept()
