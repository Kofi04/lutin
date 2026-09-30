"""Config loading: defaults, clamping, and tolerance for a malformed file."""

from __future__ import annotations

from wizard.config import load_config


def write(tmp_path, body: str):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_missing_file_falls_back_to_defaults(tmp_path):
    config = load_config(tmp_path / "nope.toml")

    assert config.appearance.scale == 1.0
    assert config.hotkeys.quick_note == "ctrl+alt+N"
    assert config.launcher == []
    assert any("aucun fichier" in warning for warning in config.warnings)


def test_reads_every_section(tmp_path):
    path = write(
        tmp_path,
        """
        [appearance]
        scale = 1.5
        opacity = 0.8
        offset_x = -20

        [hotkeys]
        quick_note = "ctrl+shift+K"

        [monitor]
        enabled = false
        cpu_busy = 50

        [clipboard]
        max_entries = 42

        [[launcher]]
        label = "Terminal"
        target = "wt.exe"
        args = ["-d", "."]
        """,
    )

    config = load_config(path)

    assert config.appearance.scale == 1.5
    assert config.appearance.opacity == 0.8
    assert config.appearance.offset_x == -20
    assert config.hotkeys.quick_note == "ctrl+shift+K"
    assert config.hotkeys.clipboard == "ctrl+alt+V"  # untouched default
    assert config.monitor.enabled is False
    assert config.monitor.cpu_busy == 50.0
    assert config.clipboard.max_entries == 42
    assert [(e.label, e.target, e.args) for e in config.launcher] == [
        ("Terminal", "wt.exe", ["-d", "."])
    ]
    assert config.warnings == []


def test_integers_are_accepted_where_a_float_is_expected(tmp_path):
    path = write(tmp_path, "[appearance]\nscale = 2\n")

    config = load_config(path)

    assert config.appearance.scale == 2.0
    assert isinstance(config.appearance.scale, float)
    assert config.warnings == []


def test_out_of_range_values_are_clamped(tmp_path):
    path = write(
        tmp_path,
        """
        [appearance]
        scale = 99.0
        opacity = 0.0

        [monitor]
        interval_seconds = 0.01

        [clipboard]
        max_entries = 1
        """,
    )

    config = load_config(path)

    assert config.appearance.scale == 4.0
    assert config.appearance.opacity == 0.2
    assert config.monitor.interval_seconds == 0.5
    assert config.clipboard.max_entries == 10


def test_wrong_types_warn_instead_of_raising(tmp_path):
    path = write(tmp_path, '[appearance]\nscale = "big"\n')

    config = load_config(path)

    assert config.appearance.scale == 1.0
    assert any("appearance.scale" in warning for warning in config.warnings)


def test_invalid_toml_falls_back_to_defaults(tmp_path):
    path = write(tmp_path, "[appearance\nscale = ")

    config = load_config(path)

    assert config.appearance.scale == 1.0
    assert any("lecture impossible" in warning for warning in config.warnings)


def test_incomplete_launcher_entries_are_skipped_not_fatal(tmp_path):
    path = write(
        tmp_path,
        """
        [[launcher]]
        label = "Good"
        target = "notepad.exe"

        [[launcher]]
        label = "No target"

        [[launcher]]
        target = "orphan.exe"
        """,
    )

    config = load_config(path)

    assert [entry.label for entry in config.launcher] == ["Good"]
    assert len(config.warnings) == 2


def test_booleans_are_not_mistaken_for_integers(tmp_path):
    path = write(tmp_path, "[appearance]\noffset_x = true\n")

    config = load_config(path)

    assert config.appearance.offset_x == 0
    assert any("offset_x" in warning for warning in config.warnings)
