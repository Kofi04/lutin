"""Framing, and the settings.json surgery the hook installer performs."""

from __future__ import annotations

import json

import pytest

from wizard.bridge import installer, protocol

# -- framing ---------------------------------------------------------------


def test_round_trip():
    frame = protocol.encode({"event": "PreToolUse", "payload": {"a": 1}})
    length = protocol.frame_length(frame[: protocol.HEADER_SIZE])

    assert length == len(frame) - protocol.HEADER_SIZE
    assert protocol.decode(frame[protocol.HEADER_SIZE :]) == {
        "event": "PreToolUse",
        "payload": {"a": 1},
    }


def test_non_ascii_survives():
    frame = protocol.encode({"detail": "réponse à Noël \u2014 ok"})
    body = frame[protocol.HEADER_SIZE :]

    assert protocol.decode(body)["detail"] == "réponse à Noël \u2014 ok"


@pytest.mark.parametrize("length", [0, protocol.MAX_FRAME + 1])
def test_implausible_lengths_are_rejected(length):
    import struct

    with pytest.raises(ValueError):
        protocol.frame_length(struct.pack(">I", length))


def test_short_header_is_rejected():
    with pytest.raises(ValueError):
        protocol.frame_length(b"\x00")


def test_a_non_object_frame_is_rejected():
    with pytest.raises(ValueError):
        protocol.decode(b"[1, 2, 3]")


# -- the hooks block --------------------------------------------------------


def hooks():
    return installer.build_hooks(
        launcher="C:/py/pythonw.exe", script="C:/l/wizard_hook.py"
    )


def test_every_event_is_registered():
    built = hooks()

    for event in installer.OBSERVED_EVENTS:
        assert event in built
    assert installer.DECIDING_EVENT in built


def test_observational_hooks_are_async_and_never_block():
    built = hooks()

    for event in installer.OBSERVED_EVENTS:
        hook = built[event][0]["hooks"][0]
        assert hook["async"] is True
        assert "timeout" not in hook


def test_the_deciding_hook_blocks_and_has_a_bounded_timeout():
    hook = hooks()[installer.DECIDING_EVENT][0]["hooks"][0]

    assert "async" not in hook
    # Must outlast the app's own wait, but stay under Claude Code's 600s default.
    assert 120 <= hook["timeout"] < 600


def test_exec_form_is_used():
    # Shell form would spawn a shell on every single tool call.
    hook = hooks()["PreToolUse"][0]["hooks"][0]

    assert hook["command"].endswith(".exe")
    assert hook["args"][0].endswith("wizard_hook.py")
    assert hook["args"][1] == "PreToolUse"


def test_tool_events_carry_a_matcher():
    built = hooks()

    assert built["PreToolUse"][0]["matcher"] == "*"
    assert "matcher" not in built["SessionStart"][0]


# -- merging ----------------------------------------------------------------


def foreign() -> dict:
    return {
        "model": "opus",
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "mine.sh"}]}
            ]
        },
    }


def test_merge_keeps_existing_hooks():
    merged = installer.merge_hooks(foreign(), hooks())

    commands = [
        h["command"]
        for g in merged["hooks"]["PreToolUse"]
        for h in g["hooks"]
    ]
    assert "mine.sh" in commands
    assert merged["model"] == "opus"


def test_merge_does_not_mutate_the_input():
    original = foreign()
    snapshot = json.dumps(original, sort_keys=True)

    installer.merge_hooks(original, hooks())

    assert json.dumps(original, sort_keys=True) == snapshot


def test_installing_twice_does_not_duplicate():
    once = installer.merge_hooks(foreign(), hooks())
    twice = installer.merge_hooks(once, hooks())

    assert len(twice["hooks"]["PreToolUse"]) == len(once["hooks"]["PreToolUse"])


def test_uninstall_removes_only_ours():
    merged = installer.merge_hooks(foreign(), hooks())

    cleaned = installer.remove_hooks(merged)

    assert cleaned == foreign()


def test_uninstall_on_untouched_settings_changes_nothing():
    assert installer.remove_hooks(foreign()) == foreign()


def test_uninstall_drops_the_hooks_key_when_it_empties():
    only_ours = installer.merge_hooks({}, hooks())

    assert "hooks" not in installer.remove_hooks(only_ours)


def test_is_installed_detects_our_entries(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(foreign()), encoding="utf-8")
    assert installer.is_installed(path) is False

    path.write_text(
        json.dumps(installer.merge_hooks(foreign(), hooks())), encoding="utf-8"
    )
    assert installer.is_installed(path) is True


