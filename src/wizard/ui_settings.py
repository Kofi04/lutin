"""The settings window: a graphical face on config.toml.

`config.toml` stays the source of truth. This window reads it through
`load_config`, and writes only the keys you changed, one line at a time, through
`config_writer` — so the French comments that explain each setting are still
there afterwards, and a hand edit made while the window was closed is not
overwritten by a stale copy.

Shortcuts are captured live: click the field, press the combination. Conflicts
are caught before saving, by what the shortcuts *mean* rather than how they are
spelt.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import Config, config_path, load_config
from .config_writer import Edit, write_edits
from .hotkey_spec import find_conflicts, invalid_bindings, spec_from_qt
from .ui import _centre_on_cursor

#: French labels for each hotkey, in the order they are shown.
HOTKEY_LABELS: dict[str, str] = {
    "ask_claude": "Demander à Claude",
    "capture_region": "Montrer une zone",
    "capture_screen": "Montrer tout l'écran",
    "launcher": "Palette de commandes",
    "quick_note": "Note rapide",
    "clipboard": "Presse-papiers",
    "toggle_avatar": "Masquer / afficher le sorcier",
}


class HotkeyEdit(QLineEdit):
    """Click, press a combination, done. Backspace or Delete clears it."""

    captured = Signal(str)

    def __init__(self, spec: str, parent: QWidget | None = None) -> None:
        super().__init__(spec, parent)
        self.setReadOnly(True)
        self.setPlaceholderText("Aucun — cliquez puis appuyez")
        self.setToolTip(
            "Cliquez, puis appuyez sur la combinaison voulue. "
            "Retour arrière pour effacer."
        )

    def focusInEvent(self, event) -> None:
        self._before = self.text()
        self.setPlaceholderText("Appuyez sur une combinaison…")
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self.setPlaceholderText("Aucun — cliquez puis appuyez")
        super().focusOutEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        modifiers = event.modifiers()
        bare = modifiers == Qt.KeyboardModifier.NoModifier
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete) and bare:
            self.setText("")
            self.captured.emit("")
            return
        if key == Qt.Key.Key_Escape and bare:
            # Escape must stay the way out of the field, not become a binding.
            self.clearFocus()
            return
        if key == Qt.Key.Key_Tab and bare:
            super().keyPressEvent(event)
            return
        spec = spec_from_qt(modifiers, key)
        if spec is not None:
            self.setText(spec)
            self.captured.emit(spec)
        event.accept()


@dataclass(frozen=True)
class _Field:
    section: str
    key: str
    widget: QWidget

    def value(self):
        widget = self.widget
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QDoubleSpinBox):
            return round(widget.value(), 3)
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        raise TypeError(widget)


class SettingsWindow(QDialog):
    """Edit config.toml without opening it."""

    #: Emitted after a successful save, so the app can reload.
    saved = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Paramètres")
        self.setObjectName("panel")
        self.resize(560, 520)

        self._fields: list[_Field] = []
        self._original: dict[tuple[str, str], object] = {}

        self._tabs = QTabWidget(self)
        self._problem = QLabel("", self)
        self._problem.setObjectName("danger")
        self._problem.setWordWrap(True)
        self._problem.hide()

        open_file = QPushButton("Ouvrir config.toml", self)
        open_file.setObjectName("quiet")
        open_file.clicked.connect(self._open_file)

        cancel = QPushButton("Annuler", self)
        cancel.clicked.connect(self.reject)
        self._save = QPushButton("Enregistrer", self)
        self._save.setDefault(True)
        self._save.clicked.connect(self._on_save)

        buttons = QHBoxLayout()
        buttons.addWidget(open_file)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self._save)

        layout = QVBoxLayout(self)
        layout.addWidget(self._tabs, 1)
        layout.addWidget(self._problem)
        layout.addLayout(buttons)

    # -- building ---------------------------------------------------------

    def load(self, config: Config | None = None) -> None:
        """(Re)build every tab from the file on disk."""
        config = config or load_config()
        self._fields.clear()
        self._original.clear()
        while self._tabs.count():
            page = self._tabs.widget(0)
            self._tabs.removeTab(0)
            page.deleteLater()

        self._tabs.addTab(self._appearance_tab(config), "Apparence")
        self._tabs.addTab(self._hotkeys_tab(config), "Raccourcis")
        self._tabs.addTab(self._claude_tab(config), "Claude")
        self._tabs.addTab(self._system_tab(config), "Système")

        for field in self._fields:
            self._original[(field.section, field.key)] = field.value()
        self._validate()

    def _form(self) -> tuple[QWidget, QFormLayout]:
        page = QWidget()
        form = QFormLayout(page)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setVerticalSpacing(12)
        return page, form

    def _add(self, form: QFormLayout, label: str, field: _Field, hint: str = ""):
        self._fields.append(field)
        form.addRow(label, field.widget)
        if hint:
            note = QLabel(hint)
            note.setObjectName("hint")
            note.setWordWrap(True)
            form.addRow("", note)

    def _appearance_tab(self, config: Config) -> QWidget:
        page, form = self._form()
        scale = QDoubleSpinBox()
        scale.setRange(0.5, 4.0)
        scale.setSingleStep(0.25)
        scale.setValue(config.appearance.scale)
        self._add(form, "Taille", _Field("appearance", "scale", scale))

        opacity = QDoubleSpinBox()
        opacity.setRange(0.2, 1.0)
        opacity.setSingleStep(0.05)
        opacity.setValue(config.appearance.opacity)
        self._add(form, "Opacité", _Field("appearance", "opacity", opacity))

        through = QCheckBox("Laisser les clics traverser le sorcier")
        through.setChecked(config.appearance.click_through_when_idle)
        self._add(
            form,
            "",
            _Field("appearance", "click_through_when_idle", through),
            "Utile s'il est posé sur un bouton que vous utilisez souvent.",
        )
        return page

    def _hotkeys_tab(self, config: Config) -> QWidget:
        page, form = self._form()
        for key, label in HOTKEY_LABELS.items():
            edit = HotkeyEdit(getattr(config.hotkeys, key, ""))
            edit.captured.connect(lambda _spec: self._validate())
            self._add(form, label, _Field("hotkeys", key, edit))
        return page

    def _claude_tab(self, config: Config) -> QWidget:
        page, form = self._form()
        enabled = QCheckBox("Activer Claude")
        enabled.setChecked(config.claude.enabled)
        self._add(form, "", _Field("claude", "enabled", enabled))

        prewarm = QCheckBox("Se connecter dès le lancement")
        prewarm.setChecked(config.claude.prewarm)
        self._add(
            form,
            "",
            _Field("claude", "prewarm", prewarm),
            "La première question est immédiate, au prix d'un processus Claude "
            "Code qui reste ouvert tant que l'app tourne.",
        )

        actions = QCheckBox("Claude peut agir (chaque action vous est demandée)")
        actions.setChecked(config.claude.allow_actions)
        self._add(form, "", _Field("claude", "allow_actions", actions))

        read_only = QCheckBox("Lecture de fichiers sans demander")
        read_only.setChecked(config.claude.auto_approve_read_only)
        self._add(
            form,
            "",
            _Field("claude", "auto_approve_read_only", read_only),
            "Read, Glob, Grep, WebFetch et WebSearch ne modifient rien, mais ils "
            "laissent Claude lire tous les fichiers que vous pouvez lire.",
        )

        timeout = QSpinBox()
        timeout.setRange(5, 600)
        timeout.setSuffix(" s")
        timeout.setValue(config.claude.permission_timeout_seconds)
        self._add(
            form,
            "Délai d'autorisation",
            _Field("claude", "permission_timeout_seconds", timeout),
            "Passé ce délai sans réponse, l'action est refusée. "
            "Le silence ne vaut pas accord.",
        )
        return page

    def _system_tab(self, config: Config) -> QWidget:
        page, form = self._form()
        clipboard = QCheckBox("Enregistrer l'historique du presse-papiers")
        clipboard.setChecked(config.clipboard.enabled)
        self._add(
            form,
            "",
            _Field("clipboard", "enabled", clipboard),
            "Tout ce que vous copiez est gardé, mots de passe compris. "
            "Désactivez-le avant de copier un secret.",
        )

        entries = QSpinBox()
        entries.setRange(10, 5000)
        entries.setValue(config.clipboard.max_entries)
        self._add(form, "Entrées conservées", _Field("clipboard", "max_entries", entries))

        hidden = QCheckBox("Cacher mes panneaux des partages d'écran")
        hidden.setChecked(config.ui.exclude_from_capture)
        self._add(
            form,
            "",
            _Field("ui", "exclude_from_capture", hidden),
            "Les réponses et la palette restent visibles pour vous, pas pour "
            "ceux qui voient votre écran. Le sorcier lui-même reste visible : "
            "Windows ne permet pas de cacher une fenêtre transparente.",
        )

        monitor = QCheckBox("Refléter la charge de la machine dans son humeur")
        monitor.setChecked(config.monitor.enabled)
        self._add(form, "", _Field("monitor", "enabled", monitor))
        return page

    # -- validating and saving --------------------------------------------

    def _hotkey_bindings(self) -> dict[str, str]:
        return {
            field.key: field.value()
            for field in self._fields
            if field.section == "hotkeys"
        }

    def _validate(self) -> bool:
        bindings = self._hotkey_bindings()
        problems = []
        for conflict in find_conflicts(bindings):
            problems.append(
                f"« {HOTKEY_LABELS.get(conflict.first, conflict.first)} » et "
                f"« {HOTKEY_LABELS.get(conflict.second, conflict.second)} » "
                f"utilisent tous deux {conflict.spec}."
            )
        for action in invalid_bindings(bindings):
            problems.append(
                f"Le raccourci de « {HOTKEY_LABELS.get(action, action)} » "
                "n'est pas reconnu."
            )
        self._problem.setText("\n".join(problems))
        self._problem.setVisible(bool(problems))
        self._save.setEnabled(not problems)
        return not problems

    def changes(self) -> list[Edit]:
        """Only what differs from the file as loaded — nothing else is written."""
        return [
            Edit(field.section, field.key, field.value())
            for field in self._fields
            if field.value() != self._original.get((field.section, field.key))
        ]

    def _on_save(self) -> None:
        if not self._validate():
            return
        edits = self.changes()
        if edits:
            try:
                write_edits(config_path(), edits)
            except (OSError, ValueError) as exc:
                self._problem.setText(f"Impossible d'enregistrer : {exc}")
                self._problem.show()
                return
        self.accept()
        self.saved.emit()

    def _open_file(self) -> None:
        import os

        path = config_path()
        if path.exists():
            os.startfile(path)  # noqa: S606 - opening the user's own file

    def open_settings(self) -> None:
        self.load()
        self.show()
        _centre_on_cursor(self)
        self.raise_()
        self.activateWindow()
