"""Grabline Desktop entry point: ``python -m app`` (or the ``grabline`` script)."""

from __future__ import annotations

import contextlib
import logging
import sys
import threading
import traceback
from types import TracebackType
from typing import TextIO

from PySide6.QtCore import QBuffer, QIODevice, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from app.core import alerts, instance, launcher, paths, power, scripts
from app.core.ffmpeg import find_ffmpeg
from app.core.manager import DownloadManager
from app.core.settings import Settings
from app.db.database import Database
from app.ui import theme
from app.ui.clipboard import ClipboardWatcher
from app.ui.icon import make_app_icon
from app.ui.main_window import MainWindow
from app.ui.tray import GrablineTray

log = logging.getLogger(__name__)


def _icon_png() -> bytes:
    pixmap = make_app_icon().pixmap(256, 256)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    # QByteArray -> bytes; the stubs type .data() as a union, so normalize.
    return bytes(bytearray(buffer.data().data()))


def _register_native_host_once(settings: Settings) -> None:
    """On the first run of an installed (frozen) build, register the Native
    Messaging host so the browser extension pairs without the user opening
    Settings. Idempotent and best-effort; re-pairing lives in Settings. Only
    frozen builds self-register - from source the user runs the installer
    command, so we don't scribble manifests into a dev machine's browsers."""
    if settings.host_registered or not getattr(sys, "frozen", False):
        return
    try:
        from app.native_host.install import install

        install()
        settings.host_registered = True
        log.info("registered the Native Messaging host for installed browsers")
    except Exception:  # never block startup on pairing
        log.warning("first-run native-host registration failed", exc_info=True)


def _open_arg(args: list[str]) -> tuple[str, str] | None:
    """A magnet link, .torrent path, or cloud address (sftp/ftp/s3/…) passed
    on the command line ('open with Grabline' / double-clicked file), or None.
    Returns (kind, source) where kind is "torrent" or "cloud"."""
    from app.engines.cloud import is_cloud_scheme

    for arg in args:
        if arg.startswith("-"):
            continue
        if arg.lower().startswith("magnet:"):
            return "torrent", arg
        if arg.lower().endswith(".torrent"):
            from pathlib import Path

            path = Path(arg)
            return "torrent", str(path.resolve()) if path.exists() else arg
        if is_cloud_scheme(arg):
            return "cloud", arg
    return None


