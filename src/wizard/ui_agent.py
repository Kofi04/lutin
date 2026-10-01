"""Launching a background agent: what to do, and where it may work."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .paths import state_path
from .ui import _centre_on_cursor

_LAST_FOLDER = "agents/last_folder"


class AgentDialog(QDialog):
    """Task + folder, then Lancer."""

    #: (task, folder)
    launched = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Lancer un agent")
        self.setObjectName("panel")
        self.setMinimumWidth(520)
        self._settings = QSettings(str(state_path()), QSettings.Format.IniFormat)

        intro = QLabel(
            "L'agent travaille en arrière-plan dans le dossier choisi. Chaque action "
            "qui modifie quelque chose vous sera demandée, comme d'habitude.",
            self,
        )
        intro.setWordWrap(True)
        intro.setObjectName("hint")

        self._task = QPlainTextEdit(self)
        self._task.setPlaceholderText(
            "Que doit-il faire ? Par exemple : « fais passer les tests qui échouent »"
        )
        self._task.setFixedHeight(110)

        self._folder = QLineEdit(self)
        self._folder.setPlaceholderText("Dossier de travail")
        browse = QPushButton("Parcourir…", self)
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self._folder, 1)
        folder_row.addWidget(browse)

        self._problem = QLabel("", self)
        self._problem.setObjectName("danger")
        self._problem.hide()

        cancel = QPushButton("Annuler", self)
        cancel.clicked.connect(self.reject)
        launch = QPushButton("Lancer", self)
        launch.setDefault(True)
        launch.clicked.connect(self._launch)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(launch)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(QLabel("Tâche", self))
        layout.addWidget(self._task)
        layout.addWidget(QLabel("Dossier", self))
        layout.addLayout(folder_row)
        layout.addWidget(self._problem)
        layout.addLayout(buttons)

        QShortcut(QKeySequence("Ctrl+Return"), self, self._launch)

    def open_dialog(self) -> None:
        self._task.clear()
        self._problem.hide()
        last = self._settings.value(_LAST_FOLDER, "", type=str)
        self._folder.setText(last if last and Path(last).is_dir() else "")
        self.show()
        _centre_on_cursor(self)
        self.raise_()
        self.activateWindow()
        self._task.setFocus()

    def _browse(self) -> None:
        start = self._folder.text() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Dossier de l'agent", start)
        if chosen:
            self._folder.setText(chosen)

    def _launch(self) -> None:
        task = self._task.toPlainText().strip()
        folder = self._folder.text().strip()
        problem = ""
        if not task:
            problem = "Décrivez la tâche."
        elif not folder or not Path(folder).is_dir():
            problem = "Choisissez un dossier qui existe."
        if problem:
            self._problem.setText(problem)
            self._problem.show()
            return
        self._settings.setValue(_LAST_FOLDER, folder)
        self.accept()
        self.launched.emit(task, folder)
