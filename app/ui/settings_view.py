"""The embedded Settings page: a left nav (search + tab list) and a scrolling
content pane on the right, matching the redesign mockups.

It reuses the existing SettingsDialog for all the field building and the save
logic - the dialog is constructed but never shown; its tab pages are lifted
out and re-hosted here, and Save calls the dialog's ``apply()``.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.settings import Settings
from app.ui import components, design, theme
from app.ui.icons import svg_icon
from app.ui.settings_dialog import SettingsDialog


class SettingsView(QWidget):
    def __init__(
        self,
        settings: Settings,
        on_applied: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_applied = on_applied
        # Build the dialog (never shown) to own the fields + apply() logic.
        self._dialog = SettingsDialog(settings)
        p = theme.current()

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        # ---- left nav -------------------------------------------------------
        nav = QFrame()
        nav.setFixedWidth(176)
        nav.setStyleSheet(f"background: {p.surface2}; border-right: 1px solid {p.border};")
        nlay = QVBoxLayout(nav)
        nlay.setContentsMargins(10, 12, 10, 12)
        nlay.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search settings…")
        self._search.addAction(
            svg_icon("search", p.text3), QLineEdit.ActionPosition.LeadingPosition
        )
        self._search.textChanged.connect(self._filter)
        nlay.addWidget(self._search)

        self._list = QListWidget()
        self._list.setStyleSheet(
            f"QListWidget {{ border: none; background: transparent; }}"
            f" QListWidget::item {{ padding: 7px 10px; border-radius: {design.RADIUS['sm']}px;"
            f" color: {p.text2}; }}"
            f" QListWidget::item:selected {{ background: {p.accent_dim}; color: {p.accent};"
            f" border-left: 2px solid {p.accent}; }}"
            f" QListWidget::item:hover {{ background: {p.row_hover}; }}"
        )
        self._list.currentRowChanged.connect(self._on_nav)
        nlay.addWidget(self._list, 1)
        row.addWidget(nav)

        # ---- content --------------------------------------------------------
        content = QWidget()
        clay = QVBoxLayout(content)
        clay.setContentsMargins(0, 0, 0, 0)
        clay.setSpacing(0)

        self._title = QLabel("")
        self._title.setStyleSheet(
            f"font-size: {design.FONT['h1']}pt; font-weight: 600; padding: 18px 24px 8px;"
        )
        clay.addWidget(self._title)

        self._stack = QStackedWidget()
        # Lift each tab page out of the dialog's QTabWidget into our stack,
        # wrapped in a scroll area so long tabs scroll.
        tabs = self._dialog.tabs
        self._titles: list[str] = []
        pages = [(tabs.tabText(i).replace("&&", "&"), tabs.widget(i)) for i in range(tabs.count())]
        for title, page in pages:
            if page is None:
                continue
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            holder = QWidget()
            hl = QVBoxLayout(holder)
            hl.setContentsMargins(24, 8, 24, 20)
            hl.addWidget(page)
            hl.addStretch(1)
            scroll.setWidget(holder)
            self._stack.addWidget(scroll)
            self._titles.append(title)
            item = QListWidgetItem(title)
            self._list.addItem(item)
        clay.addWidget(self._stack, 1)

        footer = QFrame()
        footer.setStyleSheet(f"border-top: 1px solid {p.border};")
        flay = QHBoxLayout(footer)
        flay.setContentsMargins(24, 10, 24, 10)
        flay.addStretch(1)
        self._saved = QLabel("")
        self._saved.setStyleSheet(f"color: {p.ok}; font-size: {design.FONT['small']}pt;")
        flay.addWidget(self._saved)
        save = components.accent_button("Save changes")
        save.clicked.connect(self._save)
        flay.addWidget(save)
        clay.addWidget(footer)

        row.addWidget(content, 1)
        self._list.setCurrentRow(0)

    def _on_nav(self, index: int) -> None:
        if 0 <= index < self._stack.count():
            self._stack.setCurrentIndex(index)
            self._title.setText(self._titles[index])
            self._saved.setText("")

    def _filter(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def _save(self) -> None:
        if self._dialog.apply():
            self._saved.setText("✓ Saved")
            self._on_applied()