def _configure_logging(settings: Settings) -> None:
    """Apply the configured level (and grabline.log, if on) once settings load."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.getLogger().setLevel(level)
    if settings.log_to_file:
        handler = logging.FileHandler(paths.data_dir() / "grabline.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)


def _install_crash_hooks(crash_log: TextIO | None) -> None:
    """Route uncaught Python exceptions - on the GUI thread and on worker
    threads - to crash.log with a full traceback. faulthandler catches native
    aborts (a QThread destroyed while running); these hooks catch the Python
    exceptions that would otherwise vanish when Qt swallows a slot exception or
    a daemon thread dies. Both write to the same file the user already sends."""

    def _write(
        header: str,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        log.error("%s", header, exc_info=exc)
        if crash_log is not None:
            try:
                crash_log.write(f"\n=== {header} ===\n")
                traceback.print_exception(exc_type, exc, tb, file=crash_log)
                crash_log.flush()
            except (OSError, ValueError):
                pass

    def _excepthook(
        exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
    ) -> None:
        _write("uncaught exception (GUI thread)", exc_type, exc, tb)

    def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
        _write(
            f"uncaught exception (thread {args.thread})",
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
        )

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook


def _set_windows_app_id() -> None:
    """Give Windows an explicit application id.

    Without one, a frozen Python app is grouped in the taskbar under the host
    executable, its icon can be wrong, and pinning a running window creates a
    second entry. The id must match the Start-menu shortcut's target for
    pinning to behave, and must be set before the first window exists."""
    if sys.platform != "win32":  # pragma: no cover - windows-only
        return
    import ctypes

    with contextlib.suppress(AttributeError, OSError):
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Grabline")


def main() -> int:
    # A native-crash trace (faulthandler) to the data folder: if anything
    # segfaults, crash.log says where instead of a silent vanish.
    import faulthandler

    _crash_log = None
    try:
        _crash_log = open(paths.data_dir() / "crash.log", "a")  # noqa: SIM115 - lives for the process
        faulthandler.enable(_crash_log)
    except OSError:
        pass
    _install_crash_hooks(_crash_log)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    minimized = "--minimized" in sys.argv
    open_with = _open_arg(sys.argv[1:])
    if open_with is not None and instance.app_is_running():
        # 'Open with Grabline' while it's already open: hand the source to the
        # running instance (it polls the handoffs table) and bow out.
        kind, source = open_with
        handoff_db = Database(paths.data_dir() / "grabline.db")
        handoff_db.add_handoff(source, source=kind)
        handoff_db.close()
        return 0
    _set_windows_app_id()  # before any window exists, or the taskbar ignores it
    app = QApplication([arg for arg in sys.argv if arg != "--minimized"])
    app.setApplicationName("Grabline")
    app.setOrganizationName("Grabline")
    app.setApplicationDisplayName("Grabline")
    # Ties windows to grabline.desktop on Wayland and modern X11 shells, so the
    # dock shows the real name and icon instead of a generic placeholder.
    app.setDesktopFileName("grabline")

    data_dir = paths.data_dir()
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write-test"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        # Nothing works without this folder - say which one, and why, instead
        # of failing later with a confusing database error.
        QMessageBox.critical(
            None,
            "Grabline",
            f"Grabline cannot use its data folder:\n\n{data_dir}\n\n{exc}\n\n"
            "Check the folder's permissions, or that the drive is available.",
        )
        return 1

    try:
        # IDM-style install-less integration: first run puts Grabline in the
        # application menu; later runs heal the entry if the install moved.
        launcher.install_menu_entry(icon_png=_icon_png())
    except OSError:
        log.warning("could not write the application-menu entry", exc_info=True)

    db = Database(data_dir / "grabline.db")
    interrupted = db.mark_interrupted()
    if interrupted:
        log.info("recovered %d unfinished download(s) from last session", interrupted)

    settings = Settings(db)
    settings.download_dir.mkdir(parents=True, exist_ok=True)
    _register_native_host_once(settings)
    theme.remember_default(app)
    _configure_logging(settings)
    theme.apply_theme(app, settings.theme, accent=settings.accent_color or None)
    manager = DownloadManager(db, settings=settings)

    window = MainWindow(manager, settings)
    app_icon = make_app_icon()
    app.setWindowIcon(app_icon)  # dialogs' native title bars show the logo too
    window.setWindowIcon(app_icon)

    # Warm yt-dlp's extractor list off the UI thread so the first paste/grab
    # doesn't stall for a second while 1000+ extractors are enumerated.
    def _warm_extractors() -> None:
        try:
            window.resolver.smart.matches("https://www.youtube.com/watch?v=warmup")
        except Exception:  # pragma: no cover - warmup is best effort
            log.debug("extractor warmup failed", exc_info=True)

    threading.Thread(target=_warm_extractors, name="gl-warmup", daemon=True).start()

    if find_ffmpeg(settings) is None:
        window.statusBar().showMessage(
            "FFmpeg not found - install it in Settings to enable MP3, merging, and streams"
        )

    tray: GrablineTray | None = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = GrablineTray(window)
        tray.show()
        app.setQuitOnLastWindowClosed(False)
        window.close_to_tray = True
        window.tray = tray

    watcher = ClipboardWatcher(app, settings)
    window.clipboard_suppressor = watcher.suppress
    pending_clipboard_url: list[str] = []

    def on_url_copied(url: str) -> None:
        if tray is not None:
            pending_clipboard_url.clear()
            pending_clipboard_url.append(url)
            tray.showMessage(
                "Download with Grabline?",
                f"{url}\nClick to choose quality and download.",
                QSystemTrayIcon.MessageIcon.Information,
                6000,
            )
        else:
            window.begin_add_url(url)

    def on_message_clicked() -> None:
        if pending_clipboard_url:
            window.show()
            window.raise_()
            window.begin_add_url(pending_clipboard_url.pop())

    watcher.url_copied.connect(on_url_copied)
    if tray is not None:
        tray.messageClicked.connect(on_message_clicked)

    def toast(title: str, body: str, icon: QSystemTrayIcon.MessageIcon) -> None:
        # One gate for every notification: tray present + outside quiet hours.
        if tray is not None and not settings.in_quiet_hours():
            tray.showMessage(title, body, icon, settings.toast_seconds * 1000)

    def on_job_completed(name: str, file_path: str) -> None:
        if settings.notify_on_complete:
            toast("Download complete", name, QSystemTrayIcon.MessageIcon.Information)
        if settings.sound_on_complete and not settings.in_quiet_hours():
            alerts.play_complete_sound(settings.sound_file)
        if settings.script_on_complete:
            scripts.run_script(settings.script_on_complete, file_path)

    def on_job_failed(name: str, error: str) -> None:
        if settings.notify_on_failed:
            toast(f"Download failed: {name}", error, QSystemTrayIcon.MessageIcon.Warning)

    def on_queue_drained() -> None:
        if settings.notify_queue_done:
            toast(
                "Queue finished",
                "Every download has completed.",
                QSystemTrayIcon.MessageIcon.Information,
            )
        action = settings.after_queue_action
        if action == "nothing":
            return
        log.info("all downloads finished; after-queue action: %s", action)
        if action == "quit":
            app.quit()
        elif action == "sleep":
            power.sleep()
        elif action == "shutdown":
            power.shutdown()
        elif action == "hibernate":
            power.hibernate()
        elif action == "lock":
            power.lock()

    window.job_completed.connect(on_job_completed)
    window.job_failed.connect(on_job_failed)
    window.queue_drained.connect(on_queue_drained)

    if not settings.setup_seen and not minimized:
        # First launch: show the Browser Setup wizard once.
        settings.setup_seen = True
        QTimer.singleShot(400, window.open_setup)

    # Warm up yt-dlp off the UI thread: its first import loads 1700+ extractor
    # classes (seconds on Windows, worse under antivirus). Paying that at
    # launch instead of on the first video add is why the first YouTube
    # download used to feel slow.
    def _warm_up() -> None:
        try:
            import yt_dlp  # noqa: F401
            from yt_dlp.extractor import gen_extractor_classes

            gen_extractor_classes()
            from app.core import jsruntime

            jsruntime.detect_js_runtime()
            # YouTube merges separate video+audio, so it needs FFmpeg. Fetch it
            # now, in the background, so the *first* video download doesn't stall
            # waiting on a one-time ~30 MB download.
            from app.core.ffmpeg import ensure_ffmpeg, find_ffmpeg

            if find_ffmpeg(settings) is None:
                ensure_ffmpeg(proxy=settings.proxy)
        except Exception:  # never let warm-up break startup
            log.debug("yt-dlp warm-up failed", exc_info=True)

    threading.Thread(target=_warm_up, name="gl-warmup", daemon=True).start()

    if settings.check_updates:
        # A few seconds after launch so it never delays the window appearing.
        QTimer.singleShot(3000, lambda: window.check_for_updates(quiet=True))

    if (minimized or settings.start_minimized) and tray is not None:
        log.info("started minimized to the tray")
    else:
        window.show()
    if open_with is not None:
        kind, source = open_with
        opener = window.add_torrent_source if kind == "torrent" else window.add_cloud_source
        QTimer.singleShot(400, lambda: opener(source))
    instance.write_pid()  # lets the Native Messaging host report "app running"

    def shutdown() -> None:
        instance.clear_pid()
        # Ordered teardown: stop UI polling first (so no timer touches the db
        # after it closes), then drain retained worker threads (destroying a
        # running QThread aborts the process), then stop the engine and close
        # the database last.
        window.shutdown()
        from app.ui import threads

        threads.shutdown()
        manager.shutdown()
        db.close()

    app.aboutToQuit.connect(shutdown)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
