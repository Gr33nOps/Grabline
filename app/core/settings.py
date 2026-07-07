"""Typed application settings backed by the settings table in SQLite."""

from __future__ import annotations

from pathlib import Path

from app.core import paths
from app.db.database import Database

#: Browsers yt-dlp can read a cookie store from (F0.8).
SESSION_BROWSERS = ("chrome", "firefox", "edge", "brave", "chromium", "opera", "safari")


class Settings:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------ helpers

    def _get_bool(self, key: str, default: bool) -> bool:
        raw = self._db.get_setting(key)
        return default if raw is None else raw == "1"

    def _set_bool(self, key: str, value: bool) -> None:
        self._db.set_setting(key, "1" if value else "0")

    def _get_int(self, key: str, default: int) -> int:
        raw = self._db.get_setting(key)
        try:
            return int(raw) if raw is not None else default
        except ValueError:
            return default

    # ----------------------------------------------------------- settings

    @property
    def download_dir(self) -> Path:
        raw = self._db.get_setting("download_dir")
        return Path(raw) if raw else paths.default_download_dir()

    @download_dir.setter
    def download_dir(self, value: Path | str) -> None:
        self._db.set_setting("download_dir", str(value))

    @property
    def categories_enabled(self) -> bool:
        """F0.6: sort downloads into Video/Music/Images/Documents/Archives."""
        return self._get_bool("categories_enabled", True)

    @categories_enabled.setter
    def categories_enabled(self, value: bool) -> None:
        self._set_bool("categories_enabled", value)

    @property
    def clipboard_watcher(self) -> bool:
        """F0.5: offer to download URLs copied to the clipboard."""
        return self._get_bool("clipboard_watcher", True)

    @clipboard_watcher.setter
    def clipboard_watcher(self, value: bool) -> None:
        self._set_bool("clipboard_watcher", value)

    @property
    def use_browser_session(self) -> bool:
        """F0.8: off by default; plain-language consent lives in the settings UI."""
        return self._get_bool("use_browser_session", False)

    @use_browser_session.setter
    def use_browser_session(self, value: bool) -> None:
        self._set_bool("use_browser_session", value)

    @property
    def session_browser(self) -> str:
        raw = self._db.get_setting("session_browser")
        return raw if raw in SESSION_BROWSERS else "chrome"

    @session_browser.setter
    def session_browser(self, value: str) -> None:
        if value not in SESSION_BROWSERS:
            raise ValueError(f"unsupported browser: {value}")
        self._db.set_setting("session_browser", value)

    @property
    def max_concurrent(self) -> int:
        return max(1, min(10, self._get_int("max_concurrent", 3)))

    @max_concurrent.setter
    def max_concurrent(self, value: int) -> None:
        self._db.set_setting("max_concurrent", str(value))

    @property
    def connections(self) -> int:
        return max(1, min(16, self._get_int("connections", 8)))

    @connections.setter
    def connections(self, value: int) -> None:
        self._db.set_setting("connections", str(value))

    @property
    def speed_limit_kbps(self) -> int:
        """Global download cap in KB/s (F1.8). 0 means unlimited."""
        return max(0, self._get_int("speed_limit_kbps", 0))

    @speed_limit_kbps.setter
    def speed_limit_kbps(self, value: int) -> None:
        self._db.set_setting("speed_limit_kbps", str(max(0, value)))

    @property
    def playlist_batch_cap(self) -> int:
        """How many playlist entries get preselected (F1.7)."""
        return max(1, min(500, self._get_int("playlist_batch_cap", 30)))

    @property
    def ffmpeg_path(self) -> str | None:
        """Manual override; normally FFmpeg is found automatically."""
        return self._db.get_setting("ffmpeg_path") or None

    @ffmpeg_path.setter
    def ffmpeg_path(self, value: str | None) -> None:
        self._db.set_setting("ffmpeg_path", value or "")
