"""Describing tool calls, keying "always allow" rules, and reading auth status."""

from __future__ import annotations

import json
import subprocess

import pytest

from wizard.claude import session as mod
from wizard.claude.session import AuthStatus, check_auth
from wizard.ui_claude import ToolRequest

# -- describing tool calls -------------------------------------------------


def test_detail_prefers_the_command_for_bash():
    assert mod._detail("Bash", {"command": "npm test", "timeout": 5}) == "npm test"


def test_detail_falls_back_to_the_file_path():
    assert mod._detail("Edit", {"file_path": "C:/x/app.py"}) == "C:/x/app.py"


def test_detail_dumps_unknown_inputs_as_json():
    detail = mod._detail("Weird", {"alpha": 1, "beta": [2, 3]})

    assert json.loads(detail) == {"alpha": 1, "beta": [2, 3]}


def test_describe_is_one_short_line():
    assert mod._describe("Read", {"file_path": "app.py"}) == "Read app.py"
    assert mod._describe("Bash", {"command": "pytest"}) == "Bash pytest"
    assert mod._describe("Unknown", {}) == "Unknown"


def test_describe_truncates_a_long_target():
    line = mod._describe("Read", {"file_path": "x" * 300})

    assert len(line) <= 80
    assert line.endswith("\u2026")


# -- "always allow" keys ---------------------------------------------------


def test_allowing_one_command_does_not_allow_another():
    # The whole point: "npm test" forever must not also mean "npm publish".
    assert mod._signature("Bash", {"command": "npm test"}) != mod._signature(
        "Bash", {"command": "npm publish"}
    )


def test_the_same_command_keys_the_same():
    assert mod._signature("Bash", {"command": "pytest"}) == mod._signature(
        "Bash", {"command": "pytest"}
    )


def test_file_tools_key_on_tool_and_path():
    assert mod._signature("Edit", {"file_path": "a.py"}) != mod._signature(
        "Edit", {"file_path": "b.py"}
    )
    assert mod._signature("Edit", {"file_path": "a.py"}) != mod._signature(
        "Write", {"file_path": "a.py"}
    )


# -- cost line -------------------------------------------------------------


class _Result:
    def __init__(self, cost=None, turns=None):
        self.total_cost_usd = cost
        self.num_turns = turns


def test_cost_line_reports_what_it_has():
    assert "2 tours" in mod._cost_line(_Result(turns=2))
    assert "1 tour" in mod._cost_line(_Result(turns=1))
    assert "$0.0123" in mod._cost_line(_Result(cost=0.0123))
    assert mod._cost_line(_Result()) == "Terminé."


# -- auth ------------------------------------------------------------------


def test_auth_status_message_tells_the_user_what_to_run():
    message = AuthStatus(logged_in=False, method="none").message()

    assert "claude auth login" in message


def test_logged_in_message_is_not_an_instruction():
    assert "login" not in AuthStatus(logged_in=True, method="oauth").message()


def test_check_auth_reads_the_cli_json(monkeypatch):
    payload = json.dumps({"loggedIn": True, "authMethod": "oauth"})
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, payload, ""),
    )

    status = check_auth()

    assert status.logged_in is True
    assert status.method == "oauth"


def test_check_auth_survives_garbage_output(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "not json", ""),
    )

    status = check_auth()

    assert status.logged_in is False


def test_check_auth_survives_a_missing_cli(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(subprocess, "run", boom)

    status = check_auth()

    assert status.logged_in is False
    assert "claude auth login" in status.message()


# -- the approval card's own wording --------------------------------------


@pytest.mark.parametrize(
    ("tool", "project", "expected"),
    [("Bash", "", "Claude veut utiliser Bash"), ("Edit", "wizard", "dans wizard")],
)
def test_tool_request_title(tool, project, expected):
    assert expected in ToolRequest(tool=tool, detail="x", project=project).title()
