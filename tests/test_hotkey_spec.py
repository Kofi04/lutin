"""Capturing a shortcut from a key press, and catching two that collide."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from wizard.hotkey_spec import (
    find_conflicts,
    invalid_bindings,
    normalise,
    spec_from_qt,
)

CTRL = Qt.KeyboardModifier.ControlModifier
ALT = Qt.KeyboardModifier.AltModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
WIN = Qt.KeyboardModifier.MetaModifier
NONE = Qt.KeyboardModifier.NoModifier


# -- capturing -------------------------------------------------------------


@pytest.mark.parametrize(
    ("modifiers", "key", "expected"),
    [
        (CTRL | ALT, Qt.Key.Key_N, "ctrl+alt+N"),
        (CTRL | SHIFT, Qt.Key.Key_S, "ctrl+shift+S"),
        (ALT, Qt.Key.Key_Space, "alt+space"),
        (WIN, Qt.Key.Key_F5, "win+f5"),
        (CTRL | ALT, Qt.Key.Key_7, "ctrl+alt+7"),
        (CTRL, Qt.Key.Key_F12, "ctrl+f12"),
    ],
)
def test_a_key_press_becomes_a_spec(modifiers, key, expected):
    assert spec_from_qt(modifiers, key) == expected


def test_a_captured_spec_parses_back():
    # What the settings window captures must be something the hotkey layer
    # can actually register.
    spec = spec_from_qt(CTRL | ALT, Qt.Key.Key_K)

    assert normalise(spec) is not None


def test_modifiers_alone_are_not_a_shortcut_yet():
    # The user is still holding Ctrl and reaching for the letter.
    assert spec_from_qt(CTRL, Qt.Key.Key_Control) is None
    assert spec_from_qt(CTRL | ALT, Qt.Key.Key_Alt) is None
    assert spec_from_qt(SHIFT, Qt.Key.Key_Shift) is None


def test_a_bare_key_is_refused():
    # A global hotkey with no modifier would eat that key in every app.
    assert spec_from_qt(NONE, Qt.Key.Key_A) is None


def test_shift_alone_is_refused():
    # shift+A would swallow every capital A typed anywhere on the machine.
    assert spec_from_qt(SHIFT, Qt.Key.Key_A) is None


def test_an_unsupported_key_is_refused():
    # Arrow keys are not in the hotkey vocabulary; better to refuse than to
    # capture something that can never be registered.
    assert spec_from_qt(CTRL, Qt.Key.Key_Left) is None


def test_modifier_order_is_canonical():
    # However the user presses them, the text comes out the same way round.
    assert spec_from_qt(ALT | CTRL, Qt.Key.Key_N) == "ctrl+alt+N"


# -- conflicts -------------------------------------------------------------


def test_identical_bindings_conflict():
    conflicts = find_conflicts({"note": "ctrl+alt+N", "palette": "ctrl+alt+N"})

    assert len(conflicts) == 1
    assert {conflicts[0].first, conflicts[0].second} == {"note", "palette"}


def test_conflicts_are_found_by_meaning_not_by_text():
    # Same shortcut, three spellings. A text comparison calls these different
    # and lets the user register one that silently never fires.
    conflicts = find_conflicts(
        {"a": "ctrl+alt+n", "b": "Control+Alt+N", "c": "alt+ctrl+n"}
    )

    assert len(conflicts) == 2


def test_distinct_bindings_do_not_conflict():
    assert find_conflicts({"a": "ctrl+alt+N", "b": "ctrl+alt+V"}) == []


def test_blank_bindings_never_conflict():
    assert find_conflicts({"a": "", "b": "", "c": "   "}) == []


def test_invalid_bindings_do_not_count_as_conflicts():
    assert find_conflicts({"a": "hyper+x", "b": "hyper+x"}) == []


def test_the_shipped_defaults_do_not_conflict():
    from wizard.config import Hotkeys

    defaults = vars(Hotkeys())

    assert find_conflicts(defaults) == []
    assert invalid_bindings(defaults) == []


def test_invalid_bindings_are_reported():
    assert invalid_bindings({"good": "ctrl+alt+N", "bad": "ctrl+nope"}) == ["bad"]
