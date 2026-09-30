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
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .capture import Capture
from .markdown_blocks import Block, highlight, language_label, split_blocks
from .ui import _centre_on_cursor

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
        self.setObjectName("card")

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

        # Two views of one answer. While it streams, a single QTextBrowser
        # keeps up with the text cheaply. Once it is complete, any answer
        # with code is re-rendered as separate blocks, so each code block
        # can be highlighted and get its own Copy button — rebuilding
        # widgets on every streamed chunk would flicker and cost far more.
        self._blocks = QScrollArea(self)
        self._blocks.setWidgetResizable(True)
        self._blocks.setFrameShape(QFrame.Shape.NoFrame)
        self._blocks.hide()
        self._dark = True

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
        layout.addWidget(self._blocks, 1)
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

    def set_dark(self, dark: bool) -> None:
        """Which highlighting palette to use for code blocks."""
        self._dark = dark

    def _show_stream_view(self) -> None:
        self._blocks.hide()
        self._view.show()

    def append_answer(self, chunk: str) -> None:
        self._show_stream_view()
        self._answer += chunk
        self._view.setMarkdown(self._answer)
        bar = self._view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def reset_answer(self) -> None:
        """Throw away a partial answer (the turn failed mid-stream)."""
        self._answer = ""
        self._view.setMarkdown("")
        self._show_stream_view()
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
        blocks = split_blocks(self._answer)
        if any(block.kind == "code" for block in blocks):
            self._render_blocks(blocks)

    def _render_blocks(self, blocks: list[Block]) -> None:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)
        for block in blocks:
            if block.kind == "code":
                column.addWidget(CodeBlock(block, self._dark, page))
            else:
                prose = _AutoHeightBrowser(page)
                prose.setOpenExternalLinks(True)
                prose.setMarkdown(block.body)
                column.addWidget(prose)
        column.addStretch(1)
        self._blocks.setWidget(page)
        self._view.hide()
        self._blocks.show()

    def _copy_answer(self) -> None:
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(self._answer)
        self._status.setText("Copié")


class CodeBlock(QFrame):
    """One highlighted code block with its own Copy button."""

    def __init__(self, block: Block, dark: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self._code = block.body

        name = QLabel(language_label(block.language), self)
        name.setObjectName("caption")
        self._button = QPushButton("Copier", self)
        self._button.setObjectName("quiet")
        self._button.clicked.connect(self._copy)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(name, 1)
        head.addWidget(self._button)

        body = _AutoHeightBrowser(self, cap=420)
        # Code keeps its own line breaks: wrapping it would lie about
        # indentation, which in Python is the syntax.
        body.setLineWrapMode(QTextBrowser.LineWrapMode.NoWrap)
        body.setHtml(highlight(block.body, block.language, dark))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 10)
        layout.setSpacing(4)
        layout.addLayout(head)
        layout.addWidget(body)

    @property
    def code(self) -> str:
        return self._code

    def _copy(self) -> None:
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(self._code)
        self._button.setText("Copié")
        QTimer.singleShot(1400, lambda: self._button.setText("Copier"))


class _AutoHeightBrowser(QTextBrowser):
    """A text view exactly as tall as its content, at whatever width it gets.

    Measuring once at construction does not work: the widget has no real
    width yet, so the text wraps at a guessed width and the height comes out
    wrong — three lines of prose ended up in a box sized for ten. Measuring
    on every resize is the only way the number stays true.
    """

    def __init__(self, parent: QWidget | None = None, cap: int = 520) -> None:
        super().__init__(parent)
        self._cap = cap
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().contentsChanged.connect(self._refit)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refit()

    def _refit(self) -> None:
        width = self.viewport().width()
        if width <= 0:
            return
        document = self.document()
        document.setTextWidth(width)
        margins = self.contentsMargins()
        height = int(document.size().height()) + margins.top() + margins.bottom() + 4
        # Very long code scrolls inside its own block rather than making the
        # answer a mile long.
        if height > self._cap:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            height = self._cap
        if self.height() != height:
            self.setFixedHeight(height)


class ApprovalCard(QDialog):
    """Claude wants to do something. Say yes, always, or no."""

    #: "allow" | "always" | "deny"
    decided = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Autorisation")
        self.setMinimumWidth(520)
        # This card holds a Claude Code session open while it waits. Behind the
        # editor it is worse than useless: you would never see it, and the
        # session would stall until the timeout denied it.
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

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