def test_malformed_settings_read_as_empty(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ not json", encoding="utf-8")

    assert installer.read_settings(path) == {}


# -- writing ----------------------------------------------------------------


def test_apply_backs_up_then_writes(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(foreign()), encoding="utf-8")

    plan = installer.plan_install(path)
    assert plan.changed
    assert "wizard_hook.py" in plan.diff

    saved = installer.apply(plan)

    assert saved is not None and saved.exists()
    assert json.loads(saved.read_text(encoding="utf-8")) == foreign()
    assert installer.is_installed(path) is True


def test_apply_creates_a_missing_settings_file(tmp_path):
    path = tmp_path / "settings.json"

    installer.apply(installer.plan_install(path))

    assert path.exists()
    assert installer.is_installed(path) is True


def test_uninstall_restores_the_original(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(foreign()), encoding="utf-8")

    installer.apply(installer.plan_install(path))
    installer.apply(installer.plan_uninstall(path))

    assert json.loads(path.read_text(encoding="utf-8")) == foreign()


# -- the rename: hooks written under the old name ---------------------------


def legacy_hooks() -> dict:
    """What settings.json looks like after an install under the old app name."""
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "C:/py/pythonw.exe",
                            "args": ["C:/old/hooks/lutin_hook.py", "PreToolUse"],
                            "async": True,
                        }
                    ],
                }
            ]
        }
    }


def test_legacy_entries_are_recognised_as_ours(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(legacy_hooks()), encoding="utf-8")

    # If we did not recognise the old marker, "uninstall" would silently leave
    # a hook behind that spawns a dead process on every single tool call.
    assert installer.is_installed(path) is True


def test_uninstall_removes_legacy_entries(tmp_path):
    settings = legacy_hooks()
    cleaned = installer.remove_hooks(settings)

    assert "hooks" not in cleaned


def test_install_replaces_legacy_entries_instead_of_stacking(tmp_path):
    merged = installer.merge_hooks(legacy_hooks(), installer.build_hooks())

    groups = merged["hooks"]["PreToolUse"]
    assert len(groups) == 1
    blob = json.dumps(groups)
    assert "lutin_hook.py" not in blob
    assert "wizard_hook.py" in blob


def test_legacy_entries_count_as_stale(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(legacy_hooks()), encoding="utf-8")

    assert installer.is_stale(path) is True


def test_a_missing_script_path_counts_as_stale(tmp_path):
    ours = installer.build_hooks(
        launcher="C:/py/pythonw.exe",
        script=str(tmp_path / "moved-away" / "wizard_hook.py"),
    )
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"hooks": ours}), encoding="utf-8")

    assert installer.is_stale(path) is True


def test_a_real_install_is_not_stale(tmp_path):
    script = tmp_path / "wizard_hook.py"
    script.write_text("# hook\n", encoding="utf-8")
    ours = installer.build_hooks(launcher="C:/py/pythonw.exe", script=str(script))
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"hooks": ours}), encoding="utf-8")

    assert installer.is_installed(path) is True
    assert installer.is_stale(path) is False


def test_foreign_hooks_are_never_stale(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(foreign()), encoding="utf-8")

    assert installer.is_stale(path) is False


# -- the installed app (frozen by PyInstaller) -------------------------------


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    """sys as PyInstaller leaves it: <app>/core/wizard-core.exe."""
    core = tmp_path / "app" / "core" / "wizard-core.exe"
    monkeypatch.setattr(installer.sys, "frozen", True, raising=False)
    monkeypatch.setattr(installer.sys, "executable", str(core))
    return tmp_path / "app"


def test_installed_hooks_run_the_hook_exe_with_the_event_only(frozen):
    hooks = installer.build_hooks()
    hook = hooks["PreToolUse"][0]["hooks"][0]

    assert hook["command"] == str(frozen / "hook" / installer.HOOK_EXE_NAME)
    assert hook["args"] == ["PreToolUse"]


def test_hook_exe_entries_are_ours_and_stale_once_uninstalled(frozen, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"hooks": installer.build_hooks()}), encoding="utf-8")
    assert installer.is_installed(path) is True
    # The app removed: the exe the entries point at is gone.
    assert installer.is_stale(path) is True

    exe = frozen / "hook" / installer.HOOK_EXE_NAME
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    assert installer.is_stale(path) is False
    assert "hooks" not in installer.remove_hooks(json.loads(path.read_text("utf-8")))
