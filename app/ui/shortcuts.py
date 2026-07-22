"""Keyboard shortcuts: the registry, and the manager that installs them.

Every action reachable by key lives in :data:`DEFAULTS` as one :class:`Shortcut`.
The manager reads any per-user overrides (``Settings.shortcuts``), resolves the
effective binding for each id, and creates the ``QShortcut`` objects wired to the
handlers the main window supplies.

Two scopes keep bare keys (Space, Delete, Return) from firing while the user is
typing: an ``"app"`` shortcut is application-wide; a ``"list"`` shortcut fires
only when the download table (or a child) has focus.

Bindings are stored as portable ``QKeySequence`` strings ("Ctrl+N"). Qt maps
"Ctrl" to the Command key on macOS, so the one table below is correct on every
platform without a per-OS variant. A blank binding ("") means "unbound".
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget

#: The scope value for a shortcut that fires only when the download list has focus.
LIST_SCOPE = "list"
#: The scope value for an application-wide shortcut.
APP_SCOPE = "app"


@dataclass(frozen=True)
class Shortcut:
    """One bindable action.

    ``id`` is the stable key used everywhere (overrides map, handler lookup);
    ``label`` is what the user reads; ``category`` groups it in the UIs;
    ``default`` is the out-of-the-box binding; ``scope`` is ``"app"`` or
    ``"list"``.
    """

    id: str
    label: str
    category: str
    default: str
    scope: str = APP_SCOPE


#: Category display order for the cheat-sheet and the settings table.
CATEGORIES = ("General", "Navigation", "Filters", "Downloads", "View")

DEFAULTS: tuple[Shortcut, ...] = (
    # -- General ---------------------------------------------------------------
    Shortcut("download.add", "New download", "General", "Ctrl+N"),
    Shortcut("download.batch", "New batch download", "General", "Ctrl+Shift+N"),
    Shortcut("download.paste", "Paste URL and download", "General", "Ctrl+V"),
    Shortcut("torrent.add", "Add torrent file", "General", "Ctrl+O"),
    Shortcut("import.links", "Import links", "General", "Ctrl+L"),
    Shortcut("list.export", "Export list", "General", "Ctrl+E"),
    Shortcut("site.grab", "Grab site", "General", "Ctrl+G"),
    Shortcut("url.inspect", "Inspect URL", "General", "Ctrl+Shift+I"),
    Shortcut("folder.open", "Open downloads folder", "General", "Ctrl+Shift+O"),
    Shortcut("search.focus", "Search downloads", "General", "Ctrl+F"),
    Shortcut("settings.open", "Settings", "General", "Ctrl+,"),
    Shortcut("app.quit", "Quit GrabLine", "General", "Ctrl+Q"),
    Shortcut("view.refresh", "Refresh", "General", "F5"),
    Shortcut("help.shortcuts", "Keyboard shortcuts", "General", "F1"),
    # -- Navigation (the four real sidebar pages) ------------------------------
    Shortcut("nav.downloads", "Go to Downloads", "Navigation", "Ctrl+1"),
    Shortcut("nav.dashboard", "Go to Dashboard", "Navigation", "Ctrl+2"),
    Shortcut("nav.queue", "Go to Queue manager", "Navigation", "Ctrl+3"),
    Shortcut("nav.settings", "Go to Settings", "Navigation", "Ctrl+4"),
    Shortcut("nav.next", "Next page", "Navigation", "Ctrl+Tab"),
    Shortcut("nav.prev", "Previous page", "Navigation", "Ctrl+Shift+Tab"),
    # -- Filters ---------------------------------------------------------------
    Shortcut("filter.all", "Show all", "Filters", "Alt+1"),
    Shortcut("filter.active", "Show active", "Filters", "Alt+2"),
    Shortcut("filter.completed", "Show completed", "Filters", "Alt+3"),
    Shortcut("filter.failed", "Show failed", "Filters", "Alt+4"),
    # -- Downloads: operate on the selection, so table-focus scope -------------
    Shortcut("dl.toggle", "Pause / resume", "Downloads", "Space", scope=LIST_SCOPE),
    Shortcut("dl.pause", "Pause selected", "Downloads", "Ctrl+P", scope=LIST_SCOPE),
    Shortcut("dl.resume", "Resume selected", "Downloads", "Ctrl+R", scope=LIST_SCOPE),
    Shortcut("dl.remove", "Remove from list", "Downloads", "Del", scope=LIST_SCOPE),
    Shortcut("dl.openfile", "Open file", "Downloads", "Return", scope=LIST_SCOPE),
    Shortcut(
        "dl.openfolder", "Open containing folder", "Downloads", "Ctrl+Return", scope=LIST_SCOPE
    ),
    Shortcut("dl.redownload", "Download again", "Downloads", "Ctrl+D", scope=LIST_SCOPE),
    Shortcut("dl.copyurl", "Copy URL", "Downloads", "Ctrl+C", scope=LIST_SCOPE),
    Shortcut("dl.copyhash", "Copy SHA-256 checksum", "Downloads", "Ctrl+Shift+C", scope=LIST_SCOPE),
    # -- Downloads: all-jobs actions, so application-wide -----------------------
    Shortcut("dl.pauseall", "Pause all", "Downloads", "Ctrl+Shift+P"),
    Shortcut("dl.resumeall", "Resume all", "Downloads", "Ctrl+Shift+R"),
    Shortcut("dl.clear", "Clear completed", "Downloads", "Ctrl+Backspace"),
    # -- View ------------------------------------------------------------------
    Shortcut("view.theme", "Toggle light / dark theme", "View", "Ctrl+Shift+L"),
)

#: id -> Shortcut, for quick lookup.
BY_ID: dict[str, Shortcut] = {s.id: s for s in DEFAULTS}


def normalize(sequence: str) -> str:
    """Canonicalize a binding string so equal keys compare equal (and blanks
    collapse to ""). Round-trips through ``QKeySequence`` in portable form -
    "ctrl+n" and "Ctrl+N" both become "Ctrl+N"; junk becomes "".
    """
    if not sequence:
        return ""
    key = QKeySequence(sequence)
    if key.isEmpty():
        return ""
    return key.toString(QKeySequence.SequenceFormat.PortableText)


def by_category() -> list[tuple[str, list[Shortcut]]]:
    """The registry grouped for display: ``[(category, [Shortcut, ...]), ...]``
    in :data:`CATEGORIES` order, skipping empty groups."""
    groups: dict[str, list[Shortcut]] = {}
    for shortcut in DEFAULTS:
        groups.setdefault(shortcut.category, []).append(shortcut)
    ordered = [(name, groups[name]) for name in CATEGORIES if name in groups]
    # Any category not in CATEGORIES still shows, after the known ones.
    for name, items in groups.items():
        if name not in CATEGORIES:
            ordered.append((name, items))
    return ordered


def conflicts(bindings: Mapping[str, str]) -> dict[str, list[str]]:
    """Given ``{id: sequence}``, return ``{sequence: [id, id, ...]}`` for every
    key bound to more than one action.

    Scope is deliberately ignored: an ``"app"`` binding is always active, so it
    would still collide with a ``"list"`` binding on the same key whenever the
    table has focus. Any shared key is a real conflict.
    """
    by_sequence: dict[str, list[str]] = {}
    for shortcut_id, sequence in bindings.items():
        canonical = normalize(sequence)
        if canonical:
            by_sequence.setdefault(canonical, []).append(shortcut_id)
    return {sequence: ids for sequence, ids in by_sequence.items() if len(ids) > 1}


class ShortcutManager:
    """Owns the live ``QShortcut`` objects and rebinds them without a restart."""

    def __init__(
        self,
        window: QWidget,
        settings: object,
        actions: Mapping[str, Callable[[], None]],
        list_widget: QWidget | None,
    ) -> None:
        self._window = window
        self._settings = settings
        self._actions = dict(actions)
        self._list_widget = list_widget
        self._live: list[QShortcut] = []

    @property
    def action_ids(self) -> set[str]:
        """The ids the window supplied a handler for."""
        return set(self._actions)

    def effective(self) -> dict[str, str]:
        """Merged defaults + user overrides, canonicalized: ``{id: sequence}``.
        A stored "" means the user unbound that action."""
        overrides = getattr(self._settings, "shortcuts", {}) or {}
        result: dict[str, str] = {}
        for shortcut in DEFAULTS:
            result[shortcut.id] = normalize(overrides.get(shortcut.id, shortcut.default))
        return result

    def install(self) -> None:
        """Create (or recreate) every QShortcut from the effective bindings."""
        self._clear()
        effective = self.effective()
        for shortcut in DEFAULTS:
            handler = self._actions.get(shortcut.id)
            sequence = effective.get(shortcut.id, "")
            if handler is None or not sequence:
                continue
            parent, context = self._target(shortcut.scope)
            live = QShortcut(QKeySequence(sequence), parent)
            live.setContext(context)
            live.activated.connect(handler)
            self._live.append(live)

    def reload(self) -> None:
        """Re-read the settings and reinstall - called after a rebind."""
        self.install()

    def _clear(self) -> None:
        # Disable first so a stale shortcut can't fire between now and the event
        # loop actually deleting it; deleteLater drops it regardless of parent.
        for live in self._live:
            live.setEnabled(False)
            live.deleteLater()
        self._live.clear()

    def _target(self, scope: str) -> tuple[QWidget, Qt.ShortcutContext]:
        if scope == LIST_SCOPE and self._list_widget is not None:
            return self._list_widget, Qt.ShortcutContext.WidgetWithChildrenShortcut
        return self._window, Qt.ShortcutContext.ApplicationShortcut
