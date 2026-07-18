"""Custom window chrome for the frameless main window.

``TitleBar`` is the caption bar (logo, title, min/max/close, drag-to-move,
double-click-to-maximize). ``EdgeResizer`` restores edge/corner drag-resizing
that the frameless hint takes away. ``Dialog`` is a plain QDialog base that
keeps the native OS title bar - only the main window uses custom chrome.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QWidget,
)

from app.ui import design, theme
from app.ui.icons import svg_icon

_BAR_HEIGHT = 38
_RESIZE_MARGIN = 8


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
        lay.setContentsMargins(12, 0, 6, 0)
        lay.setSpacing(8)

        from app.ui import components

        # Every bar carries the mark next to its title - main window included.
        lay.addWidget(components.app_logo(18))
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


_RESIZE_CURSORS = {
    Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
    Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
    Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
    Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
    Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
    Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
    Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
    Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
}


class EdgeResizer(QWidget):
    """Restores edge- and corner-drag resizing on a frameless top-level window.

    A previous version filtered mouse events on the window itself, but the
    window's children cover every edge and either consume those events or -
    lacking mouse tracking - never generate them, so resizing worked only in
    stray gaps and the resize cursor could stick. This is a thin overlay
    instead: it covers the window but is masked to just the outer margin, so
    only that border is interactive (clicks in the center pass straight through
    to the content). Because the overlay owns its border region, it always sees
    its own move/press/leave events - resizing works over any child, and the
    cursor resets the moment the pointer leaves the border."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent;")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        window.installEventFilter(self)
        self._sync()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._window and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.WindowStateChange,
        ):
            self._sync()
        return super().eventFilter(obj, event)

    def _sync(self) -> None:
        """Match the window's size, and mask to a hollow border frame. Hidden
        while maximized/fullscreen, where there is nothing to resize."""
        if self._window.isMaximized() or self._window.isFullScreen():
            self.hide()
            return
        self.setGeometry(self._window.rect())
        rect = self.rect()
        margin = _RESIZE_MARGIN
        inner = rect.adjusted(margin, margin, -margin, -margin)
        self.setMask(QRegion(rect).subtracted(QRegion(inner)))
        self.show()
        self.raise_()

    def _edges(self, pos: QPoint) -> Qt.Edge:
        rect = self.rect()
        margin = _RESIZE_MARGIN
        edges = Qt.Edge(0)
        if pos.x() <= margin:
            edges |= Qt.Edge.LeftEdge
        if pos.x() >= rect.width() - margin:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= margin:
            edges |= Qt.Edge.TopEdge
        if pos.y() >= rect.height() - margin:
            edges |= Qt.Edge.BottomEdge
        return edges

    def mouseMoveEvent(self, event: object) -> None:
        edges = self._edges(event.position().toPoint())  # type: ignore[attr-defined]
        self.setCursor(_RESIZE_CURSORS.get(edges, Qt.CursorShape.ArrowCursor))

    def mousePressEvent(self, event: object) -> None:
        if event.button() == Qt.MouseButton.LeftButton:  # type: ignore[attr-defined]
            edges = self._edges(event.position().toPoint())  # type: ignore[attr-defined]
            handle = self._window.windowHandle()
            if edges and handle is not None:
                handle.startSystemResize(edges)

    def leaveEvent(self, event: object) -> None:
        # The pointer left the border (into the content or off the window):
        # drop the resize cursor so it never sticks.
        self.unsetCursor()
        super().leaveEvent(event)  # type: ignore[arg-type]


class Dialog(QDialog):
    """A plain QDialog that keeps the native OS title bar.

    Dialogs used to be wrapped in the same frameless custom bar as the main
    window, but the native bar is cleaner, already carries the app icon and
    the standard window controls, and is properly movable everywhere. Only the
    main window keeps custom chrome now. Subclasses need no change - this is a
    thin alias so the ``chrome.Dialog`` base can stay in place."""
