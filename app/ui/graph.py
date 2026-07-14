"""A small multi-series time-graph widget for the dashboard - filled line
charts that scroll left as new samples arrive. Theme-aware: it paints with
the current palette so it reads in light and dark.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

_HISTORY = 120  # samples kept (~1 min at the 500ms refresh)


class Series:
    def __init__(self, name: str, color: QColor) -> None:
        self.name = name
        self.color = color
        self.samples: deque[float] = deque(maxlen=_HISTORY)


class TimeGraph(QWidget):
    """One or more series on a shared, auto-scaling y-axis. ``fmt`` renders the
    latest value into the corner readout (bytes/sec, percent, ...)."""

    def __init__(
        self,
        title: str,
        series: list[Series],
        fmt: Callable[[float], str],
        *,
        fixed_max: float | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.title = title
        self.series = series
        self._fmt = fmt
        self._fixed_max = fixed_max
        self.setMinimumHeight(110)

    def push(self, values: list[float]) -> None:
        for value, serie in zip(values, self.series, strict=False):
            serie.samples.append(max(0.0, value))
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(260, 120)

    def _scale_max(self) -> float:
        if self._fixed_max is not None:
            return self._fixed_max
        peak = max((max(s.samples, default=0.0) for s in self.series), default=0.0)
        return peak if peak > 0 else 1.0

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text_color = self.palette().color(self.palette().ColorRole.WindowText)
        muted = QColor(text_color)
        muted.setAlpha(120)

        border = QColor(text_color)
        border.setAlpha(40)
        frame = self.rect().adjusted(1, 1, -2, -2)
        painter.setPen(QPen(border, 1))
        painter.drawRect(frame)

        plot = frame.adjusted(6, 20, -6, -6)
        scale = self._scale_max()
        if plot.width() > 4 and plot.height() > 4:
            for serie in self.series:
                if len(serie.samples) < 2:
                    continue
                step = plot.width() / (_HISTORY - 1)
                baseline = plot.bottom()
                offset = _HISTORY - len(serie.samples)
                points = [
                    QPointF(
                        plot.left() + (offset + i) * step,
                        baseline - min(1.0, value / scale) * plot.height(),
                    )
                    for i, value in enumerate(serie.samples)
                ]
                fill = QColor(serie.color)
                fill.setAlpha(45)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawPolygon(
                    QPolygonF(
                        [
                            QPointF(points[0].x(), baseline),
                            *points,
                            QPointF(points[-1].x(), baseline),
                        ]
                    )
                )
                painter.setPen(QPen(serie.color, 1.5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolyline(QPolygonF(points))

        painter.setPen(text_color)
        painter.drawText(
            frame.adjusted(6, 3, -6, 0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            self.title,
        )
        # Latest value(s) in the top-right, colored per series.
        readouts = " · ".join(self._fmt(s.samples[-1]) for s in self.series if s.samples)
        painter.setPen(muted)
        painter.drawText(
            frame.adjusted(6, 3, -6, 0),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop),
            readouts,
        )
        painter.end()
