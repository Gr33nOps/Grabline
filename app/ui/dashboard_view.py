"""The embedded Dashboard page: live speed + volume tiles, area-chart cards
(download / upload / network / CPU / disk), a VPN banner, and per-server /
per-category tables. Its timer only runs while the page is on screen.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core import net
from app.core.manager import DownloadManager
from app.core.models import JobStatus
from app.core.stats import SpeedTracker, SystemSampler
from app.ui import components, motion, theme
from app.ui.format import human_bytes


def _pct(v: float) -> str:
    return f"{v:.0f}%"


class DashboardView(QWidget):
    def __init__(self, manager: DownloadManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self._speed = SpeedTracker()
        self._system = SystemSampler()
        p = theme.current()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(16)
        scroll.setWidget(body)

        self._tiles: dict[str, components.StatTile] = {}

        root.addWidget(components.SectionLabel("Speed"))
        root.addLayout(
            self._tile_row(
                [
                    ("current", "Current", False),  # data, not an action: no accent
                    ("average", "Average", False),
                    ("peak", "Peak", False),
                    ("eta", "ETA (all)", False),
                    ("active", "Active", False),
                ]
            )
        )
        root.addWidget(components.SectionLabel("Volume"))
        root.addLayout(
            self._tile_row(
                [
                    ("today", "Today", False),
                    ("week", "This week", False),
                    ("month", "This month", False),
                    ("lifetime", "Lifetime", False),
                    ("files", "Files", False),
                ]
            )
        )

        root.addWidget(components.SectionLabel("Graphs — last 60 seconds"))
        grid = QGridLayout()
        grid.setSpacing(10)
        self.g_download = components.GraphCard("Download", [p.g_dl], motion.fmt_speed)
        self.g_upload = components.GraphCard("Upload", [p.g_ul], motion.fmt_speed)
        self.g_network = components.GraphCard(
            "Network (system)", [p.g_ndown, p.g_nup], motion.fmt_speed
        )
        self.g_cpu = components.GraphCard("CPU", [p.g_cpu], _pct, fixed_max=100.0)
        self.g_disk = components.GraphCard("Disk I/O", [p.g_disk], motion.fmt_speed)
        grid.addWidget(self.g_download, 0, 0)
        grid.addWidget(self.g_upload, 0, 1)
        grid.addWidget(self.g_cpu, 1, 0)
        grid.addWidget(self.g_disk, 1, 1)
        grid.addWidget(self.g_network, 2, 0, 1, 2)
        root.addLayout(grid)

        self._vpn = QLabel("")
        self._vpn.setObjectName("VpnBanner")
        root.addWidget(self._vpn)

        tables = QHBoxLayout()
        tables.setSpacing(12)
        self.server_tree = self._table("Per server", "Host")
        self.category_tree = self._table("Per category", "Category")
        tables.addWidget(self._wrap(self.server_tree))
        tables.addWidget(self._wrap(self.category_tree))
        root.addLayout(tables)
        root.addStretch(1)

        self._timer = QTimer(self)
        # Settings → Statistics: sampling interval (default 500ms).
        self._timer.setInterval(self.manager.settings.dashboard_refresh_ms)
        self._timer.timeout.connect(self._tick)

    def _tile_row(self, specs: list[tuple[str, str, bool]]) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        for key, caption, accent in specs:
            tile = components.StatTile(caption, accent=accent)
            self._tiles[key] = tile
            row.addWidget(tile)
        return row

    def _table(self, _title: str, first: str) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderLabels([first, "Downloaded", "Files"])
        tree.setRootIsDecorated(False)
        tree.setColumnWidth(0, 190)
        return tree

    def _wrap(self, tree: QTreeWidget) -> QWidget:
        return tree

    # ------------------------------------------------------------- lifecycle

    def showEvent(self, event: object) -> None:
        super().showEvent(event)  # type: ignore[arg-type]
        self._tick()
        self._timer.start()

    def hideEvent(self, event: object) -> None:
        super().hideEvent(event)  # type: ignore[arg-type]
        self._timer.stop()

    def _tick(self) -> None:
        views = self.manager.snapshot()
        downloaded = sum(v.downloaded for v in views if v.status is JobStatus.DOWNLOADING)
        active = sum(1 for v in views if v.status is JobStatus.DOWNLOADING)
        remaining = sum(
            max(0, (v.total_size or 0) - v.downloaded)
            for v in views
            if v.status is JobStatus.DOWNLOADING and v.total_size
        )
        reading = self._speed.update(downloaded, remaining if active else None)
        self._tiles["current"].set_value(motion.fmt_speed(reading.current))
        self._tiles["average"].set_value(motion.fmt_speed(reading.average))
        self._tiles["peak"].set_value(motion.fmt_speed(reading.peak))
        self._tiles["eta"].set_value(motion.fmt_eta(reading.eta_seconds))
        self._tiles["active"].set_value(str(active), "downloads")

        totals = self.manager.stat_totals()
        self._tiles["today"].set_value(human_bytes(totals["today"]))
        self._tiles["week"].set_value(human_bytes(totals["week"]))
        self._tiles["month"].set_value(human_bytes(totals["month"]))
        self._tiles["lifetime"].set_value(human_bytes(totals["lifetime"]))
        self._tiles["files"].set_value(f"{totals['files']:,}", "total")

        system = self._system.sample()
        self.g_download.push([reading.current])
        self.g_upload.push([self.manager.torrent_upload_rate()])
        self.g_network.push([system.net_recv_per_sec, system.net_sent_per_sec])
        self.g_cpu.push([system.cpu_percent])
        self.g_disk.push([system.disk_bytes_per_sec])

        vpn = net.active_vpn_interfaces()
        if vpn:
            self._vpn.setText(f"VPN active — {', '.join(vpn)}    ·    No geo lookup")
        else:
            self._vpn.setText("VPN not detected")

        self._fill(self.server_tree, self.manager.stats_by_host())
        self._fill(self.category_tree, self.manager.stats_by_category())

    @staticmethod
    def _fill(tree: QTreeWidget, rows: list[tuple[str, int, int]]) -> None:
        p = theme.current()
        tree.clear()
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        from PySide6.QtGui import QColor

        for name, byte_count, files in rows:
            item = QTreeWidgetItem([name, human_bytes(byte_count), str(files)])
            item.setForeground(1, QColor(p.accent))
            item.setTextAlignment(1, right)
            item.setTextAlignment(2, right)
            tree.addTopLevelItem(item)
