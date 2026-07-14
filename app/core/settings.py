"""Typed application settings backed by the settings table in SQLite."""

from __future__ import annotations

import json
from collections.abc import Sequence
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
    def host_registered(self) -> bool:
        """Whether the Native Messaging host has been auto-registered once (on
        first run of an installed build). Re-pairing is available in Settings."""
        return self._get_bool("host_registered", False)

    @host_registered.setter
    def host_registered(self, value: bool) -> None:
        self._set_bool("host_registered", value)

    @property
    def clipboard_watcher(self) -> bool:
        """F0.5: offer to download URLs copied to the clipboard. Off by
        default - an offer on every copied link is intrusive, and the browser
        button covers the common case."""
        return self._get_bool("clipboard_watcher", False)

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
        if raw in SESSION_BROWSERS:
            return raw
        # Never explicitly chosen: point at the browser that's actually set up
        # here (Firefox before preinstalled-but-unused Edge) rather than a
        # hardcoded "chrome" the person may not even have.
        from app.core.browser_setup import detect_cookie_browser

        return detect_cookie_browser() or "chrome"

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
        return max(1, min(128, self._get_int("connections", 8)))

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

    @property
    def setup_seen(self) -> bool:
        """Whether the first-run Browser Setup wizard has been shown."""
        return self._get_bool("setup_seen", False)

    @setup_seen.setter
    def setup_seen(self, value: bool) -> None:
        self._set_bool("setup_seen", value)

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
        """Auto-retry attempts per download; 0 means retry forever."""
        return max(0, min(99, self._get_int("auto_retry_max", 5)))

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
    def archive_passwords(self) -> tuple[str, ...]:
        """Passwords tried in order when an archive turns out to be encrypted.
        Stored locally and unencrypted - the same trust level as the
        downloaded files themselves."""
        raw = self._db.get_setting("archive_passwords")
        if not raw:
            return ()
        try:
            values = json.loads(raw)
        except ValueError:
            return ()
        if not isinstance(values, list):
            return ()
        return tuple(str(v) for v in values if str(v).strip())

    @archive_passwords.setter
    def archive_passwords(self, value: Sequence[str]) -> None:
        deduped = list(dict.fromkeys(v.strip() for v in value if v.strip()))
        self._db.set_setting("archive_passwords", json.dumps(deduped))

    @property
    def scan_before_extract(self) -> bool:
        """Run an installed virus scanner (ClamAV / Windows Defender) over an
        archive before extracting it."""
        return self._get_bool("scan_before_extract", False)

    @scan_before_extract.setter
    def scan_before_extract(self, value: bool) -> None:
        self._set_bool("scan_before_extract", value)

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
