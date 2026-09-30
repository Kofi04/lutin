"""The first-run screen: who he is, what the shortcuts are, what is not set up.

Shown once. Its job is to make the three things that silently do not work on a
fresh machine visible before they bite: Claude Code not being logged in, the
hooks not being installed, and the tray icon hiding in the overflow area on
Windows 10. Everything else can be discovered by using the app.

It checks rather than asserts: each line reports the real state of this
machine, so it never promises something that is not true.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .branding import APP_NAME, CHARACTER_NAME
from .character.animation import still_frame
from .character.emote import Emote
from .character.renderer import load_renderer
from .config import Hotkeys
from .paths import state_path

_DONE_KEY = "onboarding/done"
_PORTRAIT = 132


@dataclass(frozen=True)
class Check:
    """One line of "is this set up?"."""

    label: str
    ok: bool
    detail: str
    #: Text for a button that fixes it, or "" when there is nothing to do.
    action: str = ""


def already_shown(settings: QSettings | None = None) -> bool:
    store = settings or QSettings(str(state_path()), QSettings.Format.IniFormat)
    return bool(store.value(_DONE_KEY, False, type=bool))


def mark_shown(settings: QSettings | None = None) -> None:
    store = settings or QSettings(str(state_path()), QSettings.Format.IniFormat)
    store.setValue(_DONE_KEY, True)
    store.sync()


def shortcut_rows(hotkeys: Hotkeys) -> list[tuple[str, str]]:
    """The shortcuts worth learning on day one, in the order you would use them."""
    rows = [
        ("Demander à Claude", hotkeys.ask_claude),
        ("Montrer une zone de l'écran", hotkeys.capture_region),
        ("Palette de commandes", hotkeys.launcher),
        ("Note rapide", hotkeys.quick_note),
        ("Presse-papiers", hotkeys.clipboard),
    ]
    return [(label, spec) for label, spec in rows if spec]


def pretty(spec: str) -> str:
    """ctrl+alt+N -> Ctrl + Alt + N, the way people write shortcuts."""
    names = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Maj", "win": "Win"}
    rendered = []
    for part in (piece.strip() for piece in spec.split("+")):
        if not part:
            continue
        if part.lower() in names:
            rendered.append(names[part.lower()])
        elif len(part) == 1:
            rendered.append(part.upper())
        else:
            rendered.append(part.capitalize())
    return " + ".join(rendered)


class OnboardingDialog(QDialog):
    """Hello, here is how I work, and here is what is not ready yet."""

    install_hooks_requested = Signal()
    open_settings_requested = Signal()

    def __init__(self, hotkeys: Hotkeys, checks: list[Check], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Bienvenue dans {APP_NAME}")
        self.setObjectName("panel")
        # Windows will not let a background process take the foreground, and
        # that is exactly how this runs at logon with autostart: without this
        # the welcome opened behind whatever window the user had open, where
        # nobody would ever see it. It is shown once and dismissed with one
        # click, so staying on top costs nothing.
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(560)

        portrait = QLabel(self)
        portrait.setPixmap(_portrait())
        portrait.setFixedSize(_PORTRAIT, _PORTRAIT)

        title = QLabel(f"Bonjour, je suis {CHARACTER_NAME}.", self)
        title.setObjectName("display")
        title.setWordWrap(True)
        intro = QLabel(
            "Je vis au-dessus de votre barre des tâches. Montrez-moi quelque chose à "
            "l'écran, posez-moi une question, et je vous réponds ici — sans terminal. "
            "Mon bâton s'allume selon ce que je fais : doré au repos, bleu quand "
            "Claude travaille, ambre quand quelque chose vous attend.",
            self,
        )
        intro.setWordWrap(True)

        head_text = QVBoxLayout()
        head_text.addWidget(title)
        head_text.addWidget(intro)
        head_text.addStretch(1)

        head = QHBoxLayout()
        head.addWidget(portrait, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(head_text, 1)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.addLayout(head)
        layout.addWidget(_section("Les raccourcis à retenir"))
        layout.addWidget(self._shortcuts(hotkeys))
        layout.addWidget(_section("Sur cette machine"))
        layout.addWidget(self._checks(checks))

        start = QPushButton("C'est parti", self)
        start.setDefault(True)
        start.clicked.connect(self.accept)
        settings = QPushButton("Paramètres…", self)
        settings.setObjectName("quiet")
        settings.clicked.connect(self.open_settings_requested.emit)

        buttons = QHBoxLayout()
        buttons.addWidget(settings)
        buttons.addStretch(1)
        buttons.addWidget(start)
        layout.addLayout(buttons)

    def _shortcuts(self, hotkeys: Hotkeys) -> QWidget:
        box = QFrame(self)
        box.setObjectName("card")
        grid = QVBoxLayout(box)
        for label, spec in shortcut_rows(hotkeys):
            row = QHBoxLayout()
            name = QLabel(label, box)
            keys = QLabel(pretty(spec), box)
            keys.setObjectName("caption")
            row.addWidget(name, 1)
            row.addWidget(keys)
            grid.addLayout(row)
        hint = QLabel(
            "Et pour montrer une fenêtre entière : Ctrl + glisser le sorcier dessus.",
            box,
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        grid.addWidget(hint)
        return box

    def _checks(self, checks: list[Check]) -> QWidget:
        box = QFrame(self)
        box.setObjectName("card")
        column = QVBoxLayout(box)
        for check in checks:
            row = QHBoxLayout()
            mark = QLabel("✓" if check.ok else "!", box)
            mark.setObjectName("success" if check.ok else "warning")
            mark.setFixedWidth(18)
            text = QLabel(f"<b>{check.label}</b><br>{check.detail}", box)
            text.setWordWrap(True)
            text.setTextFormat(Qt.TextFormat.RichText)
            row.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(text, 1)
            if check.action and not check.ok:
                button = QPushButton(check.action, box)
                button.clicked.connect(self.install_hooks_requested.emit)
                row.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
            column.addLayout(row)
        return box


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("title")
    return label


def _portrait() -> QPixmap:
    """The wizard waving, drawn by whichever renderer the app is using."""
    image = QImage(_PORTRAIT, _PORTRAIT, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    load_renderer().draw(
        painter,
        float(_PORTRAIT),
        still_frame(Emote.GREETING, shadow=False).with_overrides(time=0.35),
    )
    painter.end()
    return QPixmap.fromImage(image)
