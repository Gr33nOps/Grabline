"""Typed application settings backed by the settings table in SQLite."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from app.core import paths
from app.db.database import Database

#: Browsers yt-dlp can read a cookie store from (F0.8).
SESSION_BROWSERS = ("chrome", "firefox", "edge", "brave", "chromium", "opera", "safari")

_AFTER_QUEUE_ACTIONS = ("nothing", "quit", "sleep", "shutdown", "hibernate", "lock")


class Settings:
    def __init__(self, db: Database) -> None:
        self._db = db

    @property
    def db(self) -> Database:
        """The backing database, for components that need their own store
        (e.g. the cloud CredentialStore) without re-opening the file."""
        return self._db

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

    @property
    def host_limits(self) -> dict[str, int]:
        """Per-host download caps in KB/s, keyed by hostname. Downloads from a
        listed host share that cap; 0 or absent means no per-host limit."""
        raw = self._db.get_setting("host_limits")
        if not raw:
            return {}
        try:
            values = json.loads(raw)
        except ValueError:
            return {}
        if not isinstance(values, dict):
            return {}
        limits: dict[str, int] = {}
        for host, kbps in values.items():
            try:
                rate = int(kbps)
            except (TypeError, ValueError):
                continue
            if str(host).strip() and rate > 0:
                limits[str(host).strip().lower()] = rate
        return limits

    @host_limits.setter
    def host_limits(self, value: Mapping[str, int]) -> None:
        cleaned = {
            str(host).strip().lower(): int(kbps)
            for host, kbps in value.items()
            if str(host).strip() and int(kbps) > 0
        }
        self._db.set_setting("host_limits", json.dumps(cleaned))

    @property
    def auto_throttle(self) -> bool:
        """'Polite mode': automatically slow downloads when other apps are
        using the network heavily, and speed back up when they stop."""
        return self._get_bool("auto_throttle", False)

    @auto_throttle.setter
    def auto_throttle(self, value: bool) -> None:
        self._set_bool("auto_throttle", value)

    @property
    def auto_throttle_kbps(self) -> int:
        """The reduced download cap (KB/s) applied while other traffic is busy."""
        return max(1, self._get_int("auto_throttle_kbps", 512))

    @auto_throttle_kbps.setter
    def auto_throttle_kbps(self, value: int) -> None:
        self._db.set_setting("auto_throttle_kbps", str(max(1, value)))

    @property
    def auto_throttle_threshold_kbps(self) -> int:
        """How much *other* network traffic (KB/s) counts as 'busy' and trips
        the automatic throttle."""
        return max(1, self._get_int("auto_throttle_threshold_kbps", 256))

    @auto_throttle_threshold_kbps.setter
    def auto_throttle_threshold_kbps(self, value: int) -> None:
        self._db.set_setting("auto_throttle_threshold_kbps", str(max(1, value)))

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
        return self._get_str_list("archive_passwords")

    @archive_passwords.setter
    def archive_passwords(self, value: Sequence[str]) -> None:
        deduped = list(dict.fromkeys(v.strip() for v in value if v.strip()))
        self._db.set_setting("archive_passwords", json.dumps(deduped))

    def _get_str_list(self, key: str) -> tuple[str, ...]:
        raw = self._db.get_setting(key)
        if not raw:
            return ()
        try:
            values = json.loads(raw)
        except ValueError:
            return ()
        if not isinstance(values, list):
            return ()
        return tuple(str(v) for v in values if str(v).strip())

    @property
    def favorite_folders(self) -> tuple[str, ...]:
        """Quick move-to destinations offered in the download's context menu."""
        return self._get_str_list("favorite_folders")

    @favorite_folders.setter
    def favorite_folders(self, value: Sequence[str]) -> None:
        deduped = list(dict.fromkeys(v.strip() for v in value if v.strip()))
        self._db.set_setting("favorite_folders", json.dumps(deduped))

    @property
    def rename_rules(self) -> tuple[tuple[str, str], ...]:
        """Literal find -> replace pairs applied (in order) to every new
        download's filename stem."""
        raw = self._db.get_setting("rename_rules")
        if not raw:
            return ()
        try:
            values = json.loads(raw)
        except ValueError:
            return ()
        if not isinstance(values, list):
            return ()
        rules: list[tuple[str, str]] = []
        for pair in values:
            if isinstance(pair, list) and len(pair) == 2 and str(pair[0]):
                rules.append((str(pair[0]), str(pair[1])))
        return tuple(rules)

    @rename_rules.setter
    def rename_rules(self, value: Sequence[tuple[str, str]]) -> None:
        cleaned = [[find, replace] for find, replace in value if find]
        self._db.set_setting("rename_rules", json.dumps(cleaned))

    @property
    def scan_before_extract(self) -> bool:
        """Run an installed virus scanner (ClamAV / Windows Defender) over an
        archive before extracting it."""
        return self._get_bool("scan_before_extract", False)

    @scan_before_extract.setter
    def scan_before_extract(self, value: bool) -> None:
        self._set_bool("scan_before_extract", value)

    # ------------------------------------------------------------ security

    @property
    def scan_downloads(self) -> bool:
        """Run an advisory security check on each finished download (a local
        virus scan and, if configured, VirusTotal). Never blocks - it only
        warns."""
        return self._get_bool("scan_downloads", False)

    @scan_downloads.setter
    def scan_downloads(self, value: bool) -> None:
        self._set_bool("scan_downloads", value)

    @property
    def enforce_https(self) -> bool:
        """Warn before starting a download over unencrypted HTTP (you can
        still proceed)."""
        return self._get_bool("enforce_https", False)

    @enforce_https.setter
    def enforce_https(self, value: bool) -> None:
        self._set_bool("enforce_https", value)

    @property
    def virustotal_key(self) -> str:
        """The user's own VirusTotal API key. Empty = the VirusTotal check is
        off. Only the file's hash is ever sent, never its contents."""
        return self._db.get_setting("virustotal_key") or ""

    @virustotal_key.setter
    def virustotal_key(self, value: str) -> None:
        self._db.set_setting("virustotal_key", value.strip())

    @property
    def safebrowsing_key(self) -> str:
        """The user's own Google Safe Browsing API key. Empty = off. When set,
        the URL is sent to Google before download - so this is opt-in."""
        return self._db.get_setting("safebrowsing_key") or ""

    @safebrowsing_key.setter
    def safebrowsing_key(self, value: str) -> None:
        self._db.set_setting("safebrowsing_key", value.strip())

    # ------------------------------------------------------------ torrents

    @property
    def torrent_port(self) -> int:
        """The BitTorrent listen port (both TCP and uTP)."""
        return max(1024, min(65535, self._get_int("torrent_port", 6881)))

    @torrent_port.setter
    def torrent_port(self, value: int) -> None:
        self._db.set_setting("torrent_port", str(value))

    @property
    def torrent_dht(self) -> bool:
        """DHT: find peers without trackers (also enables magnet-only swarms)."""
        return self._get_bool("torrent_dht", True)

    @torrent_dht.setter
    def torrent_dht(self, value: bool) -> None:
        self._set_bool("torrent_dht", value)

    @property
    def torrent_upnp(self) -> bool:
        return self._get_bool("torrent_upnp", True)

    @torrent_upnp.setter
    def torrent_upnp(self, value: bool) -> None:
        self._set_bool("torrent_upnp", value)

    @property
    def torrent_natpmp(self) -> bool:
        return self._get_bool("torrent_natpmp", True)

    @torrent_natpmp.setter
    def torrent_natpmp(self, value: bool) -> None:
        self._set_bool("torrent_natpmp", value)

    @property
    def torrent_seed(self) -> bool:
        """Keep seeding after a torrent finishes downloading."""
        return self._get_bool("torrent_seed", True)

    @torrent_seed.setter
    def torrent_seed(self, value: bool) -> None:
        self._set_bool("torrent_seed", value)

    @property
    def torrent_ratio_limit(self) -> float:
        """Stop seeding at this upload/download ratio (0 = seed forever)."""
        raw = self._db.get_setting("torrent_ratio_limit")
        try:
            return max(0.0, float(raw)) if raw is not None else 2.0
        except ValueError:
            return 2.0

    @torrent_ratio_limit.setter
    def torrent_ratio_limit(self, value: float) -> None:
        self._db.set_setting("torrent_ratio_limit", str(value))

    @property
    def torrent_upload_kbps(self) -> int:
        """Upload speed cap for the whole torrent session (0 = unlimited)."""
        return max(0, self._get_int("torrent_upload_kbps", 0))

    @torrent_upload_kbps.setter
    def torrent_upload_kbps(self, value: int) -> None:
        self._db.set_setting("torrent_upload_kbps", str(value))

    @property
    def torrent_sequential(self) -> bool:
        """Default new torrents to in-order pieces (streaming-friendly)."""
        return self._get_bool("torrent_sequential", False)

    @torrent_sequential.setter
    def torrent_sequential(self, value: bool) -> None:
        self._set_bool("torrent_sequential", value)

    @property
    def torrent_dir(self) -> Path | None:
        """Where torrent content saves by default (None = the download dir)."""
        raw = self._db.get_setting("torrent_dir")
        return Path(raw) if raw else None

    @torrent_dir.setter
    def torrent_dir(self, value: Path | str | None) -> None:
        self._db.set_setting("torrent_dir", str(value) if value else "")

    @property
    def torrent_search_url(self) -> str:
        """Search template opened in the browser; %s is the query. Empty =
        the search action asks you to configure one first."""
        return self._db.get_setting("torrent_search_url") or ""

    @torrent_search_url.setter
    def torrent_search_url(self, value: str) -> None:
        self._db.set_setting("torrent_search_url", value.strip())

    @property
    def rss_feeds(self) -> tuple[str, ...]:
        """RSS/Atom feed lines: 'url' or 'url | must-contain filter'."""
        return self._get_str_list("rss_feeds")

    @rss_feeds.setter
    def rss_feeds(self, value: Sequence[str]) -> None:
        deduped = list(dict.fromkeys(v.strip() for v in value if v.strip()))
        self._db.set_setting("rss_feeds", json.dumps(deduped))

    @property
    def rss_interval_minutes(self) -> int:
        return max(5, min(24 * 60, self._get_int("rss_interval_minutes", 30)))

    @rss_interval_minutes.setter
    def rss_interval_minutes(self, value: int) -> None:
        self._db.set_setting("rss_interval_minutes", str(value))

    @property
    def rss_seen(self) -> tuple[str, ...]:
        """GUIDs/links already added from feeds (capped to the newest 500)."""
        return self._get_str_list("rss_seen")

    @rss_seen.setter
    def rss_seen(self, value: Sequence[str]) -> None:
        self._db.set_setting("rss_seen", json.dumps(list(value)[-500:]))

    @property
    def after_queue_action(self) -> str:
        """What to do once every download finishes: nothing / quit / sleep /
        shutdown / hibernate / lock."""
        raw = self._db.get_setting("after_queue_action")
        return raw if raw in _AFTER_QUEUE_ACTIONS else "nothing"

    @after_queue_action.setter
    def after_queue_action(self, value: str) -> None:
        if value not in _AFTER_QUEUE_ACTIONS:
            raise ValueError(f"unknown after-queue action: {value}")
        self._db.set_setting("after_queue_action", value)

    @property
    def download_days(self) -> tuple[int, ...]:
        """Weekdays downloads may run (0=Mon .. 6=Sun). All days when unset;
        an empty selection also means all days - you can't accidentally
        configure 'never download'."""
        raw = self._db.get_setting("download_days")
        if not raw:
            return (0, 1, 2, 3, 4, 5, 6)
        try:
            values = json.loads(raw)
        except ValueError:
            return (0, 1, 2, 3, 4, 5, 6)
        days = tuple(sorted({int(v) for v in values if 0 <= int(v) <= 6}))
        return days or (0, 1, 2, 3, 4, 5, 6)

    @download_days.setter
    def download_days(self, value: Sequence[int]) -> None:
        self._db.set_setting("download_days", json.dumps(sorted({int(v) for v in value})))

    @property
    def pause_on_battery(self) -> bool:
        """Battery mode: hold downloads while on battery, resume on AC."""
        return self._get_bool("pause_on_battery", False)

    @pause_on_battery.setter
    def pause_on_battery(self, value: bool) -> None:
        self._set_bool("pause_on_battery", value)

    @property
    def wait_for_network(self) -> bool:
        """Hold new downloads while the internet is unreachable and retry
        failed ones the moment it returns (instead of waiting out backoff)."""
        return self._get_bool("wait_for_network", False)

    @wait_for_network.setter
    def wait_for_network(self, value: bool) -> None:
        self._set_bool("wait_for_network", value)

    @property
    def sound_on_complete(self) -> bool:
        return self._get_bool("sound_on_complete", False)

    @sound_on_complete.setter
    def sound_on_complete(self, value: bool) -> None:
        self._set_bool("sound_on_complete", value)

    @property
    def sound_file(self) -> str:
        """A custom completion sound (empty = the platform default sound)."""
        return self._db.get_setting("sound_file") or ""

    @sound_file.setter
    def sound_file(self, value: str) -> None:
        self._db.set_setting("sound_file", value.strip())

    @property
    def script_on_complete(self) -> str:
        """A command run after each finished download, with the file path
        appended as the last argument (empty = off)."""
        return self._db.get_setting("script_on_complete") or ""

    @script_on_complete.setter
    def script_on_complete(self, value: str) -> None:
        self._db.set_setting("script_on_complete", value.strip())

    @property
    def playlist_batch_cap(self) -> int:
        """How many playlist entries get preselected (F1.7)."""
        return max(1, min(500, self._get_int("playlist_batch_cap", 30)))

    @playlist_batch_cap.setter
    def playlist_batch_cap(self, value: int) -> None:
        self._db.set_setting("playlist_batch_cap", str(max(1, min(500, value))))

    @property
    def ffmpeg_path(self) -> str | None:
        """Manual override; normally FFmpeg is found automatically."""
        return self._db.get_setting("ffmpeg_path") or None

    @ffmpeg_path.setter
    def ffmpeg_path(self, value: str | None) -> None:
        self._db.set_setting("ffmpeg_path", value or "")
