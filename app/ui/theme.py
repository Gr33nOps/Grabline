"""In-app light/dark theme. "system" leaves Qt's default look untouched;
"light" and "dark" apply an explicit Fusion palette so the choice is honored
the same way on every platform."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEMES = ("system", "light", "dark")

_DARK = {
    "window": "#2b2b2b",
    "base": "#232323",
    "alt": "#2f2f2f",
    "text": "#e6e6e6",
    "button": "#3a3a3a",
    "highlight": "#2563eb",
    "disabled": "#6b6b6b",
}
_LIGHT = {
    "window": "#f2f2f2",
    "base": "#ffffff",
    "alt": "#e9e9e9",
    "text": "#1e1e1e",
    "button": "#e6e6e6",
    "highlight": "#2563eb",
    "disabled": "#a0a0a0",
}


def _palette(colors: dict[str, str]) -> QPalette:
    p = QPalette()
    window, base, alt = QColor(colors["window"]), QColor(colors["base"]), QColor(colors["alt"])
    text, button = QColor(colors["text"]), QColor(colors["button"])
    highlight, disabled = QColor(colors["highlight"]), QColor(colors["disabled"])
    p.setColor(QPalette.ColorRole.Window, window)
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, base)
    p.setColor(QPalette.ColorRole.AlternateBase, alt)
    p.setColor(QPalette.ColorRole.ToolTipBase, base)
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.Button, button)
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.Highlight, highlight)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.Link, highlight)
    group = QPalette.ColorGroup.Disabled
    p.setColor(group, QPalette.ColorRole.Text, disabled)
    p.setColor(group, QPalette.ColorRole.ButtonText, disabled)
    p.setColor(group, QPalette.ColorRole.WindowText, disabled)
    return p


#: Captured once so switching back to "system" restores the real defaults.
_default_style: str | None = None
_default_palette: QPalette | None = None


def remember_default(app: QApplication) -> None:
    """Snapshot the platform default look before any theme is applied."""
    global _default_style, _default_palette
    style = app.style()
    _default_style = style.objectName() if style is not None else None
    _default_palette = QPalette(app.palette())


def apply_theme(app: QApplication, mode: str) -> None:
    """Apply "system", "light", or "dark" to the running application."""
    if mode == "system" or mode not in THEMES:
        if _default_style:
            app.setStyle(_default_style)
        if _default_palette is not None:
            app.setPalette(_default_palette)
        return
    app.setStyle("Fusion")
    app.setPalette(_palette(_DARK if mode == "dark" else _LIGHT))
