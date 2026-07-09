from __future__ import annotations

from pathlib import Path

import pytest

from app.core.paths import default_download_dir
from app.core.settings import Settings
from app.db.database import Database


def test_defaults(db: Database):
    settings = Settings(db)
    assert settings.download_dir == default_download_dir()
    assert settings.categories_enabled is True
    assert settings.clipboard_watcher is True
    assert settings.use_browser_session is False
    assert settings.session_browser == "chrome"
    assert settings.max_concurrent == 3
    assert settings.connections == 8
    assert settings.ffmpeg_path is None


def test_roundtrip(db: Database, tmp_path: Path):
    settings = Settings(db)
    settings.download_dir = tmp_path / "dl"
    settings.categories_enabled = False
    settings.clipboard_watcher = False
    settings.use_browser_session = True
    settings.session_browser = "firefox"
    settings.max_concurrent = 5
    settings.connections = 4
    settings.ffmpeg_path = "/opt/ffmpeg"

    fresh = Settings(db)  # separate instance, same storage
    assert fresh.download_dir == tmp_path / "dl"
    assert fresh.categories_enabled is False
    assert fresh.clipboard_watcher is False
    assert fresh.use_browser_session is True
    assert fresh.session_browser == "firefox"
    assert fresh.max_concurrent == 5
    assert fresh.connections == 4
    assert fresh.ffmpeg_path == "/opt/ffmpeg"


def test_values_are_clamped(db: Database):
    settings = Settings(db)
    settings.max_concurrent = 99
    settings.connections = 0
    assert settings.max_concurrent == 10
    assert settings.connections == 1


def test_invalid_browser_rejected(db: Database):
    settings = Settings(db)
    with pytest.raises(ValueError):
        settings.session_browser = "netscape"


def test_corrupt_int_falls_back(db: Database):
    db.set_setting("max_concurrent", "banana")
    assert Settings(db).max_concurrent == 3


def test_schedule_retry_theme_defaults(db: Database):
    settings = Settings(db)
    assert settings.speed_schedule_enabled is False
    assert settings.speed_full_from == "00:00"
    assert settings.speed_full_to == "07:00"
    assert settings.auto_retry is True
    assert settings.auto_retry_max == 5
    assert settings.theme == "system"


def test_schedule_retry_theme_roundtrip(db: Database):
    settings = Settings(db)
    settings.speed_schedule_enabled = True
    settings.speed_full_from = "23:30"
    settings.speed_full_to = "06:15"
    settings.auto_retry = False
    settings.auto_retry_max = 99  # clamped to 20
    settings.theme = "dark"

    fresh = Settings(db)
    assert fresh.speed_schedule_enabled is True
    assert fresh.speed_full_from == "23:30"
    assert fresh.speed_full_to == "06:15"
    assert fresh.auto_retry is False
    assert fresh.auto_retry_max == 20
    assert fresh.theme == "dark"


def test_bad_time_and_theme_fall_back(db: Database):
    db.set_setting("speed_full_from", "9999")
    db.set_setting("theme", "hologram")
    settings = Settings(db)
    assert settings.speed_full_from == "00:00"
    assert settings.theme == "system"
    with pytest.raises(ValueError):
        settings.theme = "hologram"
