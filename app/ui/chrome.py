"""Custom window chrome: the frameless title bar that replaces the native one
on the main window and on Grabline's dialogs.

``TitleBar`` is the bar itself (logo, title, min/max/close, drag-to-move,
double-click-to-maximize). ``Dialog`` is a drop-in QDialog base class - the
first ``exec``/``show`` wraps the dialog's existing layout under a close-only
title bar, so dialog code needs no other change. ``EdgeResizer`` restores
edge-drag resizing that the frameless hint takes away.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui import design, theme
from app.ui.icons import svg_icon

_BAR_HEIGHT = 38
_RESIZE_MARGIN = 6


class _CaptionButton(QPushButton):
    """A flat 34px window-control button (minimize / maximize / close)."""

    def __init__(self, icon_name: str, tooltip: str, *, danger: bool = False) -> None:
        super().__init__()
        self._icon_name = icon_name
        self._danger = danger
        self.setFixedSize(40, _BAR_HEIGHT - 8)
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retint()

    def set_icon_name(self, name: str) -> None:
        self._icon_name = name
        self.retint()

    def retint(self) -> None:
        p = theme.current()
        self.setIcon(svg_icon(self._icon_name, p.text2))
        hover = p.warn if self._danger else p.row_hover
        hover_fg = "#ffffff" if self._danger else p.text
        self.setStyleSheet(
            f"QPushButton {{ border: none; border-radius: {design.RADIUS['sm']}px;"
            f" background: transparent; }}"
            f" QPushButton:hover {{ background: {hover}; color: {hover_fg}; }}"
        )


class TitleBar(QFrame):
    """The custom caption bar: drag to move, double-click to maximize, and
    the standard window controls. ``dialog=True`` shows only Close."""

    def __init__(self, window: QWidget, *, dialog: bool = False) -> None:
        super().__init__()
        self._window = window
        self.setObjectName("TitleBar")
        self.setFixedHeight(_BAR_HEIGHT)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 6, 0)
        lay.setSpacing(8)

        from app.ui import components

        lay.addWidget(components.app_logo(20))
        self._title = components.role_label(window.windowTitle() or "Grabline", "strong")
        window.windowTitleChanged.connect(self._title.setText)
        lay.addWidget(self._title)
        lay.addStretch(1)

        self._buttons: list[_CaptionButton] = []
        self._max_btn: _CaptionButton | None = None
        if not dialog:
            mini = _CaptionButton("minimize", "Minimize")
            mini.clicked.connect(window.showMinimized)
            self._max_btn = _CaptionButton("maximize", "Maximize")
            self._max_btn.clicked.connect(self._toggle_maximized)
            self._buttons += [mini, self._max_btn]
        close = _CaptionButton("cancel", "Close", danger=True)
        close.clicked.connect(window.close)
        self._buttons.append(close)
        for btn in self._buttons:
            lay.addWidget(btn)

    def retint(self) -> None:
        for btn in self._buttons:
            btn.retint()

    def _toggle_maximized(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
            if self._max_btn:
                self._max_btn.set_icon_name("maximize")
                self._max_btn.setToolTip("Maximize")
        else:
            self._window.showMaximized()
            if self._max_btn:
                self._max_btn.set_icon_name("restore")
                self._max_btn.setToolTip("Restore")

    def mousePressEvent(self, event: object) -> None:
        ev = event
        if ev.button() == Qt.MouseButton.LeftButton:  # type: ignore[attr-defined]
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return
        super().mousePressEvent(ev)  # type: ignore[arg-type]

    def mouseDoubleClickEvent(self, event: object) -> None:
        if self._max_btn is not None:
            self._toggle_maximized()
        super().mouseDoubleClickEvent(event)  # type: ignore[arg-type]


class EdgeResizer(QObject):
    """Restores edge-drag resizing on a frameless top-level window."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        window.setMouseTracking(True)
        window.installEventFilter(self)

    def _edges(self, pos: QPoint) -> Qt.Edge:
        rect = self._window.rect()
        edges = Qt.Edge(0)
        if pos.x() <= _RESIZE_MARGIN:
            edges |= Qt.Edge.LeftEdge
        if pos.x() >= rect.width() - _RESIZE_MARGIN:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= _RESIZE_MARGIN:
            edges |= Qt.Edge.TopEdge
        if pos.y() >= rect.height() - _RESIZE_MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._window and not self._window.isMaximized():
            if event.type() == QEvent.Type.MouseMove:
                edges = self._edges(event.position().toPoint())  # type: ignore[attr-defined]
                cursors = {
                    Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
                    Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
                    Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
                    Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
                    Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
                    Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
                    Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
                    Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
                }
                if edges in cursors:
                    self._window.setCursor(cursors[edges])
                else:
                    self._window.unsetCursor()
            elif event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:  # type: ignore[attr-defined]
                    edges = self._edges(event.position().toPoint())  # type: ignore[attr-defined]
                    if edges:
                        handle = self._window.windowHandle()
                        if handle is not None:
                            handle.startSystemResize(edges)
                            return True
        return super().eventFilter(obj, event)


def wrap_dialog(dialog: QDialog) -> None:
    """Give a dialog the custom chrome: frameless, with its existing layout
    re-hosted under a close-only TitleBar. Call before the first show."""
    dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    old = dialog.layout()
    outer = QVBoxLayout()
    outer.setContentsMargins(1, 1, 1, 1)  # room for the border to show
    outer.setSpacing(0)
    bar = TitleBar(dialog, dialog=True)
    outer.addWidget(bar)
    if old is not None:
        holder = QWidget()
        holder.setLayout(old)  # transfers the layout (and margins) intact
        outer.addWidget(holder, 1)
    dialog.setLayout(outer)
    p = theme.current()
    dialog.setStyleSheet(dialog.styleSheet() + f"\nQDialog {{ border: 1px solid {p.border}; }}")


class Dialog(QDialog):
    """QDialog with Grabline's chrome. Subclass instead of QDialog - the
    wrap happens lazily on first exec/show/open, after __init__ built the
    layout, so existing dialog code needs no other change."""

    _chromed = False

    def _apply_chrome(self) -> None:
        if not self._chromed:
            self._chromed = True
            wrap_dialog(self)

    def exec(self) -> int:
        self._apply_chrome()
        return super().exec()

    def show(self) -> None:
        self._apply_chrome()
        super().show()

    def open(self) -> None:
        self._apply_chrome()
        super().open()
