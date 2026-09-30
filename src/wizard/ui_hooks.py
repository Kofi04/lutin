"""Showing the settings.json diff before Little Wizard touches it.

`~/.claude/settings.json` belongs to the user and Claude Code depends on it, so
nothing is written until the exact change has been shown and accepted. The
backup path is reported afterwards so the way back is never a mystery.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .bridge.installer import InstallPlan
from .ui import _centre_on_cursor


class HookDiffDialog(QDialog):
    """Presents a settings.json change and asks for a yes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.resize(760, 520)

        self._intro = QLabel("", self)
        self._intro.setWordWrap(True)

        self._diff = QPlainTextEdit(self)
        self._diff.setReadOnly(True)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(9)
        self._diff.setFont(font)

        cancel = QPushButton("Annuler", self)
        cancel.clicked.connect(self.reject)
        self._confirm = QPushButton("Écrire", self)
        self._confirm.setDefault(True)
        self._confirm.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self._confirm)

        layout = QVBoxLayout(self)
        layout.addWidget(self._intro)
        layout.addWidget(self._diff, 1)
        layout.addLayout(buttons)

    def confirm(self, plan: InstallPlan, installing: bool) -> bool:
        """Show the plan. Returns True when the user accepted."""
        action = "installer" if installing else "désinstaller"
        self.setWindowTitle(f"{action.capitalize()} les hooks Claude Code")

        if not plan.changed:
            self._intro.setText(
                f"Rien à {action} : {plan.path} contient déjà ce qu'il faut."
            )
            self._diff.setPlainText("")
            self._confirm.setEnabled(False)
        else:
            self._intro.setText(
                f"Little Wizard va modifier {plan.path}.\n"
                "Une copie horodatée est faite avant écriture, et seules les "
                "entrées de Little Wizard sont touchées."
            )
            self._diff.setPlainText(plan.diff)
            self._confirm.setEnabled(True)

        self.show()
        _centre_on_cursor(self)
        self.raise_()
        self.activateWindow()
        return self.exec() == QDialog.DialogCode.Accepted


def summarise_backup(path) -> str:
    if path is None:
        return "Aucune sauvegarde nécessaire (le fichier n'existait pas)."
    return f"Sauvegarde : {path.name}"
