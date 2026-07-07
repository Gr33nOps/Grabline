"""Grabline Desktop entry point: ``python -m app`` (or the ``grabline`` script)."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from app.core import instance, paths
from app.core.ffmpeg import find_ffmpeg
from app.core.manager import DownloadManager
from app.core.settings import Settings
from app.db.database import Database
from app.ui.clipboard import ClipboardWatcher
from app.ui.icon import make_app_icon
from app.ui.main_window import MainWindow
from app.ui.tray import GrablineTray

log = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Grabline")
    app.setOrganizationName("Grabline")

    data_dir = paths.data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(data_dir / "grabline.db")
    interrupted = db.mark_interrupted()
    if interrupted:
        log.info("recovered %d unfinished download(s) from last session", interrupted)

    settings = Settings(db)
    settings.download_dir.mkdir(parents=True, exist_ok=True)
    manager = DownloadManager(db, settings=settings)

    window = MainWindow(manager, settings)
    window.setWindowIcon(make_app_icon())
    if find_ffmpeg(settings) is None:
        window.statusBar().showMessage(
            "FFmpeg not found — install it in Settings to enable MP3, merging, and streams"
        )

    tray: GrablineTray | None = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = GrablineTray(window)
        tray.show()
        app.setQuitOnLastWindowClosed(False)
        window.close_to_tray = True

    watcher = ClipboardWatcher(app, settings)
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

    window.show()
    instance.write_pid()  # lets the Native Messaging host report "app running"

    def shutdown() -> None:
        instance.clear_pid()
        manager.shutdown()
        db.close()

    app.aboutToQuit.connect(shutdown)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
