"""The small windows the avatar opens: quick note, history, reminders.

These are real focusable dialogs (unlike the avatar itself), because you type
into them. They are kept deliberately keyboard-first: Esc closes, Enter is the
primary action, and the search box takes focus on open.
"""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .branding import APP_NAME
from .features.timers import TimerManager, parse_duration
from .storage import Record, Storage

STYLESHEET = """
QDialog { background: #161B22; }
QLabel { color: #C9D1D9; font-size: 12px; }
QLabel#hint { color: #6E7681; }
QLineEdit, QPlainTextEdit {
    background: #0D1117; color: #E6EDF3;
    border: 1px solid #30363D; border-radius: 6px; padding: 6px;
    selection-background-color: #2FA89B;
}
QLineEdit:focus, QPlainTextEdit:focus { border-color: #2FA89B; }
QPushButton {
    background: #21262D; color: #E6EDF3;
    border: 1px solid #30363D; border-radius: 6px; padding: 6px 12px;
}
QPushButton:hover { background: #30363D; }
QPushButton:default { background: #2FA89B; border-color: #2FA89B; color: #06231F; }
QListWidget {
    background: #0D1117; color: #E6EDF3;
    border: 1px solid #30363D; border-radius: 6px; outline: none;
}
QListWidget::item { padding: 6px 8px; border-bottom: 1px solid #1B2028; }
QListWidget::item:selected { background: #1F6F68; }
QTabBar::tab {
    background: transparent; color: #8B949E; padding: 6px 14px; border: none;
}
QTabBar::tab:selected { color: #E6EDF3; border-bottom: 2px solid #2FA89B; }
QTabWidget::pane { border: none; }
"""


def _centre_on_cursor(widget: QWidget) -> None:
    """Open near the mouse, but always fully on screen."""
    where = QCursor.pos()
    screen = QGuiApplication.screenAt(where) or QGuiApplication.primaryScreen()
    if screen is None:  # pragma: no cover - no display
        return
    bounds = screen.availableGeometry()
    geometry = widget.frameGeometry()
    geometry.moveCenter(where)
    geometry.moveLeft(
        max(bounds.left(), min(geometry.left(), bounds.right() - geometry.width()))
    )
    geometry.moveTop(
        max(bounds.top(), min(geometry.top(), bounds.bottom() - geometry.height()))
    )
    widget.move(geometry.topLeft())


def _preview(body: str, limit: int = 110) -> str:
    """One-line preview of a possibly multi-line entry."""
    single = " ".join(body.split())
    return single if len(single) <= limit else single[: limit - 1] + "…"


