"""Minimal queue window (F0.4): one list for everything, with pause/resume/
cancel/retry, live progress and speed, driven by a 500 ms refresh timer.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QInputDialog,
    QMainWindow,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
)

from app.core.manager import DownloadManager, JobView
from app.core.models import JobStatus

_COLUMNS = ("Name", "Size", "Progress", "Speed", "Status")


def human_bytes(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if count < 1024 or unit == "TB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} TB"  # pragma: no cover - unreachable


class MainWindow(QMainWindow):
    def __init__(self, manager: DownloadManager, download_dir: Path) -> None:
        super().__init__()
        self.manager = manager
        self.download_dir = download_dir
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
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        self.table.setColumnWidth(0, 320)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 120)
        self.setCentralWidget(self.table)

        self._row_job_ids: list[int] = []
        self._rates: dict[int, tuple[float, int]] = {}
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(500)
        self.refresh()

    # ------------------------------------------------------------- actions

    def _add_url(self) -> None:
        url, accepted = QInputDialog.getText(self, "Add download", "URL:")
        if accepted and url.strip():
            self.manager.add_url(url.strip(), self.download_dir)
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
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.download_dir)))

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
        name_item.setText(view.filename)
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
