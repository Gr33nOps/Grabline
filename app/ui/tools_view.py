"""The embedded Tools page: a card per power feature, replacing the old
"More actions" overflow menu. Each card is a real button (icon, name, and a
one-line description), so the tools read as features instead of hiding in a
junk-drawer menu. The main window supplies the handlers; this module only
draws and dispatches.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui import components, design, theme
from app.ui.icons import svg_icon

#: key -> (icon, title, description). Keys match the handler mapping the
#: main window passes in; sections group the cards on the page.
_SECTIONS: tuple[tuple[str, tuple[tuple[str, str, str, str], ...]], ...] = (
    (
        "Tools",
        (
            (
                "grab_site",
                "globe",
                "Grab Site",
                "Scan a web page - optionally the pages it links to - and pick "
                "which of the files it finds to download.",
            ),
            (
                "inspect_url",
                "inspect",
                "Inspect URL",
                "See what a link really serves before downloading: server, size, "
                "type, resume support, and redirects.",
            ),
            (
                "search_torrents",
                "search",
                "Search Torrents",
                "Search your configured torrent site (Settings → Torrent) and "
                "open the results in your browser.",
            ),
            (
                "create_torrent",
                "torrent",
                "Create Torrent",
                "Package a file or folder into a .torrent with trackers, web "
                "seeds, and an optional private flag.",
            ),
            (
                "find_duplicates",
                "copy",
                "Find Duplicate Files",
                "Hash-compare your completed downloads and clean up the "
                "byte-identical extra copies.",
            ),
        ),
    ),
    (
        "Import & Export",
        (
            (
                "import_links",
                "add",
                "Import Links",
                "Paste or load a batch of URLs; everything queues at your "
                "default settings in one go.",
            ),
            (
                "import_list",
                "import",
                "Import List",
                "Restore a download list exported earlier - from a backup or another machine.",
            ),
            (
                "export_list",
                "export",
                "Export List",
                "Save the current download list to a JSON file you can back up "
                "or import elsewhere.",
            ),
        ),
    ),
)


class ToolCard(QPushButton):
    """A clickable card: icon chip on the left, name + one-line description
    on the right. A real button, so focus/Enter/Space work like one."""

    def __init__(
        self, icon_name: str, title: str, description: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)
        self._chip = QLabel()
        self._chip.setFixedSize(QSize(36, 36))
        self._chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._chip, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        title_lbl = components.role_label(title, "strong", size=design.FONT["h2"], bold=True)
        desc = components.role_label(description, "muted", size=design.FONT["small"])
        desc.setWordWrap(True)
        # Labels ignore mouse presses, so clicks fall through to the button.
        text.addWidget(title_lbl)
        text.addWidget(desc)
        text.addStretch(1)
        lay.addLayout(text, 1)
        self.retint()

    def retint(self) -> None:
        p = theme.current()
        self._chip.setPixmap(svg_icon(self._icon_name, p.accent).pixmap(20, 20))
        self._chip.setStyleSheet(
            f"QLabel {{ background: {p.accent_dim}; border-radius: {design.RADIUS['md']}px; }}"
        )
        self.setStyleSheet(
            f"QPushButton {{ background: {p.surface}; border: 1px solid {p.border};"
            f" border-radius: {design.RADIUS['lg']}px; text-align: left; }}"
            f" QPushButton:hover {{ background: {p.row_hover}; border-color: {p.accent}; }}"
            f" QPushButton:focus {{ border-color: {p.accent}; }}"
        )


class ToolsView(QWidget):
    """The Tools page. ``handlers`` maps the keys in ``_SECTIONS`` to the
    main-window actions each card launches."""

    def __init__(
        self, handlers: dict[str, Callable[[], None]], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._cards: list[ToolCard] = []

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

        heading = components.role_label("Tools", "strong", size=design.FONT["h1"], bold=True)
        root.addWidget(heading)
        intro = components.role_label("Everything beyond plain downloads lives here.", "muted")
        root.addWidget(intro)

        for section, cards in _SECTIONS:
            root.addSpacing(2)
            root.addWidget(components.SectionLabel(section))
            grid = QGridLayout()
            grid.setSpacing(10)
            for index, (key, icon_name, title, description) in enumerate(cards):
                card = ToolCard(icon_name, title, description)
                handler = handlers.get(key)
                if handler is not None:
                    card.clicked.connect(handler)
                self._cards.append(card)
                grid.addWidget(card, index // 2, index % 2)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            root.addLayout(grid)
        root.addStretch(1)

    def retint(self) -> None:
        for card in self._cards:
            card.retint()
