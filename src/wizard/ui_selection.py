"""The small window that shows what Claude made of a selection.

It opens as soon as an action is picked, saying Claude is working, because a
one-shot job starts its own Claude Code process and takes a few seconds;
nothing on screen for that long reads as "it did not work".

For transformations (translate, rephrase, fix) the default is to replace the
selection; for summaries and explanations it is to copy. Either way the choice
is shown before anything touches the other application.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .assistant.selection import SelectionAction


class SelectionResult(QDialog):
    """Shows the result; replace the selection, copy it, or drop it."""

    replace_requested = Signal(str)
    copy_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(520, 320)

        self._title = QLabel("", self)
        self._title.setObjectName("title")
        self._status = QLabel("", self)
        self._status.setObjectName("hint")
        # Editable: a one-word fix before pasting is quicker here than after.
        self._text = QPlainTextEdit(self)

        self._replace = QPushButton("Remplacer la sélection", self)
        self._replace.clicked.connect(
            lambda: self._done(self.replace_requested, self._text.toPlainText())
        )
        self._copy = QPushButton("Copier", self)
        self._copy.clicked.connect(
            lambda: self._done(self.copy_requested, self._text.toPlainText())
        )
        close = QPushButton("Fermer", self)
        close.setObjectName("quiet")
        close.clicked.connect(self.hide)

        buttons = QHBoxLayout()
        buttons.addWidget(self._status, 1)
        buttons.addWidget(close)
        buttons.addWidget(self._copy)
        buttons.addWidget(self._replace)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._text, 1)
        layout.addLayout(buttons)

        QShortcut(QKeySequence("Ctrl+Return"), self, self._default_action)

    def start(self, chosen: SelectionAction, original: str) -> None:
        self._action = chosen
        self.setWindowTitle(chosen.label)
        self._title.setText(chosen.label)
        self._text.setPlainText("")
        self._text.setPlaceholderText(f"« {_preview(original)} »")
        self._text.setReadOnly(True)
        self._set_status("Claude travaille…")
        self._replace.setEnabled(False)
        self._copy.setEnabled(False)
        self._replace.setVisible(chosen.replaces)
        self.show()
        _near_cursor(self)
        self.raise_()
        self.activateWindow()

    def show_result(self, text: str) -> None:
        self._text.setReadOnly(False)
        self._text.setPlainText(text)
        self._set_status("")
        self._replace.setEnabled(True)
        self._copy.setEnabled(True)
        default = self._replace if self._action.replaces else self._copy
        default.setDefault(True)
        default.setFocus()

    def show_error(self, message: str) -> None:
        self._text.setReadOnly(True)
        self._text.setPlainText("")
        self._text.setPlaceholderText("")
        self._set_status(message, danger=True)

    def _set_status(self, text: str, danger: bool = False) -> None:
        # The object name drives the colour; it has to be reset for the
        # next job, or one error leaves every later status red.
        self._status.setObjectName("danger" if danger else "hint")
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
        self._status.setText(text)

    def _default_action(self) -> None:
        if self._replace.isEnabled() and self._action.replaces:
            self._replace.click()
        elif self._copy.isEnabled():
            self._copy.click()

    def _done(self, signal, text: str) -> None:
        self.hide()
        signal.emit(text)


def _preview(text: str, limit: int = 120) -> str:
    single = " ".join(text.split())
    return single if len(single) <= limit else single[: limit - 1] + "…"


def _near_cursor(widget: QWidget) -> None:
    where = QCursor.pos()
    screen = QGuiApplication.screenAt(where) or QGuiApplication.primaryScreen()
    if screen is None:  # pragma: no cover
        return
    area = screen.availableGeometry()
    x = min(
        max(area.left(), where.x() - widget.width() // 2), area.right() - widget.width()
    )
    y = min(max(area.top(), where.y() + 20), area.bottom() - widget.height())
    widget.move(x, y)
