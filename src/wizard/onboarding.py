"""The first-run state and the facts the welcome shows, without any window.

Shared by the Qt welcome (ui_onboarding.py) and the core's services for the
Tauri one (services.py).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings

from .config import Hotkeys
from .paths import state_path

_DONE_KEY = "onboarding/done"


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
