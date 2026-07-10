"""Offscreen smoke tests: widgets build, render job rows, and validate input."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QProgressBar

from app.core.manager import DownloadManager
from app.core.settings import Settings
from app.db.database import Database
from app.engines.smart import MediaInfo, QualityOption
from app.ui.clipboard import is_probable_url
from app.ui.format import duration_text, human_bytes
from app.ui.main_window import MainWindow
from app.ui.quality_panel import QualityPanel, parse_timestamp


def _qapp() -> QApplication:
    instance = QApplication.instance()
    return instance if isinstance(instance, QApplication) else QApplication([])


def test_human_bytes():
    assert human_bytes(512) == "512 B"
    assert human_bytes(2048) == "2.0 KB"
    assert human_bytes(5 * 1024 * 1024) == "5.0 MB"


def test_duration_text():
    assert duration_text(None) == ""
    assert duration_text(75) == "1:15"
    assert duration_text(3671) == "1:01:11"


def test_parse_timestamp():
    assert parse_timestamp("") is None
    assert parse_timestamp("90") == 90.0
    assert parse_timestamp("1:30") == 90.0
    assert parse_timestamp("1:02:03") == 3723.0
    with pytest.raises(ValueError):
        parse_timestamp("abc")


def test_is_probable_url():
    assert is_probable_url("https://example.com/video.mp4")
    assert not is_probable_url("just some text")
    assert not is_probable_url("https://example.com/with space")
    assert not is_probable_url("ftp://example.com/f")


def test_clipboard_off_by_default_and_suppress(db: Database):
    from app.ui.clipboard import ClipboardWatcher

    app = _qapp()
    settings = Settings(db)
    assert settings.clipboard_watcher is False  # no auto-offer on copy
    watcher = ClipboardWatcher(app, settings)
    fired: list[str] = []
    watcher.url_copied.connect(fired.append)
    # Even enabled, a suppressed URL (our own Copy URL) must not bounce back.
    settings.clipboard_watcher = True
    watcher.suppress("https://example.com/mine.zip")
    app.clipboard().setText("https://example.com/mine.zip")
    assert fired == []


def test_main_window_lists_jobs(db: Database, tmp_path: Path):
    _qapp()
    settings = Settings(db)
    settings.download_dir = tmp_path
    # max_concurrent=0 keeps the scheduler idle: the row renders without any
    # network activity.
    manager = DownloadManager(db, settings=settings, max_concurrent=0)
    try:
        db.create_job("http://example.invalid/x.bin", str(tmp_path), "x.bin")
        window = MainWindow(manager, settings)
        window.refresh()
        assert window.table.rowCount() == 1
        name_item = window.table.item(0, 0)
        status_item = window.table.item(0, 4)
        assert name_item is not None and name_item.text() == "x.bin"
        assert status_item is not None and status_item.text() == "queued"
        assert isinstance(window.table.cellWidget(0, 2), QProgressBar)
    finally:
        manager.shutdown()


def test_playlist_panel_selection(db: Database):
    from PySide6.QtCore import Qt

    from app.engines.smart import PlaylistEntry, PlaylistInfo
    from app.ui.playlist_panel import PlaylistPanel

    _qapp()
    playlist = PlaylistInfo(
        url="https://tube.example/playlist?list=1",
        title="Big Course",
        uploader="Prof",
        entries=tuple(
            PlaylistEntry(
                url=f"https://tube.example/watch?v={i}",
                title=f"Lesson {i}",
                duration=60,
                index=i,
            )
            for i in range(1, 41)
        ),
    )
    panel = PlaylistPanel(playlist, preselect_cap=30)
    assert panel.entry_list.count() == 40
    assert len(panel.selected_entries()) == 30  # cap preselects the first 30
    panel._set_all(Qt.CheckState.Checked)
    assert len(panel.selected_entries()) == 40
    panel._set_all(Qt.CheckState.Unchecked)
    panel.entry_list.item(2).setCheckState(Qt.CheckState.Checked)
    selected = panel.selected_entries()
    assert [entry.title for entry in selected] == ["Lesson 3"]
    assert panel.selected_option().label == "Best"


def test_link_panel_selection_and_filter(db: Database):
    from app.ui.link_panel import LinkPanel

    _qapp()
    urls = [
        "https://x.test/movie.mp4",
        "https://x.test/song.mp3",
        "https://x.test/notes.pdf",
        "https://x.test/page",
    ]
    panel = LinkPanel(urls)
    assert panel.list.count() == 4
    assert panel.selected_urls() == []  # nothing checked by default
    panel._select_by_ext((".mp4", ".mp3"))
    assert set(panel.selected_urls()) == {urls[0], urls[1]}
    panel.filter_box.setText("notes")
    assert panel.list.item(0).isHidden() and not panel.list.item(2).isHidden()


def test_main_window_has_file_menu(db: Database, tmp_path: Path):
    _qapp()
    settings = Settings(db)
    settings.download_dir = tmp_path
    manager = DownloadManager(db, settings=settings, max_concurrent=0)
    try:
        window = MainWindow(manager, settings)
        titles = [action.text() for action in window.menuBar().actions()]
        assert "&File" in titles
    finally:
        manager.shutdown()


def test_setup_dialog_builds_and_stages_extension(tmp_path, monkeypatch):
    from app.ui.setup_dialog import SetupDialog

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    _qapp()
    dialog = SetupDialog()
    # The wizard stages the extension and shows its stable path.
    from app.core import browser_setup

    assert dialog._folder_edit.text() == str(browser_setup.stable_extension_dir())
    assert (browser_setup.stable_extension_dir() / "manifest.json").is_file()


def test_theme_apply_switches_palette():
    from app.ui import theme

    app = _qapp()
    theme.remember_default(app)
    theme.apply_theme(app, "dark")
    dark_window = app.palette().color(app.palette().ColorRole.Window)
    theme.apply_theme(app, "light")
    light_window = app.palette().color(app.palette().ColorRole.Window)
    assert dark_window != light_window
    theme.apply_theme(app, "system")  # restores default without error


def test_main_window_search_filter(db: Database, tmp_path: Path):
    _qapp()
    settings = Settings(db)
    settings.download_dir = tmp_path
    manager = DownloadManager(db, settings=settings, max_concurrent=0)
    try:
        db.create_job("http://example.invalid/report.pdf", str(tmp_path), "report.pdf")
        db.create_job("http://example.invalid/movie.mkv", str(tmp_path), "movie.mkv")
        window = MainWindow(manager, settings)
        window.refresh()
        assert window.table.rowCount() == 2
        window.search_box.setText("movie")
        assert window.table.isRowHidden(0)
        assert not window.table.isRowHidden(1)
        window.search_box.setText("")
        assert not window.table.isRowHidden(0)
    finally:
        manager.shutdown()


def test_quality_panel_selection_and_trim(db: Database):
    _qapp()
    media = MediaInfo(
        url="https://tube.example/watch?v=1",
        id="1",
        title="Panel Video",
        uploader="Someone",
        duration=125.0,
        thumbnail_url=None,
        options=(
            QualityOption(label="Best", kind="video", format_spec="bv*+ba/b"),
            QualityOption(
                label="1080p",
                kind="video",
                format_spec="bv*[height<=1080]+ba/b[height<=1080]",
                estimated_size=84 * 1024 * 1024,
            ),
            QualityOption(label="MP3", kind="audio", format_spec="ba/b", audio_format="mp3"),
        ),
        subtitle_languages=("en",),
        auto_caption_languages=("en", "de"),
    )
    panel = QualityPanel(media)
    assert panel.options_list.count() == 3
    assert panel.selected_option() is media.options[0]
    panel.options_list.setCurrentRow(2)
    selected = panel.selected_option()
    assert selected is not None and selected.audio_format == "mp3"

    # subtitles: None + en + de (auto); en (manual) wins over its auto twin
    assert panel.subtitle_combo.count() == 3
    panel.subtitle_combo.setCurrentIndex(1)
    config = panel.subtitles_config()
    assert config == {"lang": "en", "auto": False, "embed": False}

    panel.trim_start.setText("1:00")
    panel.trim_end.setText("2:05")
    assert panel.trim_range() == (60.0, 125.0)
    panel.trim_start.setText("")
    panel.trim_end.setText("")
    assert panel.trim_range() is None
