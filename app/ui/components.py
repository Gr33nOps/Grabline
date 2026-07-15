"""Reusable, theme-aware widgets shared across the redesigned screens: status
pills, stat tiles, tag chips, flat icon buttons, sidebar nav buttons, section
labels, and a small area-graph card. Every one reads its colors from
``theme.current()`` so light/dark just works.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui import design, theme
from app.ui.icons import svg_icon

_GRAPH_HISTORY = 120

_STATUS_LABEL = {
    "downloading": "Downloading",
    "queued": "Queued",
    "paused": "Paused",
    "completed": "Completed",
    "failed": "Failed",
    "cancelled": "Cancelled",
}


class StatusPill(QLabel):
    """A colored, rounded status label. Downloading pulses a subtle dot."""

    def __init__(self, status: str = "queued", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_status(status)

    def set_status(self, status: str) -> None:
        p = theme.current()
        color = design.status_color(p, status)
        label = _STATUS_LABEL.get(status, status.title())
        self.setText(label)
        self.setStyleSheet(
            f"QLabel {{ color: {color}; background: {_dim(color, 0.14)};"
            f" border-radius: 4px; padding: 2px 8px; font-size: {design.FONT['small']}pt;"
            f" font-weight: 600; }}"
        )


def _dim(hex_color: str, alpha: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


class Chip(QLabel):
    """A small tag/label chip."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        p = theme.current()
        self.setStyleSheet(
            f"QLabel {{ color: {p.text2}; background: {p.surface2};"
            f" border: 1px solid {p.border}; border-radius: 3px; padding: 1px 7px;"
            f" font-size: {design.FONT['small']}pt; }}"
        )


