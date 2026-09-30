"""Hotkey string parsing and duration parsing - the two fiddly parsers."""

from __future__ import annotations

import pytest

from wizard.features.timers import parse_duration
from wizard.winapi import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
    HotkeyError,
    parse_hotkey,
)


def test_single_modifier_and_letter():
    modifiers, vk = parse_hotkey("ctrl+N")

    assert modifiers == MOD_NOREPEAT | MOD_CONTROL
    assert vk == ord("N")


def test_modifiers_combine_and_are_case_insensitive():
    modifiers, vk = parse_hotkey("CTRL+Alt+shift+WIN+k")

    assert modifiers == MOD_NOREPEAT | MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_WIN
    assert vk == ord("K")


def test_named_keys():
    assert parse_hotkey("ctrl+alt+space")[1] == 0x20
    assert parse_hotkey("alt+f4")[1] == 0x73
    assert parse_hotkey("ctrl+f12")[1] == 0x7B


def test_digits_are_valid_keys():
    assert parse_hotkey("ctrl+alt+1")[1] == ord("1")


def test_whitespace_is_tolerated():
    assert parse_hotkey(" ctrl + alt + n ") == parse_hotkey("ctrl+alt+n")


@pytest.mark.parametrize("spec", ["", "+", "hyper+n", "ctrl+nope", "ctrl+"])
def test_bad_specs_raise(spec):
    with pytest.raises(HotkeyError):
        parse_hotkey(spec)


# -- durations ------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("25", 1500),  # a bare number means minutes
        ("25m", 1500),
        ("90s", 90),
        ("2h", 7200),
        ("1h30", 5400),
        ("1h30m", 5400),
        ("25:00", 1500),
        ("1:30:00", 5400),
        (" 25 m ", 1500),
    ],
)
def test_durations(text, expected):
    assert parse_duration(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "0", "-5", "abc", "1x", "1:2:3:4", "m"])
def test_bad_durations_raise(text):
    with pytest.raises(ValueError):
        parse_duration(text)
