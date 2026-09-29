"""The registry of Claude Code sessions and the feed lines it builds."""

from __future__ import annotations

from lutin.sessions import EVENT_STATES, PALETTE, SessionRegistry, describe


class FakeEvent:
    def __init__(self, name, tool_name="", tool_input=None):
        self.name = name
        self.tool_name = tool_name
        self.tool_input = tool_input or {}


# -- registry --------------------------------------------------------------


def test_a_session_is_created_on_first_sight():
    registry = SessionRegistry()

    session = registry.record("s1", "lutin", "working", "Edit app.py")

    assert session.project == "lutin"
    assert session.state == "working"
    assert session.last_action == "Edit app.py"


def test_the_same_id_is_one_session():
    registry = SessionRegistry()
    registry.record("s1", "lutin", "thinking")
    registry.record("s1", "lutin", "working", "Bash pytest")

    assert len(registry.sessions) == 1
    assert registry.sessions[0].state == "working"


def test_sessions_get_distinct_colours():
    registry = SessionRegistry()
    for index in range(3):
        registry.record(f"s{index}", f"p{index}", "idle")

    colours = [s.colour for s in registry.sessions]

    assert len(set(colours)) == 3
    assert all(c in PALETTE for c in colours)


def test_colours_wrap_instead_of_running_out():
    registry = SessionRegistry()
    for index in range(len(PALETTE) + 2):
        registry.record(f"s{index}", "p", "idle")

    assert len(registry.sessions) == len(PALETTE) + 2


def test_a_late_project_name_fills_in():
    registry = SessionRegistry()
    registry.record("s1", "", "idle")
    registry.record("s1", "lutin", "working")

    assert registry.sessions[0].project == "lutin"


def test_active_lists_only_busy_sessions():
    registry = SessionRegistry()
    registry.record("a", "x", "working")
    registry.record("b", "y", "done")
    registry.record("c", "z", "waiting")

    assert {s.session_id for s in registry.active} == {"a", "c"}


def test_the_feed_is_bounded():
    registry = SessionRegistry()
    for index in range(40):
        registry.record("s1", "p", "working", f"Edit file{index}.py")

    feed = registry.sessions[0].feed

    assert len(feed) <= 12
    assert feed[-1] == "Edit file39.py"


def test_forget_and_clear():
    registry = SessionRegistry()
    registry.record("s1", "p", "idle")
    registry.forget("s1")
    assert registry.sessions == []

    registry.record("s2", "p", "idle")
    registry.clear()
    assert registry.sessions == []


def test_label_falls_back_to_a_short_id():
    registry = SessionRegistry()
    session = registry.record("0123456789abcdef", "", "idle")

    assert session.label == "01234567"


def test_changed_fires_on_every_record():
    registry = SessionRegistry()
    seen = []
    registry.changed.connect(lambda: seen.append(1))

    registry.record("s1", "p", "idle")
    registry.record("s1", "p", "working")

    assert len(seen) == 2


# -- event mapping ---------------------------------------------------------


def test_every_registered_hook_event_maps_to_a_state():
    for event, (state, feeds) in EVENT_STATES.items():
        assert isinstance(state, str) and state
        assert isinstance(feeds, bool), event


def test_permission_requests_read_as_waiting():
    assert EVENT_STATES["PermissionRequest"][0] == "waiting"


def test_a_failed_tool_reads_as_error():
    assert EVENT_STATES["PostToolUseFailure"][0] == "error"


# -- feed lines ------------------------------------------------------------


def test_describe_keeps_a_command_whole():
    line = describe(FakeEvent("PreToolUse", "Bash", {"command": "npm run build"}))

    assert line == "Bash npm run build"


def test_describe_shortens_a_path_to_its_file_name():
    line = describe(
        FakeEvent("PreToolUse", "Edit", {"file_path": "C:/a/b/c/config.py"})
    )

    assert line == "Edit config.py"


def test_describe_truncates_a_very_long_command():
    line = describe(FakeEvent("PreToolUse", "Bash", {"command": "x" * 200}))

    assert len(line) <= 70
    assert line.endswith("\u2026")


def test_describe_falls_back_to_the_tool_then_the_event():
    assert describe(FakeEvent("PreToolUse", "Read", {})) == "Read"
    assert describe(FakeEvent("SessionStart")) == "SessionStart"
