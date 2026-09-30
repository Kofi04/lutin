"""The preview shown after a capture, before anything leaves the machine.

This dialog is not decoration. Capturing the screen can pick up passwords, a
private browsing session, a client's data - so nothing is ever sent without the
user seeing exactly what would be sent. There is deliberately no option to skip
it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .capture import Capture
from .ui import STYLESHEET, _centre_on_cursor

_MAX_PREVIEW = 560  # longest edge of the thumbnail shown in the dialog


class CapturePreview(QDialog):
    """Shows a capture and asks what to do with it."""

    #: The user confirmed; the capture may be used.
    confirmed = Signal(object)  # Capture

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ce qui sera envoyé")
        self.setStyleSheet(STYLESHEET)

        self._capture: Capture | None = None

        self._thumbnail = QLabel(self)
        self._thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumbnail.setMinimumSize(320, 200)
        self._thumbnail.setStyleSheet(
            "border: 1px solid #30363D; border-radius: 6px; background: #0D1117;"
        )

        self._summary = QLabel("", self, objectName="hint")
        self._warning = QLabel(
            "Vérifiez qu'aucun mot de passe ni donnée privée n'apparaît.",
            self,
            objectName="hint",
        )
        self._warning.setWordWrap(True)

        discard = QPushButton("Annuler", self)
        discard.clicked.connect(self.reject)
        confirm = QPushButton("Utiliser cette capture", self)
        confirm.setDefault(True)
        confirm.clicked.connect(self._confirm)

        buttons = QHBoxLayout()
        buttons.addWidget(self._summary)
        buttons.addStretch(1)
        buttons.addWidget(discard)
        buttons.addWidget(confirm)

        layout = QVBoxLayout(self)
        layout.addWidget(self._thumbnail, 1)
        layout.addWidget(self._warning)
        layout.addLayout(buttons)

        QShortcut(QKeySequence("Ctrl+Return"), self, self._confirm)

    def show_capture(self, capture: Capture) -> None:
        self._capture = capture
        self._summary.setText(capture.summary())

        pixmap = QPixmap.fromImage(capture.image)
        if max(pixmap.width(), pixmap.height()) > _MAX_PREVIEW:
            pixmap = pixmap.scaled(
                _MAX_PREVIEW,
                _MAX_PREVIEW,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._thumbnail.setPixmap(pixmap)
        self.adjustSize()

        self.show()
        _centre_on_cursor(self)
        self.raise_()
        self.activateWindow()

    def _confirm(self) -> None:
        if self._capture is not None:
            self.confirmed.emit(self._capture)
        self.accept()
