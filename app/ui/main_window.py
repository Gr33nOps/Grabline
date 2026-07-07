"""The queue window (F0.4) and the add-URL flow: paste a URL, the resolver
routes it in a background thread, and Smart Engine hits get the quality panel.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
)

from app.core.manager import DownloadManager, JobView
from app.core.models import JobKind, JobStatus
from app.core.resolver import Resolution, Resolver
from app.core.settings import Settings
from app.ui.format import human_bytes
from app.ui.quality_panel import QualityPanel
from app.ui.settings_dialog import SettingsDialog

_COLUMNS = ("Name", "Size", "Progress", "Speed", "Status")


class _ResolveThread(QThread):
    resolved = Signal(object)

    def __init__(self, resolver: Resolver, url: str, settings: Settings) -> None:
        super().__init__()
        self._resolver = resolver
        self._url = url
        self._use_session = settings.use_browser_session
        self._browser = settings.session_browser

    def run(self) -> None:
        resolution = self._resolver.resolve(
            self._url, use_session=self._use_session, session_browser=self._browser
        )
        self.resolved.emit(resolution)


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
            ("Pause", self._pause_selected),
            ("Resume", self._resume_selected),
            ("Cancel", self._cancel_selected),
            ("Open Folder", self._open_folder),
            ("Settings", self._open_settings),
        ):
            action = QAction(label, self)
            action.triggered.connect(handler)
            toolbar.addAction(action)

        self.table = QTableWidget(0, len(_COLUMNS), self)
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 320)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 120)
        self.setCentralWidget(self.table)
        self.statusBar().showMessage("Ready")

        self._row_job_ids: list[int] = []
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
            self.begin_add_url(handoff.url)

    # ------------------------------------------------------------- actions

    def _add_url(self) -> None:
        url, accepted = QInputDialog.getText(self, "Add download", "URL:")
        if accepted and url.strip():
            self.begin_add_url(url.strip())

    def begin_add_url(self, url: str) -> None:
        """Entry point shared by the toolbar, tray, and clipboard watcher."""
        self.statusBar().showMessage(f"Analyzing {url} …")
        thread = _ResolveThread(self.resolver, url, self.settings)
        thread.resolved.connect(self._on_resolved)
        thread.finished.connect(lambda: self._resolve_threads.remove(thread))
        self._resolve_threads.append(thread)
        thread.start()

    def _on_resolved(self, resolution: Resolution) -> None:
        self.statusBar().showMessage("Ready")
        if resolution.kind is None:
            QMessageBox.information(self, "Grabline", resolution.message or "No media found.")
            return
        if resolution.kind is JobKind.SMART and resolution.media is not None:
            panel = QualityPanel(resolution.media, self)
            if panel.exec() != QualityPanel.DialogCode.Accepted:
                return
            option = panel.selected_option()
            if option is None:
                return
            self.manager.add_smart(
                resolution.url,
                resolution.media,
                option,
                subtitles=panel.subtitles_config(),
                trim=panel.trim_range(),
                use_session=self.settings.use_browser_session,
                session_browser=self.settings.session_browser,
            )
        elif resolution.kind is JobKind.HLS:
            self.manager.add_hls(resolution.url)
        else:
            filename = (
                resolution.probe.filename
                if resolution.probe is not None and resolution.probe.filename
                else None
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
        SettingsDialog(self.settings, self).exec()

    # ------------------------------------------------------------- refresh

    def refresh(self) -> None:
        views = self.manager.snapshot()
        ids = [view.id for view in views]
        if ids != self._row_job_ids:
            self._rebuild_rows(views)
        for row, view in enumerate(views):
            self._update_row(row, view)

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
