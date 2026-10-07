"""The core's own checks on what a settings window sends."""

from __future__ import annotations

import pytest

from wizard import settings_schema
from wizard.config import Config
from wizard.settings_schema import SettingError, check


def test_every_field_exists_in_the_config():
    config = Config()
    for f in settings_schema.FIELDS:
        assert hasattr(getattr(config, f.section), f.key), f"{f.section}.{f.key}"


def test_every_hotkey_has_a_label():
    assert set(settings_schema.HOTKEY_LABELS) <= set(vars(Config().hotkeys))


@pytest.mark.parametrize(
    ("section", "key", "value", "message"),
    [
        ("claude", "enabled", 1, "oui ou non"),
        ("appearance", "scale", True, "un nombre"),
        ("appearance", "scale", "2", "un nombre"),
        ("claude", "permission_timeout_seconds", 12.5, "entier"),
        ("clipboard", "max_entries", 5, "entre 10 et 5000"),
        ("hotkeys", "quick_note", 3, "un raccourci"),
    ],
)
def test_wrong_values_are_refused_in_french(section, key, value, message):
    with pytest.raises(SettingError, match=message):
        check(section, key, value)


def test_values_come_back_in_the_fields_type():
    assert check("claude", "permission_timeout_seconds", 30.0) == 30
    assert check("appearance", "opacity", 0.5) == 0.5
    assert check("hotkeys", "quick_note", "  ctrl+alt+N ") == "ctrl+alt+N"


def test_describe_leaves_out_what_a_field_does_not_have():
    described = settings_schema.field("claude", "enabled").describe()
    assert "minimum" not in described and "suffix" not in described
    assert described["label"] == "Activer Claude"
