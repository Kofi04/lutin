"""Hotkey specs: from a live key press, and checked against each other.

The settings window captures a shortcut by listening to a key press, which Qt
reports as a modifier mask plus a key code. The config stores it as text like
`ctrl+alt+N`. This module converts between the two and finds conflicts, and it
is pure — no widgets — so the rules are tested without a keyboard.

Two shortcuts conflict when they resolve to the same modifiers and virtual key,
not when their text matches: `ctrl+alt+n`, `Control+Alt+N` and `alt+ctrl+n` are
the same shortcut, and a text comparison would call them different and let the
user register one that silently never fires.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt

from . import winapi

#: Qt key -> our key name, for the keys that are not a single letter or digit.
_NAMED_KEYS: dict[int, str] = {
    int(Qt.Key.Key_Space): "space",
    int(Qt.Key.Key_Tab): "tab",
    int(Qt.Key.Key_Escape): "escape",
    int(Qt.Key.Key_Return): "enter",
    int(Qt.Key.Key_Enter): "enter",
    int(Qt.Key.Key_Insert): "insert",
    int(Qt.Key.Key_Delete): "delete",
    int(Qt.Key.Key_Home): "home",
    int(Qt.Key.Key_End): "end",
}
for _index in range(1, 25):
    _NAMED_KEYS[int(Qt.Key.Key_F1) + _index - 1] = f"f{_index}"

#: Keys that are only ever modifiers: pressing them alone is not a shortcut yet.
_MODIFIER_KEYS = frozenset(
    int(key)
    for key in (
        Qt.Key.Key_Control,
        Qt.Key.Key_Shift,
        Qt.Key.Key_Alt,
        Qt.Key.Key_Meta,
        Qt.Key.Key_AltGr,
    )
)


def _as_int(value) -> int:
    """Qt enums and flags as plain ints.

    PySide6 6.x models them as Python enums: `int()` works on `Qt.Key` but
    not on a combined `Qt.KeyboardModifier` flag, which needs `.value`.
    """
    if isinstance(value, int):
        return value
    return int(getattr(value, "value", value))


def spec_from_qt(modifiers, key: int) -> str | None:
    """Turn a key press into a spec, or None if it is not a usable shortcut yet.

    A usable global shortcut needs at least one of Ctrl, Alt or Win. Shift
    alone is refused: `shift+A` would swallow every capital A you type,
    everywhere, which is how you get a bug report titled "I can't type".
    """
    key = _as_int(key)
    if key in _MODIFIER_KEYS or key == 0:
        return None

    name = _key_name(key)
    if name is None:
        return None

    mods = _as_int(modifiers)
    parts = []
    if mods & _as_int(Qt.KeyboardModifier.ControlModifier):
        parts.append("ctrl")
    if mods & _as_int(Qt.KeyboardModifier.AltModifier):
        parts.append("alt")
    if mods & _as_int(Qt.KeyboardModifier.ShiftModifier):
        parts.append("shift")
    if mods & _as_int(Qt.KeyboardModifier.MetaModifier):
        parts.append("win")

    if not any(part in parts for part in ("ctrl", "alt", "win")):
        return None
    return "+".join([*parts, name])


def _key_name(key: int) -> str | None:
    if key in _NAMED_KEYS:
        return _NAMED_KEYS[key]
    if int(Qt.Key.Key_A) <= key <= int(Qt.Key.Key_Z):
        return chr(key).upper()
    if int(Qt.Key.Key_0) <= key <= int(Qt.Key.Key_9):
        return chr(key)
    return None


def normalise(spec: str) -> tuple[int, int] | None:
    """The (modifiers, virtual key) a spec resolves to, or None if invalid."""
    try:
        return winapi.parse_hotkey(spec)
    except winapi.HotkeyError:
        return None


@dataclass(frozen=True)
class Conflict:
    """Two actions bound to the same shortcut."""

    first: str
    second: str
    spec: str


def find_conflicts(bindings: dict[str, str]) -> list[Conflict]:
    """Every pair of actions that would fight over one shortcut.

    Blank bindings are "no shortcut" and never conflict.
    """
    seen: dict[tuple[int, int], str] = {}
    conflicts: list[Conflict] = []
    for action, spec in bindings.items():
        if not spec or not spec.strip():
            continue
        resolved = normalise(spec)
        if resolved is None:
            continue
        if resolved in seen:
            conflicts.append(Conflict(seen[resolved], action, spec))
        else:
            seen[resolved] = action
    return conflicts


def invalid_bindings(bindings: dict[str, str]) -> list[str]:
    """Actions whose spec does not parse at all."""
    return [
        action
        for action, spec in bindings.items()
        if spec and spec.strip() and normalise(spec) is None
    ]
