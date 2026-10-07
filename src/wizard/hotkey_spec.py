"""Hotkey specs (`ctrl+alt+N`), checked against each other.

The app window captures a shortcut from a key press (ui/src/app/hotkey.ts)
and the config stores it as text. This module finds conflicts and invalid
specs, and it is pure — no widgets — so the rules are tested without a
keyboard.

Two shortcuts conflict when they resolve to the same modifiers and virtual key,
not when their text matches: `ctrl+alt+n`, `Control+Alt+N` and `alt+ctrl+n` are
the same shortcut, and a text comparison would call them different and let the
user register one that silently never fires.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import winapi


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