def _relative_time(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    seconds = (datetime.now(UTC) - moment).total_seconds()
    if seconds < 60:
        return "à l'instant"
    if seconds < 3600:
        return f"il y a {seconds // 60:.0f} min"
    if seconds < 86400:
        return f"il y a {seconds // 3600:.0f} h"
    return f"il y a {seconds // 86400:.0f} j"


class QuickNoteDialog(QDialog):
    """A tiny capture box: type, Ctrl+Enter, gone."""

    def __init__(self, storage: Storage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._storage = storage
        self.setWindowTitle("Note rapide")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setStyleSheet(STYLESHEET)
        self.setMinimumWidth(420)

        self._editor = QPlainTextEdit(self)
        self._editor.setPlaceholderText("Qu'est-ce que vous voulez retenir ?")
        self._editor.setFixedHeight(96)

        save = QPushButton("Enregistrer", self)
        save.setDefault(True)
        save.clicked.connect(self.accept)
        cancel = QPushButton("Annuler", self)
        cancel.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addWidget(
            QLabel("Ctrl+Entrée pour enregistrer", self, objectName="hint")
        )
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        layout = QVBoxLayout(self)
        layout.addWidget(self._editor)
        layout.addLayout(buttons)

        QShortcut(QKeySequence("Ctrl+Return"), self, self.accept)
        QShortcut(QKeySequence("Ctrl+Enter"), self, self.accept)

    def accept(self) -> None:
        body = self._editor.toPlainText().strip()
        if not body:
            self.reject()
            return
        self._storage.add_note(body)
        super().accept()

    def open_near_cursor(self) -> None:
        self.show()
        _centre_on_cursor(self)
        self.raise_()
        self.activateWindow()
        self._editor.setFocus()


class HistoryPanel(QDialog):
    """Searchable clipboard history and notes, side by side in two tabs."""

    CLIPBOARD_TAB = 0
    NOTES_TAB = 1

    copy_requested = Signal(str)

    def __init__(self, storage: Storage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._storage = storage
        self.setWindowTitle(APP_NAME)
        self.setStyleSheet(STYLESHEET)
        self.resize(QSize(520, 420))

        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Rechercher…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self.refresh)

        self._clips = self._make_list()
        self._notes = self._make_list()

        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._clips, "Presse-papiers")
        self._tabs.addTab(self._notes, "Notes")
        self._tabs.currentChanged.connect(lambda _: self.refresh())

        self._status = QLabel("", self, objectName="hint")

        delete = QPushButton("Supprimer", self)
        delete.clicked.connect(self._delete_selected)
        copy = QPushButton("Copier", self)
        copy.setDefault(True)
        copy.clicked.connect(self._copy_selected)

        actions = QHBoxLayout()
        actions.addWidget(self._status)
        actions.addStretch(1)
        actions.addWidget(delete)
        actions.addWidget(copy)

        layout = QVBoxLayout(self)
        layout.addWidget(self._search)
        layout.addWidget(self._tabs)
        layout.addLayout(actions)

        QShortcut(QKeySequence("Ctrl+F"), self, self._search.setFocus)

    def _make_list(self) -> QListWidget:
        widget = QListWidget(self)
        widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        widget.setAlternatingRowColors(False)
        widget.itemActivated.connect(lambda _: self._copy_selected())
        # Scoped to the list, not the window: a window-wide Delete shortcut
        # would swallow the Delete key while you are editing the search box.
        shortcut = QShortcut(QKeySequence("Delete"), widget, self._delete_selected)
        shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        return widget

    def open_at(self, tab: int) -> None:
        self._tabs.setCurrentIndex(tab)
        self.refresh()
        self.show()
        _centre_on_cursor(self)
        self.raise_()
        self.activateWindow()
        self._search.setFocus()
        self._search.selectAll()

    def refresh(self) -> None:
        term = self._search.text().strip() or None
        self._fill(self._clips, self._storage.list_clips(limit=200, search=term))
        self._fill(self._notes, self._storage.list_notes(limit=200, search=term))
        current = self._current_list()
        count = current.count()
        self._status.setText(f"{count} entrée{'s' if count > 1 else ''}")

    def _fill(self, widget: QListWidget, records: list[Record]) -> None:
        # Keep the selected row across refreshes so typing in the search box
        # does not yank the selection out from under the keyboard.
        selected_id = None
        current = widget.currentItem()
        if current is not None:
            selected_id = current.data(Qt.ItemDataRole.UserRole)

        widget.clear()
        for record in records:
            item = QListWidgetItem(
                f"{_preview(record.body)}\n{_relative_time(record.created_at)}"
            )
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, record.body)
            item.setToolTip(record.body[:2000])
            widget.addItem(item)
            if record.id == selected_id:
                widget.setCurrentItem(item)

        if widget.currentItem() is None and widget.count():
            widget.setCurrentRow(0)

    def _current_list(self) -> QListWidget:
        on_clipboard = self._tabs.currentIndex() == self.CLIPBOARD_TAB
        return self._clips if on_clipboard else self._notes

    def _selected_body(self) -> str | None:
        item = self._current_list().currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole + 1)

    def _copy_selected(self) -> None:
        body = self._selected_body()
        if body is not None:
            self.copy_requested.emit(body)
            self._status.setText("Copié")

    def _delete_selected(self) -> None:
        item = self._current_list().currentItem()
        if item is None:
            return
        record_id = item.data(Qt.ItemDataRole.UserRole)
        if self._tabs.currentIndex() == self.CLIPBOARD_TAB:
            self._storage.delete_clip(record_id)
        else:
            self._storage.delete_note(record_id)
        self.refresh()


class ReminderDialog(QDialog):
    """Set a countdown: presets for the common cases, free text for the rest."""

    PRESETS = (("5 min", 300), ("15 min", 900), ("Pomodoro 25 min", 1500), ("1 h", 3600))

    def __init__(self, timers: TimerManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._timers = timers
        self.setWindowTitle("Me rappeler")
        self.setStyleSheet(STYLESHEET)
        self.setMinimumWidth(380)

        self._label = QLineEdit(self)
        self._label.setPlaceholderText("À quel sujet ? (facultatif)")

        self._duration = QLineEdit(self)
        self._duration.setPlaceholderText("25  ·  25m  ·  1h30  ·  90s")
        self._duration.returnPressed.connect(self.accept)

        presets = QHBoxLayout()
        for text, seconds in self.PRESETS:
            button = QPushButton(text, self)
            button.clicked.connect(lambda _=False, s=seconds: self._start(s))
            presets.addWidget(button)

        start = QPushButton("Démarrer", self)
        start.setDefault(True)
        start.clicked.connect(self.accept)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(start)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Durée", self))
        layout.addWidget(self._duration)
        layout.addWidget(QLabel("Intitulé", self))
        layout.addWidget(self._label)
        layout.addLayout(presets)
        layout.addLayout(row)

    def accept(self) -> None:
        try:
            seconds = parse_duration(self._duration.text())
        except ValueError:
            QMessageBox.warning(
                self,
                "Durée non reconnue",
                "Essayez par exemple 25, 25m, 1h30 ou 90s.",
            )
            return
        self._start(seconds)

    def _start(self, seconds: int) -> None:
        self._timers.add(self._label.text(), seconds)
        super().accept()

    def open_near_cursor(self) -> None:
        self._duration.clear()
        self._label.clear()
        self.show()
        _centre_on_cursor(self)
        self.raise_()
        self.activateWindow()
        self._duration.setFocus()
