"""Offscreen smoke test: the queue window builds and renders job rows."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QProgressBar

from app.core.manager import DownloadManager
from app.db.database import Database
from app.ui.main_window import MainWindow, human_bytes


def _qapp() -> QApplication:
    instance = QApplication.instance()
    return instance if isinstance(instance, QApplication) else QApplication([])


def test_human_bytes():
    assert human_bytes(512) == "512 B"
    assert human_bytes(2048) == "2.0 KB"
    assert human_bytes(5 * 1024 * 1024) == "5.0 MB"


def test_main_window_lists_jobs(db: Database, tmp_path: Path):
    _qapp()
    # max_concurrent=0 keeps the scheduler idle: the row renders without any
    # network activity.
    manager = DownloadManager(db, max_concurrent=0)
    try:
        db.create_job("http://example.invalid/x.bin", str(tmp_path), "x.bin")
        window = MainWindow(manager, tmp_path)
        window.refresh()
        assert window.table.rowCount() == 1
        name_item = window.table.item(0, 0)
        status_item = window.table.item(0, 4)
        assert name_item is not None and name_item.text() == "x.bin"
        assert status_item is not None and status_item.text() == "queued"
        assert isinstance(window.table.cellWidget(0, 2), QProgressBar)
    finally:
        manager.shutdown()
