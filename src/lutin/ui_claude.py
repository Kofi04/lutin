"""The two panels Claude needs: asking a question, and approving an action.

Both are deliberately ignorant of the Agent SDK. They receive plain strings and
a small `ToolRequest` record, so the SDK's message shapes stay behind
`claude/session.py` and this file does not move when the SDK does.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .capture import Capture
from .ui import STYLESHEET, _centre_on_cursor

_PILL_HEIGHT = 44


@dataclass(frozen=True)
class ToolRequest:
    """One action Claude wants to take, described for a human."""

    tool: str  # "Bash", "Edit", ...
    detail: str  # the command, the file being edited...
    project: str = ""  # working directory name, when known

    def title(self) -> str:
        where = f" dans {self.project}" if self.project else ""
        return f"Claude veut utiliser {self.tool}{where}"


class _ContextPill(QFrame):
    """The little card showing what Claude is being shown."""

    cleared = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_PILL_HEIGHT)
        self.setStyleSheet(
            "QFrame { background: #0D1117; border: 1px solid #30363D;"
            " border-radius: 8px; }"
        )

        self._thumb = QLabel(self)
        self._thumb.setFixedSize(52, 32)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label = QLabel("", self)

        remove = QPushButton("×", self)
        remove.setFixedWidth(28)
        remove.setToolTip("Retirer le contexte")
        remove.clicked.connect(self.cleared.emit)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(self._thumb)
        layout.addWidget(self._label, 1)
        layout.addWidget(remove)

    def set_capture(self, capture: Capture) -> None:
        pixmap = QPixmap.fromImage(capture.image).scaled(
            52,
            32,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._thumb.setPixmap(pixmap)
        self._label.setText(capture.summary())


class AskPanel(QDialog):
    """Ask Claude about a capture, and read the answer as it arrives."""

    #: (question, capture or None)
    asked = Signal(str, object)
    interrupted = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Demander à Claude")
        self.setStyleSheet(STYLESHEET)
        self.resize(620, 560)

        self._capture: Capture | None = None
        self._answer = ""

        self._pill = _ContextPill(self)
        self._pill.cleared.connect(self._clear_capture)
        self._pill.hide()

        self._question = QPlainTextEdit(self)
        self._question.setPlaceholderText(
            "Qu'est-ce que tu veux savoir ? (Ctrl+Entrée pour envoyer)"
        )
        self._question.setFixedHeight(80)

        self._status = QLabel("", self, objectName="hint")
        self._view = QTextBrowser(self)
        self._view.setOpenExternalLinks(True)
        self._view.setPlaceholderText("La réponse de Claude apparaîtra ici.")

        self._send = QPushButton("Demander", self)
        self._send.setDefault(True)
        self._send.clicked.connect(self._submit)

        self._stop = QPushButton("Interrompre", self)
        self._stop.clicked.connect(self.interrupted.emit)
        self._stop.hide()

        self._copy = QPushButton("Copier", self)
        self._copy.clicked.connect(self._copy_answer)
        self._copy.setEnabled(False)

        close = QPushButton("Fermer", self)
        close.clicked.connect(self.hide)

        actions = QHBoxLayout()
        actions.addWidget(self._status, 1)
        actions.addWidget(self._copy)
        actions.addWidget(self._stop)
        actions.addWidget(close)
        actions.addWidget(self._send)

        layout = QVBoxLayout(self)
        layout.addWidget(self._pill)
        layout.addWidget(self._question)
        layout.addWidget(self._view, 1)
        layout.addLayout(actions)

        QShortcut(QKeySequence("Ctrl+Return"), self, self._submit)

    # -- context ----------------------------------------------------------

    def set_capture(self, capture: Capture | None) -> None:
        self._capture = capture
        if capture is None:
            self._pill.hide()
        else:
            self._pill.set_capture(capture)
            self._pill.show()

    def _clear_capture(self) -> None:
        self.set_capture(None)

    # -- conversation -----------------------------------------------------

    def open_with(self, capture: Capture | None = None) -> None:
        if capture is not None:
            self.set_capture(capture)
        self.show()
        _centre_on_cursor(self)
        self.raise_()
        self.activateWindow()
        self._question.setFocus()

    def _submit(self) -> None:
        question = self._question.toPlainText().strip()
        if not question and self._capture is None:
            return
        if not question:
            question = "Explique-moi ce que tu vois."

        self._answer = ""
        self._view.setMarkdown("")
        self._copy.setEnabled(False)
        self.set_busy(True)
        self.asked.emit(question, self._capture)

    def set_busy(self, busy: bool) -> None:
        self._send.setEnabled(not busy)
        self._question.setReadOnly(busy)
        self._stop.setVisible(busy)
        if busy:
            self._status.setText("Claude réfléchit…")

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def append_answer(self, chunk: str) -> None:
        self._answer += chunk
        self._view.setMarkdown(self._answer)
        bar = self._view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def reset_answer(self) -> None:
        """Throw away a partial answer (the turn failed mid-stream)."""
        self._answer = ""
        self._view.setMarkdown("")
        self._copy.setEnabled(False)

    def show_error(self, message: str) -> None:
        """Replace the answer with the failure, so no raw SDK text is left."""
        self.reset_answer()
        self._view.setMarkdown(f"**Échec**\n\n{message}")
        self.finish("Échec")

    def finish(self, status: str = "") -> None:
        self.set_busy(False)
        self._status.setText(status)
        self._copy.setEnabled(bool(self._answer))

    def _copy_answer(self) -> None:
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(self._answer)
        self._status.setText("Copié")


class ApprovalCard(QDialog):
    """Claude wants to do something. Say yes, always, or no."""

    #: "allow" | "always" | "deny"
    decided = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Autorisation")
        self.setStyleSheet(STYLESHEET)
        self.setMinimumWidth(520)

        self._title = QLabel("", self)
        self._detail = QTextBrowser(self)
        self._detail.setFixedHeight(120)
        self._countdown = QLabel("", self, objectName="hint")

        deny = QPushButton("Refuser (N)", self)
        deny.clicked.connect(lambda: self._decide("deny"))
        always = QPushButton("Toujours autoriser", self)
        always.clicked.connect(lambda: self._decide("always"))
        allow = QPushButton("Autoriser (Y)", self)
        allow.setDefault(True)
        allow.clicked.connect(lambda: self._decide("allow"))

        buttons = QHBoxLayout()
        buttons.addWidget(self._countdown, 1)
        buttons.addWidget(deny)
        buttons.addWidget(always)
        buttons.addWidget(allow)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._detail)
        layout.addLayout(buttons)

        QShortcut(QKeySequence("Y"), self, lambda: self._decide("allow"))
        QShortcut(QKeySequence("N"), self, lambda: self._decide("deny"))

        self._remaining = 0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def ask(self, request: ToolRequest, timeout_seconds: int) -> None:
        self._title.setText(request.title())
        self._detail.setPlainText(request.detail)
        self._remaining = max(1, timeout_seconds)
        self._tick_label()
        self._timer.start()

        self.show()
        _centre_on_cursor(self)
        self.raise_()
        self.activateWindow()

    def _tick(self) -> None:
        self._remaining -= 1
        if self._remaining <= 0:
            # Silence is not consent: timing out denies, it never allows.
            self._decide("deny")
            return
        self._tick_label()

    def _tick_label(self) -> None:
        self._countdown.setText(f"Refus automatique dans {self._remaining} s")

    def _decide(self, decision: str) -> None:
        if not self.isVisible():
            return
        self._timer.stop()
        self.hide()
        self.decided.emit(decision)

    def reject(self) -> None:  # Esc
        self._decide("deny")
