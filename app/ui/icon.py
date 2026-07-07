"""The Grabline icon, painted in code so Phase 0 ships no binary assets."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


def make_app_icon(size: int = 64) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#2563eb"))
    margin = size * 0.06
    painter.drawEllipse(QPointF(size / 2, size / 2), size / 2 - margin, size / 2 - margin)

    pen = QPen(QColor("white"), size * 0.10)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    # Arrow shaft, arrow head, and a base line: the classic download glyph.
    painter.drawLine(QPointF(size * 0.50, size * 0.24), QPointF(size * 0.50, size * 0.58))
    painter.drawPolyline(
        [
            QPointF(size * 0.34, size * 0.46),
            QPointF(size * 0.50, size * 0.62),
            QPointF(size * 0.66, size * 0.46),
        ]
    )
    painter.drawLine(QPointF(size * 0.32, size * 0.76), QPointF(size * 0.68, size * 0.76))
    painter.end()
    return QIcon(pixmap)
