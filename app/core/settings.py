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

    # --- speed schedule: lift the limit during a nightly full-speed window ---

    @property
    def speed_schedule_enabled(self) -> bool:
        """When on, the speed limit is lifted during the full-speed window."""
        return self._get_bool("speed_schedule_enabled", False)

    @speed_schedule_enabled.setter
    def speed_schedule_enabled(self, value: bool) -> None:
        self._set_bool("speed_schedule_enabled", value)

    def _get_time(self, key: str, default: str) -> str:
        raw = self._db.get_setting(key)
        if raw and len(raw) == 5 and raw[2] == ":" and raw[:2].isdigit() and raw[3:].isdigit():
            return raw
        return default

    @property
    def speed_full_from(self) -> str:
        """Start of the nightly full-speed window, "HH:MM"."""
        return self._get_time("speed_full_from", "00:00")

    @speed_full_from.setter
    def speed_full_from(self, value: str) -> None:
        self._db.set_setting("speed_full_from", value)

    @property
    def speed_full_to(self) -> str:
        """End of the nightly full-speed window, "HH:MM"."""
        return self._get_time("speed_full_to", "07:00")

    @speed_full_to.setter
    def speed_full_to(self, value: str) -> None:
        self._db.set_setting("speed_full_to", value)

    # --- timed download window: only run downloads between two times ---

    @property
    def download_schedule_enabled(self) -> bool:
        """When on, downloads only start (and keep running) inside the window."""
        return self._get_bool("download_schedule_enabled", False)

    @download_schedule_enabled.setter
    def download_schedule_enabled(self, value: bool) -> None:
        self._set_bool("download_schedule_enabled", value)

    @property
    def download_start(self) -> str:
        return self._get_time("download_start", "02:00")

    @download_start.setter
    def download_start(self, value: str) -> None:
        self._db.set_setting("download_start", value)

    @property
    def download_stop(self) -> str:
        return self._get_time("download_stop", "08:00")

    @download_stop.setter
    def download_stop(self, value: str) -> None:
        self._db.set_setting("download_stop", value)

    # --- updates ---

    @property
    def check_updates(self) -> bool:
        """Look for a newer Grabline release on startup (best effort)."""
        return self._get_bool("check_updates", True)

    @check_updates.setter
    def check_updates(self, value: bool) -> None:
        self._set_bool("check_updates", value)

    # --- automatic retry of failed downloads ---

    @property
    def auto_retry(self) -> bool:
        """Retry a download that fails from a network hiccup, with backoff."""
        return self._get_bool("auto_retry", True)

    @auto_retry.setter
    def auto_retry(self, value: bool) -> None:
        self._set_bool("auto_retry", value)

    @property
    def auto_retry_max(self) -> int:
        return max(0, min(20, self._get_int("auto_retry_max", 5)))

    @auto_retry_max.setter
    def auto_retry_max(self, value: int) -> None:
        self._db.set_setting("auto_retry_max", str(max(0, value)))

    # --- appearance ---

    @property
    def theme(self) -> str:
        """UI theme: "system", "light", or "dark"."""
        raw = self._db.get_setting("theme")
        return raw if raw in ("system", "light", "dark") else "system"

    @theme.setter
    def theme(self, value: str) -> None:
        if value not in ("system", "light", "dark"):
            raise ValueError(f"unknown theme: {value}")
        self._db.set_setting("theme", value)

    # --- networking ---

    @property
    def proxy(self) -> str | None:
        """A proxy URL (http://, https://, socks5://…) applied to all
        downloading, or None to go direct."""
        return self._db.get_setting("proxy") or None

    @proxy.setter
    def proxy(self, value: str | None) -> None:
        self._db.set_setting("proxy", (value or "").strip())

    # --- finishing touches ---

    @property
    def notify_on_complete(self) -> bool:
        return self._get_bool("notify_on_complete", True)

    @notify_on_complete.setter
    def notify_on_complete(self, value: bool) -> None:
        self._set_bool("notify_on_complete", value)

    @property
    def auto_open_folder(self) -> bool:
        """Open the containing folder when a download finishes."""
        return self._get_bool("auto_open_folder", False)

    @auto_open_folder.setter
    def auto_open_folder(self, value: bool) -> None:
        self._set_bool("auto_open_folder", value)

    @property
    def auto_extract(self) -> bool:
        """Unpack .zip/.tar archives automatically once they finish."""
        return self._get_bool("auto_extract", False)

    @auto_extract.setter
    def auto_extract(self, value: bool) -> None:
        self._set_bool("auto_extract", value)

    @property
    def after_queue_action(self) -> str:
        """What to do once every download finishes: nothing / quit / sleep /
        shutdown."""
        raw = self._db.get_setting("after_queue_action")
        return raw if raw in ("nothing", "quit", "sleep", "shutdown") else "nothing"

    @after_queue_action.setter
    def after_queue_action(self, value: str) -> None:
        if value not in ("nothing", "quit", "sleep", "shutdown"):
            raise ValueError(f"unknown after-queue action: {value}")
        self._db.set_setting("after_queue_action", value)

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