class SectionLabel(QLabel):
    """An all-caps, muted section heading."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text.upper(), parent)
        p = theme.current()
        self.setStyleSheet(
            f"QLabel {{ color: {p.text3}; font-size: {design.FONT['caption']}pt;"
            f" font-weight: 700; letter-spacing: 1px; }}"
        )


class StatTile(QFrame):
    """A big-number + caption tile (dashboard)."""

    def __init__(self, caption: str, accent: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        p = theme.current()
        self.setStyleSheet(
            f"QFrame {{ background: {p.surface}; border: 1px solid {p.border};"
            f" border-radius: {design.RADIUS['md']}px; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(3)
        cap = QLabel(caption.upper())
        cap.setStyleSheet(
            f"color: {p.text3}; font-size: {design.FONT['caption']}pt;"
            f" font-weight: 700; letter-spacing: 0.6px;"
        )
        self.value = QLabel("—")
        self.value.setStyleSheet(
            f"color: {p.accent if accent else p.text}; font-size: {design.FONT['display']}pt;"
            f" font-weight: 700;"
        )
        self.sub = QLabel("")
        self.sub.setStyleSheet(f"color: {p.text3}; font-size: {design.FONT['small']}pt;")
        self.sub.hide()
        lay.addWidget(cap)
        lay.addWidget(self.value)
        lay.addWidget(self.sub)

    def set_value(self, text: str, sub: str = "") -> None:
        self.value.setText(text)
        if sub:
            self.sub.setText(sub)
            self.sub.show()


class IconButton(QPushButton):
    """A flat, icon-first toolbar button; optional text label."""

    def __init__(
        self,
        icon_name: str,
        label: str = "",
        *,
        danger: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._danger = danger
        self.setProperty("flat", "true")
        if danger:
            self.setProperty("danger", "true")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if label:
            self.setText("  " + label)
        self.setIconSize(QSize(16, 16))
        self.retint()

    def retint(self) -> None:
        p = theme.current()
        color = p.st_failed if self._danger else p.text2
        self.setIcon(svg_icon(self._icon_name, color))


class SidebarButton(QPushButton):
    """A 36px square nav button for the left rail; active state uses the accent."""

    def __init__(self, icon_name: str, tooltip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._active = False
        self.setToolTip(tooltip)
        self.setFixedSize(38, 38)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(19, 19))
        self.retint()

    def set_active(self, active: bool) -> None:
        self._active = active
        self.setChecked(active)
        self.retint()

    def retint(self) -> None:
        p = theme.current()
        color = p.accent if self._active else p.text3
        self.setIcon(svg_icon(self._icon_name, color))
        bg = p.accent_dim if self._active else "transparent"
        self.setStyleSheet(
            f"QPushButton {{ border: none; border-radius: {design.RADIUS['md']}px;"
            f" background: {bg}; }}"
            f" QPushButton:hover {{ background: {p.row_hover}; }}"
        )


class GraphCard(QFrame):
    """A titled area-chart card (dashboard). Feed samples with :meth:`push`;
    draws one or two series over a shared auto-scaled axis."""

    def __init__(
        self,
        title: str,
        colors: list[str],
        fmt: Callable[[float], str],
        *,
        fixed_max: float | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.title = title
        self._colors = colors
        self._fmt = fmt
        self._fixed_max = fixed_max
        self._series: list[deque[float]] = [deque(maxlen=_GRAPH_HISTORY) for _ in colors]
        p = theme.current()
        self.setStyleSheet(
            f"QFrame {{ background: {p.surface}; border: 1px solid {p.border};"
            f" border-radius: {design.RADIUS['md']}px; }}"
        )
        self.setMinimumHeight(118)

    def push(self, values: list[float]) -> None:
        for serie, v in zip(self._series, values, strict=False):
            serie.append(max(0.0, v))
        self.update()

    def _scale(self) -> float:
        if self._fixed_max is not None:
            return self._fixed_max
        peak = max((max(s, default=0.0) for s in self._series), default=0.0)
        return peak or 1.0

    def paintEvent(self, _event: object) -> None:
        p = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        # title + latest readout
        painter.setPen(QColor(p.text2))
        painter.drawText(rect.adjusted(12, 9, -12, 0), int(Qt.AlignmentFlag.AlignLeft), self.title)
        latest = " · ".join(self._fmt(s[-1]) for s in self._series if s)
        painter.setPen(QColor(self._colors[0]))
        painter.drawText(rect.adjusted(12, 9, -12, 0), int(Qt.AlignmentFlag.AlignRight), latest)
        plot = rect.adjusted(12, 30, -12, -12)
        if plot.width() < 4 or plot.height() < 4:
            painter.end()
            return
        # subtle baseline grid
        grid = QColor(p.border2)
        painter.setPen(QPen(grid, 1, Qt.PenStyle.DashLine))
        for f in (0.5, 1.0):
            y = plot.bottom() - f * plot.height()
            painter.drawLine(plot.left(), int(y), plot.right(), int(y))
        scale = self._scale()
        for serie, hexc in zip(self._series, self._colors, strict=False):
            if len(serie) < 2:
                continue
            color = QColor(hexc)
            step = plot.width() / (_GRAPH_HISTORY - 1)
            off = _GRAPH_HISTORY - len(serie)
            base = plot.bottom()
            pts = [
                QPointF(
                    plot.left() + (off + i) * step,
                    base - min(1.0, v / scale) * plot.height(),
                )
                for i, v in enumerate(serie)
            ]
            fill = QColor(color)
            fill.setAlpha(38)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawPolygon(
                QPolygonF([QPointF(pts[0].x(), base), *pts, QPointF(pts[-1].x(), base)])
            )
            painter.setPen(QPen(color, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolyline(QPolygonF(pts))
        painter.end()


def accent_button(text: str) -> QPushButton:
    """A primary (accent-filled) button."""
    btn = QPushButton(text)
    btn.setProperty("accent", "true")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def card_frame() -> QFrame:
    p = theme.current()
    frame = QFrame()
    frame.setStyleSheet(
        f"QFrame {{ background: {p.surface}; border: 1px solid {p.border};"
        f" border-radius: {design.RADIUS['md']}px; }}"
    )
    return frame


def hline() -> QFrame:
    p = theme.current()
    line = QFrame()
    line.setFixedWidth(1)
    line.setStyleSheet(f"background: {p.border};")
    return line


def app_logo(size: int = 28) -> QLabel:
    """The rounded-square blue app mark with the white download glyph."""
    p = theme.current()
    label = QLabel()
    label.setFixedSize(size, size)
    label.setStyleSheet(f"background: {p.accent}; border-radius: {design.RADIUS['md']}px;")
    label.setPixmap(svg_icon("download", "#ffffff").pixmap(int(size * 0.6), int(size * 0.6)))
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label
