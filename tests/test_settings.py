"""The settings window: it must write only what changed, and refuse conflicts."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from wizard import config as config_module
from wizard.config import DEFAULT_CONFIG_TEMPLATE, load_config
from wizard.ui_settings import HOTKEY_LABELS, HotkeyEdit, SettingsWindow


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    target = tmp_path / "config.toml"
    target.write_text(
        DEFAULT_CONFIG_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    # The window resolves the path itself; point it at the copy.
    monkeypatch.setattr("wizard.ui_settings.config_path", lambda: target)
    monkeypatch.setattr(config_module, "config_path", lambda: target)
    return target


@pytest.fixture
def window(config_file):
    widget = SettingsWindow()
    widget.load(load_config(config_file))
    yield widget
    widget.deleteLater()


def field(window, section, key):
    return next(f for f in window._fields if (f.section, f.key) == (section, key))


# -- what gets written -----------------------------------------------------


def test_nothing_changed_means_nothing_to_write(window):
    assert window.changes() == []


def test_only_the_changed_setting_is_written(window):
    field(window, "claude", "prewarm").widget.setChecked(False)

    edits = window.changes()

    assert [(e.section, e.key, e.value) for e in edits] == [
        ("claude", "prewarm", False)
    ]


def test_saving_updates_the_file_and_keeps_the_comments(window, config_file):
    before = config_file.read_text(encoding="utf-8")
    field(window, "appearance", "scale").widget.setValue(2.0)
    saved = []
    window.saved.connect(lambda: saved.append(True))

    window._on_save()

    after = config_file.read_text(encoding="utf-8")
    assert load_config(config_file).appearance.scale == 2.0
    assert saved == [True]
    # Every comment line from the original is still there.
    for line in before.splitlines():
        if line.lstrip().startswith("#"):
            assert line in after


def test_a_hand_edit_elsewhere_is_not_overwritten(window, config_file):
    # The user edits the file by hand while the window is open...
    text = config_file.read_text(encoding="utf-8")
    config_file.write_text(
        text.replace("cpu_busy = 65.0", "cpu_busy = 50.0"), encoding="utf-8"
    )
    # ...then changes something unrelated in the window and saves.
    field(window, "claude", "prewarm").widget.setChecked(False)
    window._on_save()

    config = load_config(config_file)
    # Writing a full snapshot would have silently reverted this.
    assert config.monitor.cpu_busy == 50.0
    assert config.claude.prewarm is False


def test_the_saved_file_has_no_warnings(window, config_file):
    field(window, "appearance", "opacity").widget.setValue(0.8)
    field(window, "claude", "permission_timeout_seconds").widget.setValue(90)
    window._on_save()

    assert load_config(config_file).warnings == []


# -- hotkeys ---------------------------------------------------------------


def test_every_configured_hotkey_has_a_field(window):
    keys = {f.key for f in window._fields if f.section == "hotkeys"}

    assert keys == set(HOTKEY_LABELS)


def test_a_conflict_blocks_saving(window):
    field(window, "hotkeys", "quick_note").widget.setText("ctrl+alt+V")
    # clipboard is ctrl+alt+V by default.

    assert window._validate() is False
    assert not window._save.isEnabled()
    assert "ctrl+alt+V" in window._problem.text()


def test_a_conflict_spelt_differently_still_blocks_saving(window):
    field(window, "hotkeys", "quick_note").widget.setText("Control+Alt+v")

    assert window._validate() is False


def test_resolving_the_conflict_unblocks_saving(window):
    edit = field(window, "hotkeys", "quick_note").widget
    edit.setText("ctrl+alt+V")
    window._validate()
    edit.setText("ctrl+alt+J")

    assert window._validate() is True
    assert window._save.isEnabled()


def test_an_unrecognised_hotkey_blocks_saving(window):
    field(window, "hotkeys", "quick_note").widget.setText("hyper+q")

    assert window._validate() is False
    assert "n'est pas reconnu" in window._problem.text()


def test_a_blank_hotkey_is_allowed(window):
    field(window, "hotkeys", "quick_note").widget.setText("")

    assert window._validate() is True


# -- the capture field -----------------------------------------------------


def press(widget, key, modifiers=Qt.KeyboardModifier.NoModifier):
    from PySide6.QtGui import QKeyEvent

    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, modifiers))


@pytest.fixture
def capture():
    widget = HotkeyEdit("ctrl+alt+N")
    yield widget
    widget.deleteLater()


def test_pressing_a_combination_captures_it(capture):
    seen = []
    capture.captured.connect(seen.append)

    press(
        capture,
        Qt.Key.Key_K,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
    )

    assert capture.text() == "ctrl+alt+K"
    assert seen == ["ctrl+alt+K"]


def test_backspace_clears_the_binding(capture):
    press(capture, Qt.Key.Key_Backspace)

    assert capture.text() == ""


def test_escape_is_not_captured_as_a_binding(capture):
    press(capture, Qt.Key.Key_Escape)

    # Escape must remain the way out of the field.
    assert capture.text() == "ctrl+alt+N"


def test_a_bare_letter_is_ignored(capture):
    press(capture, Qt.Key.Key_Q)

    assert capture.text() == "ctrl+alt+N"


def test_the_field_cannot_be_typed_into(capture):
    assert capture.isReadOnly()
