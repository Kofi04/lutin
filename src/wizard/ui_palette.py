"""The command palette: one field, everything behind it.

Replaces the launcher menu on `Ctrl+Alt+Space`. It searches actions, launcher
entries, notes and clipboard history together, because the whole point is not
having to remember which menu a thing lives in.

Entirely keyboard-driven: type to filter, arrows to move, Enter to run, Escape
to leave. The mouse works too, but nothing requires it.

Sources are pushed in by the app rather than pulled by the palette, so this
file knows nothing about Storage, the config or Claude — which is what keeps it
testable and what stops it from becoming a second copy of the app's wiring.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .fuzzy import rank

#: Shown to the right of each row, so a result's origin is obvious.
KIND_LABELS = {
    "action": "Action",
    "launcher": "Lancer",
    "note": "Note",
    "clip": "Presse-papiers",
    "conversation": "Discussion",
}

_MAX_RESULTS = 40


@dataclass
class Command:
    """One thing the palette can do."""

    title: str
    #: "action", "launcher", "note", "clip", "conversation".
    kind: str = "action"
    subtitle: str = ""
    run: Callable[[], None] | None = None
    #: Free-form extra text folded into the search, never displayed.
    keywords: str = ""
    #: Sort hint for the empty query: lower comes first.
    order: int = 0
    payload: object = None

    def haystack(self) -> str:
        return " ".join(
            part for part in (self.title, self.subtitle, self.keywords) if part
        )


@dataclass
class Source:
    """A group of commands, rebuilt each time the palette opens."""

    name: str
    provide: Callable[[], list[Command]]
    commands: list[Command] = field(default_factory=list)


class CommandPalette(QDialog):
    """Search everything, run one thing."""

    #: Emitted with the chosen command, once the palette has closed.
    chosen = Signal(object)
    #: (source name, message) when a source raised instead of returning.
    source_failed = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setObjectName("panel")
        self.setModal(True)
        self.resize(QSize(640, 440))

        self._sources: list[Source] = []
        self._results: list[Command] = []

        self._search = QLineEdit(self)
        self._search.setObjectName("search")
        self._search.setPlaceholderText(
            "Chercher une action, un lanceur, une note, un presse-papiers…"
        )
        self._search.textChanged.connect(self._refilter)
        # The list has focus semantics but not focus: arrows must work while
        # typing, so the field keeps focus and forwards them.
        self._search.installEventFilter(self)

        self._list = QListWidget(self)
        self._list.setUniformItemSizes(True)
        self._list.itemActivated.connect(lambda _item: self._accept_current())
        self._list.itemClicked.connect(lambda _item: self._accept_current())

        self._empty = QLabel("Aucun résultat", self, objectName="hint")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.hide()

        hint = QLabel("↑↓ naviguer · Entrée valider · Échap fermer", self)
        hint.setObjectName("faint")
        hint.setAlignment(Qt.AlignmentFlag.AlignRight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)
        layout.addWidget(self._search)
        layout.addWidget(self._list, 1)
        layout.addWidget(self._empty)
        layout.addWidget(hint)

    # -- sources ----------------------------------------------------------

    def add_source(self, name: str, provide: Callable[[], list[Command]]) -> None:
        """Register a group of commands, rebuilt on every open."""
        self._sources.append(Source(name=name, provide=provide))

    def _gather(self) -> list[Command]:
        commands: list[Command] = []
        for source in self._sources:
            try:
                commands.extend(source.provide())
            except Exception as exc:
                # One broken source must not take the palette down with it: a
                # corrupt clipboard row should cost you that row, not the only
                # way you have of reaching everything else.
                #
                # But it must not vanish quietly either. Swallowing this hid a
                # source that was failing outright during development, and the
                # only symptom was a category of results that never appeared.
                self.source_failed.emit(source.name, str(exc)[:200])
        commands.sort(key=lambda command: command.order)
        return commands

    # -- opening ----------------------------------------------------------

    def open_palette(self) -> None:
        self._search.clear()
        self._all = self._gather()
        self._refilter("")
        self.show()
        _centre_on_active_screen(self)
        self.raise_()
        self.activateWindow()
        self._search.setFocus()

    # -- filtering --------------------------------------------------------

    def _refilter(self, text: str) -> None:
        self._results = rank(
            text, self._all, key=lambda command: command.haystack(), limit=_MAX_RESULTS
        )
        self._list.clear()
        for command in self._results:
            item = QListWidgetItem(self._label_for(command))
            item.setToolTip(command.subtitle or command.title)
            self._list.addItem(item)

        empty = not self._results
        self._list.setVisible(not empty)
        self._empty.setVisible(empty)
        if self._results:
            self._list.setCurrentRow(0)

    @staticmethod
    def _label_for(command: Command) -> str:
        kind = KIND_LABELS.get(command.kind, command.kind)
        if command.subtitle:
            return f"{command.title}\n{command.subtitle}   ·   {kind}"
        return f"{command.title}\n{kind}"

    # -- keyboard ---------------------------------------------------------

    def eventFilter(self, watched, event) -> bool:
        typing = (
            watched is self._search
            and isinstance(event, QKeyEvent)
            and event.type() == QKeyEvent.Type.KeyPress
        )
        if typing:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self._move(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._accept_current()
                return True
            if key == Qt.Key.Key_PageDown:
                self._move(8)
                return True
            if key == Qt.Key.Key_PageUp:
                self._move(-8)
                return True
        return super().eventFilter(watched, event)

    def _move(self, delta: int) -> None:
        count = self._list.count()
        if not count:
            return
        # Wrapping: pressing Up from the top goes to the bottom, which is what
        # every palette does and what fingers expect.
        row = (self._list.currentRow() + delta) % count
        self._list.setCurrentRow(row)

    def _accept_current(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._results):
            return
        command = self._results[row]
        # Close first: an action that opens another window should not have to
        # fight the palette for focus.
        self.hide()
        self.chosen.emit(command)
        if command.run is not None:
            command.run()

    def current_command(self) -> Command | None:
        row = self._list.currentRow()
        if 0 <= row < len(self._results):
            return self._results[row]
        return None


def _centre_on_active_screen(widget: QWidget) -> None:
    """Centre horizontally, sit a third of the way down: where the eye is."""
    from PySide6.QtGui import QCursor, QGuiApplication

    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    if screen is None:  # pragma: no cover - no display
        return
    bounds = screen.availableGeometry()
    geometry = widget.frameGeometry()
    geometry.moveCenter(bounds.center())
    geometry.moveTop(bounds.top() + bounds.height() // 5)
    widget.move(geometry.topLeft())
