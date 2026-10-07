"""Catching two shortcuts that collide, and specs that do not parse."""

from __future__ import annotations

import pytest

from wizard.hotkey_spec import find_conflicts, invalid_bindings, normalise

# -- what the app window captures ---------------------------------------------


@pytest.mark.parametrize(
    "spec",
    # The shapes ui/src/app/hotkey.ts produces (its own tests list them).
    ["ctrl+alt+N", "win+N", "ctrl+5", "alt+shift+f12", "ctrl+space", "ctrl+enter"],
)
def test_a_spec_captured_in_the_app_window_parses(spec):
    assert normalise(spec) is not None


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
