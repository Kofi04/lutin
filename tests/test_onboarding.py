"""The first-run screen: shown once, and honest about the machine."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings

from wizard.config import Hotkeys
from wizard.onboarding import already_shown, mark_shown, pretty, shortcut_rows


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "state.ini"), QSettings.Format.IniFormat)


def test_not_shown_on_a_fresh_machine(settings):
    assert already_shown(settings) is False


def test_shown_only_once(settings):
    mark_shown(settings)

    assert already_shown(settings) is True


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("ctrl+alt+N", "Ctrl + Alt + N"),
        ("ctrl+alt+Space", "Ctrl + Alt + Space"),
        ("ctrl+shift+s", "Ctrl + Maj + S"),
        ("win+f5", "Win + F5"),
    ],
)
def test_shortcuts_are_written_the_way_people_write_them(spec, expected):
    # French keyboards say "Maj", not "Shift".
    assert pretty(spec) == expected


def test_the_day_one_shortcuts_are_the_configured_ones():
    hotkeys = Hotkeys(ask_claude="ctrl+alt+Q")
    rows = dict(shortcut_rows(hotkeys))

    assert rows["Demander à Claude"] == "ctrl+alt+Q"


def test_a_disabled_shortcut_is_not_advertised():
    rows = dict(shortcut_rows(Hotkeys(quick_note="")))

    assert "Note rapide" not in rows
