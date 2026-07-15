"""The Downloads detail drawer: a 292px panel that slides in beside the table
when a single download is selected. Shows its type, status, progress, a live
mini speed graph, metadata, tags, and quick actions — everything the selected
row can tell us, updated live while it stays open.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlsplit

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core.manager import DownloadManager, JobView
from app.core.models import JobStatus
from app.ui import components, design, motion, theme
from app.ui.format import human_bytes
from app.ui.icons import svg_icon, type_icon_name


def _meta_label(caption: str, value: str) -> QWidget:
    p = theme.current()
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    cap = QLabel(caption.upper())
    cap.setStyleSheet(
        f"color: {p.text3}; font-size: {design.FONT['caption']}pt;"
        f" font-weight: 700; letter-spacing: 0.5px;"
    )
    val = QLabel(value)
    val.setStyleSheet(f"color: {p.text}; font-size: {design.FONT['small']}pt;")
    val.setWordWrap(True)
    val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    lay.addWidget(cap)
    lay.addWidget(val)
    return box


class DetailDrawer(QFrame):
    def __init__(
        self,
        manager: DownloadManager,
        *,
        on_open_folder: Callable[[JobView], None],
        on_copy_url: Callable[[JobView], None],
        on_copy_hash: Callable[[JobView], None],
        on_remove: Callable[[JobView], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self._view: JobView | None = None
        self._callbacks = (on_open_folder, on_copy_url, on_copy_hash, on_remove)
        self.setFixedWidth(300)
        p = theme.current()
        self.setStyleSheet(f"background: {p.surface}; border-left: 1px solid {p.border};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setStyleSheet(f"border-bottom: 1px solid {p.border};")
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(14, 10, 8, 10)
        title = QLabel("DETAILS")
        title.setStyleSheet(
            f"color: {p.text3}; font-size: {design.FONT['caption']}pt;"
            f" font-weight: 700; letter-spacing: 1px;"
        )
        hlay.addWidget(title)
        hlay.addStretch(1)
        close = components.IconButton("cancel", "")
        close.clicked.connect(self.hide)
        hlay.addWidget(close)
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self._body = QVBoxLayout(body)
        self._body.setContentsMargins(14, 12, 14, 10)
        self._body.setSpacing(11)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # actions footer
        footer = QFrame()
        footer.setStyleSheet(f"border-top: 1px solid {p.border};")
        flay = QHBoxLayout(footer)
        flay.setContentsMargins(8, 7, 8, 7)
        flay.setSpacing(2)
        self._act_folder = components.IconButton("folder", "Folder")
        self._act_url = components.IconButton("copy", "URL")
        self._act_hash = components.IconButton("copy", "Hash")
        self._act_remove = components.IconButton("trash", "Remove", danger=True)
        self._act_folder.clicked.connect(lambda: self._fire(0))
        self._act_url.clicked.connect(lambda: self._fire(1))
        self._act_hash.clicked.connect(lambda: self._fire(2))
        self._act_remove.clicked.connect(lambda: self._fire(3))
        for b in (self._act_folder, self._act_url, self._act_hash, self._act_remove):
            flay.addWidget(b)
        root.addWidget(footer)

        self._spark = motion.Sparkline()
        self._spark.setFixedHeight(46)
        self.hide()

    def _fire(self, index: int) -> None:
        if self._view is not None:
            self._callbacks[index](self._view)

    def show_view(self, view: JobView, speed_bps: float) -> None:
        first = self._view is None or self._view.id != view.id
        self._view = view
        if first:
            self._spark = motion.Sparkline()
            self._spark.setFixedHeight(46)
            self._rebuild()
        self._update_live(view, speed_bps)
        self.show()

    def current_id(self) -> int | None:
        return self._view.id if self._view is not None else None

    def _rebuild(self) -> None:
        while self._body.count():
            item = self._body.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.deleteLater()
        view = self._view
        if view is None:
            return
        p = theme.current()

        # name + type icon
        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)
        icon = QLabel()
        kind = view.kind.value if view.kind.value in ("torrent", "cloud") else view.filename
        icon.setPixmap(svg_icon(type_icon_name(kind), p.accent).pixmap(16, 16))
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        name = QLabel(view.display_name)
        name.setWordWrap(True)
        name.setStyleSheet(f"font-weight: 600; font-size: {design.FONT['h2']}pt;")
        tl.addWidget(icon)
        tl.addWidget(name, 1)
        self._body.addWidget(top)

        self._pill = components.StatusPill(view.status.value)
        pill_row = QHBoxLayout()
        pill_row.addWidget(self._pill)
        pill_row.addStretch(1)
        self._body.addLayout(pill_row)

        self._progress = motion.SmoothProgressBar()
        self._body.addWidget(self._progress)
        self._prog_text = QLabel("")
        self._prog_text.setStyleSheet(f"color: {p.text3}; font-size: {design.FONT['small']}pt;")
        self._body.addWidget(self._prog_text)

        # mini speed card
        spark_card = components.card_frame()
        sc = QVBoxLayout(spark_card)
        sc.setContentsMargins(10, 8, 10, 8)
        cap = QLabel("SPEED · LAST 30s")
        cap.setStyleSheet(
            f"color: {p.text3}; font-size: {design.FONT['caption']}pt; font-weight: 700;"
        )
        sc.addWidget(cap)
        sc.addWidget(self._spark)
        self._spark_val = QLabel("—")
        self._spark_val.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._spark_val.setStyleSheet(f"color: {p.accent}; font-weight: 600;")
        sc.addWidget(self._spark_val)
        self._spark_card = spark_card
        self._body.addWidget(spark_card)

        # metadata
        queue = self._queue_name(view.queue_id)
        host = urlsplit(view.url).hostname or "—"
        self._body.addWidget(_meta_label("Queue", queue))
        self._body.addWidget(_meta_label("Server", host))
        self._eta_meta = _meta_label("ETA", "—")
        self._body.addWidget(self._eta_meta)
        self._body.addWidget(_meta_label("Destination", view.dest_dir))
        self._body.addWidget(_meta_label("URL", view.url))
        if view.tags:
            tags = QWidget()
            tw = QHBoxLayout(tags)
            tw.setContentsMargins(0, 0, 0, 0)
            tw.setSpacing(4)
            for tag in (t.strip() for t in view.tags.split(",") if t.strip()):
                tw.addWidget(components.Chip(tag))
            tw.addStretch(1)
            self._body.addWidget(tags)
        self._body.addStretch(1)

    def _update_live(self, view: JobView, speed_bps: float) -> None:
        self._pill.set_status(view.status.value)
        if view.total_size:
            self._progress.set_value(view.downloaded / view.total_size)
            self._prog_text.setText(
                f"{human_bytes(view.downloaded)} of {human_bytes(view.total_size)}"
            )
        elif view.status is JobStatus.DOWNLOADING:
            self._progress.set_indeterminate(True)
            self._prog_text.setText("Fetching metadata…")
        else:
            self._progress.set_value(1.0 if view.status is JobStatus.COMPLETED else 0.0)
            self._prog_text.setText("")
        self._progress.set_color(design.status_color(theme.current(), view.status.value))

        downloading = view.status is JobStatus.DOWNLOADING
        self._spark_card.setVisible(downloading)
        if downloading:
            self._spark.push(speed_bps)
            self._spark_val.setText(motion.fmt_speed(speed_bps))
            eta = "—"
            if speed_bps > 1 and view.total_size:
                eta = motion.fmt_eta((view.total_size - view.downloaded) / speed_bps)
            self._set_eta(eta)
        else:
            self._set_eta("—")
        self._act_hash.setVisible(view.status is JobStatus.COMPLETED)

    def _set_eta(self, text: str) -> None:
        # the meta value label is the second child of the eta meta box
        val = self._eta_meta.findChildren(QLabel)[-1]
        val.setText(text)

    def _queue_name(self, queue_id: int | None) -> str:
        if queue_id is None:
            return "Default"
        for q in self.manager.list_queues():
            if q.id == queue_id:
                return q.name
        return "Default"
