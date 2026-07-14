"""Grabline Desktop entry point: ``python -m app`` (or the ``grabline`` script)."""

from __future__ import annotations

import logging
import sys
import threading

from PySide6.QtCore import QBuffer, QIODevice, QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

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


def main() -> int:
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
    app = QApplication([arg for arg in sys.argv if arg != "--minimized"])
    app.setApplicationName("Grabline")
    app.setOrganizationName("Grabline")

    try:
        # IDM-style install-less integration: first run puts Grabline in the
        # application menu; later runs heal the entry if the install moved.
        launcher.install_menu_entry(icon_png=_icon_png())
    except OSError:
        log.warning("could not write the application-menu entry", exc_info=True)

    data_dir = paths.data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(data_dir / "grabline.db")
    interrupted = db.mark_interrupted()
    if interrupted:
        log.info("recovered %d unfinished download(s) from last session", interrupted)

    settings = Settings(db)
    settings.download_dir.mkdir(parents=True, exist_ok=True)
    _register_native_host_once(settings)
    theme.remember_default(app)
    theme.apply_theme(app, settings.theme)
    manager = DownloadManager(db, settings=settings)

    window = MainWindow(manager, settings)
    window.setWindowIcon(make_app_icon())

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

    def on_job_completed(name: str, file_path: str) -> None:
        if tray is not None and settings.notify_on_complete:
            tray.showMessage(
                "Download complete",
                name,
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )
        if settings.sound_on_complete:
            alerts.play_complete_sound(settings.sound_file)
        if settings.script_on_complete:
            scripts.run_script(settings.script_on_complete, file_path)

    def on_queue_drained() -> None:
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
    window.queue_drained.connect(on_queue_drained)

    if not settings.setup_seen and not minimized:
        # First launch: show the Browser Setup wizard once.
        settings.setup_seen = True
        QTimer.singleShot(400, window.open_setup)

    if settings.check_updates:
        # A few seconds after launch so it never delays the window appearing.
        QTimer.singleShot(3000, lambda: window.check_for_updates(quiet=True))

    if minimized and tray is not None:
        log.info("started minimized to the tray (autostart)")
    else:
        window.show()
    if open_with is not None:
        kind, source = open_with
        opener = window.add_torrent_source if kind == "torrent" else window.add_cloud_source
        QTimer.singleShot(400, lambda: opener(source))
    instance.write_pid()  # lets the Native Messaging host report "app running"

    def shutdown() -> None:
        instance.clear_pid()
        manager.shutdown()
        db.close()

    app.aboutToQuit.connect(shutdown)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
