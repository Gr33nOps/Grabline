"""The Downloads detail drawer: a 300px panel that shows beside the table when
a single download is selected. Its widgets are built once and only their text /
visibility change as the selection or live progress updates - no teardown and
rebuild - so nothing flickers or doubles up, and it stays cheap to keep live.
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
        self.setObjectName("Drawer")
        self.setFixedWidth(300)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- header ---------------------------------------------------------
        header = QFrame()
        header.setObjectName("DrawerHeader")
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(14, 10, 8, 10)
        title = components.role_label("DETAILS", "caption", size=design.FONT["caption"])
        hlay.addWidget(title)
        hlay.addStretch(1)
        close = components.IconButton("cancel", "")
        close.clicked.connect(self.hide)
        hlay.addWidget(close)
        root.addWidget(header)

        # ---- body (static widgets, filled in _update) -----------------------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self._body = QVBoxLayout(body)
        self._body.setContentsMargins(14, 12, 14, 12)
        self._body.setSpacing(11)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # name + type icon
        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)
        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._icon.setFixedWidth(18)
        self._name = components.role_label("", "strong", size=design.FONT["h2"], bold=True)
        self._name.setWordWrap(True)
        tl.addWidget(self._icon)
        tl.addWidget(self._name, 1)
        self._body.addWidget(top)

        # status pill
        pill_row = QHBoxLayout()
        self._pill = components.StatusPill("queued")
        pill_row.addWidget(self._pill)
        pill_row.addStretch(1)
        self._body.addLayout(pill_row)

        # progress bar + percent
        prow = QHBoxLayout()
        prow.setSpacing(8)
        self._progress = motion.SmoothProgressBar()
        self._percent = components.role_label("", "muted", size=design.FONT["small"])
        self._percent.setMinimumWidth(30)
        self._percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        prow.addWidget(self._progress, 1)
        prow.addWidget(self._percent, 0, Qt.AlignmentFlag.AlignVCenter)
        self._body.addLayout(prow)

        self._size = components.role_label("", "muted", size=design.FONT["small"])
        self._body.addWidget(self._size)

        # live speed card
        self._spark = motion.Sparkline()
        self._spark.setFixedHeight(52)
        self._spark_card = components.card_frame()
        sc = QVBoxLayout(self._spark_card)
        sc.setContentsMargins(11, 9, 11, 9)
        sc.setSpacing(4)
        sc.addWidget(
            components.role_label("SPEED · LAST 30s", "caption", size=design.FONT["caption"])
        )
        sc.addWidget(self._spark)
        self._spark_val = components.role_label("—", "accent", size=design.FONT["h2"], bold=True)
        self._spark_val.setAlignment(Qt.AlignmentFlag.AlignRight)
        sc.addWidget(self._spark_val)
        self._body.addWidget(self._spark_card)

        # metadata
        self._meta_queue = self._meta_block("Queue")
        self._meta_server = self._meta_block("Server")
        self._meta_eta = self._meta_block("ETA")
        self._meta_dest = self._meta_block("Destination")
        self._meta_url = self._meta_block("URL")

        # tags (the only variable-count part - rebuilt in place)
        self._tags_box = QWidget()
        self._tags_layout = QHBoxLayout(self._tags_box)
        self._tags_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_layout.setSpacing(4)
        self._body.addWidget(self._tags_box)
        self._body.addStretch(1)

        # ---- actions footer -------------------------------------------------
        footer = QFrame()
        footer.setObjectName("DrawerFooter")
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

        self.hide()

    def _meta_block(self, caption: str) -> QLabel:
        """A caption + value pair; returns the value label to fill in later."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(
            components.role_label(caption.upper(), "caption", size=design.FONT["caption"])
        )
        value = components.role_label("—", "value", size=design.FONT["small"])
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(value)
        self._body.addWidget(box)
        return value

    def _fire(self, index: int) -> None:
        if self._view is not None:
            self._callbacks[index](self._view)

    def show_view(self, view: JobView, speed_bps: float) -> None:
        new = self._view is None or self._view.id != view.id
        if new:
            self._spark.clear()
        self._view = view
        self._update(view, speed_bps, new)
        self.show()

    def current_id(self) -> int | None:
        return self._view.id if self._view is not None else None

    def _update(self, view: JobView, speed_bps: float, new: bool) -> None:
        p = theme.current()
        if new:
            kind = view.kind.value if view.kind.value in ("torrent", "cloud") else view.filename
            self._icon.setPixmap(svg_icon(type_icon_name(kind), p.accent).pixmap(16, 16))
            self._name.setText(view.display_name)
            self._meta_queue.setText(self._queue_name(view.queue_id))
            self._meta_server.setText(urlsplit(view.url).hostname or "—")
            self._meta_dest.setText(view.dest_dir)
            self._meta_url.setText(view.url)
            self._rebuild_tags(view)

        self._pill.set_status(view.status.value)
        self._progress.set_color(design.status_color(p, view.status.value))
        if view.total_size:
            fraction = view.downloaded / view.total_size
            self._progress.set_value(fraction)
            self._percent.setText(f"{int(fraction * 100)}%")
            self._size.setText(f"{human_bytes(view.downloaded)} of {human_bytes(view.total_size)}")
        elif view.status is JobStatus.DOWNLOADING:
            self._progress.set_indeterminate(True)
            self._percent.setText("")
            self._size.setText("Fetching metadata…")
        else:
            self._progress.set_value(1.0 if view.status is JobStatus.COMPLETED else 0.0)
            self._percent.setText("")
            self._size.setText("")

        downloading = view.status is JobStatus.DOWNLOADING
        self._spark_card.setVisible(downloading)
        if downloading:
            self._spark.push(speed_bps)
            self._spark_val.setText(motion.fmt_speed(speed_bps))
            eta = "—"
            if speed_bps > 1 and view.total_size:
                eta = motion.fmt_eta((view.total_size - view.downloaded) / speed_bps)
            self._meta_eta.setText(eta)
        else:
            self._meta_eta.setText("—")
        self._act_hash.setVisible(view.status is JobStatus.COMPLETED)

    def _rebuild_tags(self, view: JobView) -> None:
        while self._tags_layout.count():
            item = self._tags_layout.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.deleteLater()
        tags = [t.strip() for t in view.tags.split(",") if t.strip()] if view.tags else []
        for tag in tags:
            self._tags_layout.addWidget(components.Chip(tag))
        self._tags_layout.addStretch(1)
        self._tags_box.setVisible(bool(tags))

    def _queue_name(self, queue_id: int | None) -> str:
        if queue_id is None:
            return "Default"
        for q in self.manager.list_queues():
            if q.id == queue_id:
                return q.name
        return "Default"
