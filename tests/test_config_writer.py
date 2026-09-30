"""Writing config.toml without destroying the user's comments."""

from __future__ import annotations

import tomllib

import pytest

from wizard.config import DEFAULT_CONFIG_TEMPLATE, load_config
from wizard.config_writer import (
    ConfigWriteError,
    Edit,
    apply_edits,
    format_value,
    write_edits,
)

SAMPLE = """\
# Configuration de Little Wizard.
# Un commentaire en tête, que l'on doit retrouver intact.

[appearance]
scale = 1.0                      # taille du sorcier, de 0.5 à 4.0
opacity = 0.96                   # opacité, de 0.2 à 1.0

[claude]
enabled = true
# Un commentaire sur sa propre ligne.
prewarm = true

[[launcher]]
label = "VS Code"
target = "code"
"""


def parsed(text: str) -> dict:
    return tomllib.loads(text)


# -- values ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, "true"),
        (False, "false"),
        (3, "3"),
        (1.5, "1.5"),
        (2.0, "2.0"),
        ("ctrl+alt+N", '"ctrl+alt+N"'),
        ('dit "bonjour"', '"dit \\"bonjour\\""'),
        ("C:\\Users", '"C:\\\\Users"'),
    ],
)
def test_values_are_written_as_toml(value, expected):
    assert format_value(value) == expected


def test_a_whole_float_keeps_its_decimal_point():
    # Without it TOML reads an int back, and config.py rejects an int where it
    # expects a float — silently resetting the setting to its default.
    assert parsed(f"x = {format_value(2.0)}")["x"] == 2.0
    assert isinstance(parsed(f"x = {format_value(2.0)}")["x"], float)


def test_an_unsupported_type_is_refused():
    with pytest.raises(ConfigWriteError):
        format_value([1, 2])


# -- the point of the module: keep everything else ------------------------


def test_changing_a_value_keeps_its_comment():
    result = apply_edits(SAMPLE, [Edit("appearance", "scale", 2.0)])

    assert "scale = 2.0" in result
    assert "# taille du sorcier, de 0.5 à 4.0" in result
    assert parsed(result)["appearance"]["scale"] == 2.0


def test_the_comment_column_is_preserved():
    result = apply_edits(SAMPLE, [Edit("appearance", "scale", 1.25)])
    line = next(line for line in result.splitlines() if line.startswith("scale"))
    original = next(line for line in SAMPLE.splitlines() if line.startswith("scale"))

    assert line.index("#") == original.index("#")


def test_every_other_line_is_left_byte_for_byte():
    result = apply_edits(SAMPLE, [Edit("appearance", "opacity", 0.8)])

    before = SAMPLE.splitlines()
    after = result.splitlines()
    changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
    assert len(changed) == 1


def test_header_and_standalone_comments_survive():
    result = apply_edits(SAMPLE, [Edit("claude", "prewarm", False)])

    assert "# Configuration de Little Wizard." in result
    assert "# Un commentaire sur sa propre ligne." in result


def test_a_no_op_edit_changes_nothing():
    result = apply_edits(SAMPLE, [Edit("claude", "enabled", True)])

    assert result == SAMPLE


def test_the_right_section_is_edited():
    # `enabled` exists in more than one section of the real config.
    text = "[monitor]\nenabled = true\n\n[claude]\nenabled = true\n"
    result = apply_edits(text, [Edit("claude", "enabled", False)])

    assert parsed(result)["monitor"]["enabled"] is True
    assert parsed(result)["claude"]["enabled"] is False


def test_a_missing_key_is_added_to_its_section():
    result = apply_edits(SAMPLE, [Edit("claude", "allow_actions", False)])
    data = parsed(result)

    assert data["claude"]["allow_actions"] is False
    # Added inside [claude], not after [[launcher]].
    assert data["launcher"][0] == {"label": "VS Code", "target": "code"}


def test_a_missing_section_is_appended():
    result = apply_edits(SAMPLE, [Edit("voice", "language", "fr-FR")])

    assert parsed(result)["voice"]["language"] == "fr-FR"
    assert result.startswith("# Configuration de Little Wizard.")


def test_arrays_of_tables_are_not_mistaken_for_a_section_body():
    # The key after [[launcher]] must not be edited as if it belonged to the
    # section before it.
    text = "[claude]\nenabled = true\n\n[[launcher]]\nenabled = false\n"
    result = apply_edits(text, [Edit("claude", "enabled", False)])
    data = parsed(result)

    assert data["claude"]["enabled"] is False
    assert data["launcher"][0]["enabled"] is False


def test_windows_line_endings_are_kept():
    crlf = SAMPLE.replace("\n", "\r\n")
    result = apply_edits(crlf, [Edit("appearance", "scale", 3.0)])

    assert "\r\n" in result
    assert "\n" not in result.replace("\r\n", "")


def test_several_edits_apply_together():
    result = apply_edits(
        SAMPLE,
        [
            Edit("appearance", "scale", 1.5),
            Edit("appearance", "opacity", 0.5),
            Edit("claude", "prewarm", False),
        ],
    )
    data = parsed(result)

    assert data["appearance"] == {"scale": 1.5, "opacity": 0.5}
    assert data["claude"]["prewarm"] is False


def test_an_empty_file_gains_a_section():
    result = apply_edits("", [Edit("claude", "prewarm", False)])

    assert parsed(result) == {"claude": {"prewarm": False}}


# -- against the real template --------------------------------------------


def test_the_shipped_template_round_trips(tmp_path):
    target = tmp_path / "config.toml"
    target.write_text(
        DEFAULT_CONFIG_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8"
    )

    write_edits(
        target,
        [
            Edit("appearance", "scale", 1.5),
            Edit("hotkeys", "quick_note", "ctrl+shift+N"),
            Edit("claude", "prewarm", False),
        ],
    )
    config = load_config(target)

    assert config.warnings == []
    assert config.appearance.scale == 1.5
    assert config.hotkeys.quick_note == "ctrl+shift+N"
    assert config.claude.prewarm is False
    # And the French comments the user is told to read are all still there.
    original_comments = [
        line
        for line in DEFAULT_CONFIG_TEMPLATE.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("#")
    ]
    written = target.read_text(encoding="utf-8")
    for comment in original_comments:
        assert comment in written


def test_writing_is_atomic_and_leaves_no_temporary_file(tmp_path):
    target = tmp_path / "config.toml"
    target.write_text(SAMPLE, encoding="utf-8")

    write_edits(target, [Edit("appearance", "scale", 2.0)])

    assert not (tmp_path / "config.toml.tmp").exists()
    assert "scale = 2.0" in target.read_text(encoding="utf-8")


def test_a_no_op_write_does_not_touch_the_file(tmp_path):
    target = tmp_path / "config.toml"
    target.write_text(SAMPLE, encoding="utf-8")
    before = target.stat().st_mtime_ns

    write_edits(target, [Edit("claude", "enabled", True)])

    assert target.stat().st_mtime_ns == before
