"""Background agents, the mini-wizards, and routing approvals to the right owner."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal

from wizard.assistant.agents import MAX_RUNNING, AgentError, AgentManager
from wizard.claude.tool_request import ToolRequest


class FakeSession(QObject):
    chunk = Signal(str)
    activity = Signal(str)
    finished = Signal(str)
    failed = Signal(str)
    permission_requested = Signal(int, object)

    def __init__(self, folder):
        super().__init__()
        self.folder = folder
        self.asked: list[str] = []
        self.answers: list[tuple] = []
        self.cancelled = False
        self.closed = False
        self.session_id = "agent-session"

    def ask(self, question, capture=None):
        self.asked.append(question)

    def cancel(self):
        self.cancelled = True

    def shutdown(self):
        self.closed = True

    def answer_permission(self, request_id, decision):
        self.answers.append((request_id, decision))


@pytest.fixture
def manager():
    made: list[FakeSession] = []

    def make(folder):
        session = FakeSession(folder)
        made.append(session)
        return session

    agents = AgentManager(make_session=make)
    agents.made = made
    return agents


def record(manager):
    events = {"progress": [], "ended": [], "permission": []}
    manager.progressed.connect(lambda a, s, line: events["progress"].append((s, line)))
    manager.ended.connect(events["ended"].append)
    manager.permission_requested.connect(
        lambda a, rid, req: events["permission"].append((rid, req))
    )
    return events


# -- starting ---------------------------------------------------------------


def test_an_agent_gets_its_own_session_in_its_folder(manager, tmp_path):
    agent = manager.start("fais passer les tests", tmp_path)

    assert agent.folder == tmp_path.resolve()
    assert manager.made[0].folder == tmp_path.resolve()
    assert manager.made[0].asked == ["fais passer les tests"]


@pytest.mark.parametrize("task", ["", "   "])
def test_an_empty_task_is_refused(manager, tmp_path, task):
    with pytest.raises(AgentError):
        manager.start(task, tmp_path)


def test_a_missing_folder_is_refused(manager, tmp_path):
    with pytest.raises(AgentError, match="existe pas"):
        manager.start("x", tmp_path / "nope")


def test_only_a_few_run_at_once(manager, tmp_path):
    for _ in range(MAX_RUNNING):
        manager.start("x", tmp_path)

    with pytest.raises(AgentError, match="Déjà"):
        manager.start("un de trop", tmp_path)


# -- progress ---------------------------------------------------------------


def test_activity_becomes_progress(manager, tmp_path):
    events = record(manager)
    manager.start("x", tmp_path)
    manager.made[0].activity.emit("Edit app.py")

    assert ("working", "Edit app.py") in events["progress"]


def test_a_permission_request_is_passed_on_and_shown_as_waiting(manager, tmp_path):
    events = record(manager)
    manager.start("x", tmp_path)
    manager.made[0].permission_requested.emit(3, ToolRequest("Bash", "rm -rf build"))

    assert events["permission"][0][0] == 3
    assert events["progress"][-1][0] == "waiting"


def test_finishing_keeps_the_report_and_closes_the_session(manager, tmp_path):
    events = record(manager)
    agent = manager.start("x", tmp_path)
    session = manager.made[0]
    session.chunk.emit("J'ai corrigé ")
    session.chunk.emit("deux tests.")
    session.finished.emit("3 tours")

    assert agent.state == "done"
    assert agent.report == "J'ai corrigé deux tests."
    assert events["ended"] == [agent]
    assert events["progress"][-1][0] == "done"


def test_a_failure_is_reported_as_an_error(manager, tmp_path):
    events = record(manager)
    agent = manager.start("x", tmp_path)
    manager.made[0].failed.emit("Claude Code n'est pas connecté.")

    assert agent.state == "failed"
    assert events["progress"][-1] == ("error", "Claude Code n'est pas connecté.")


def test_stopping_cancels_and_ends_once(manager, tmp_path):
    events = record(manager)
    agent = manager.start("x", tmp_path)

    manager.stop(agent.id)
    # The session reports its interruption afterwards; that must not end the
    # agent a second time.
    manager.made[0].finished.emit("Interrompu.")

    assert manager.made[0].cancelled
    assert agent.state == "stopped"
    assert events["ended"] == [agent]


def test_a_finished_agent_frees_its_slot(manager, tmp_path):
    for _ in range(MAX_RUNNING):
        manager.start("x", tmp_path)
    manager.made[0].finished.emit("ok")

    manager.start("encore un", tmp_path)  # must not raise


def test_shutdown_closes_running_agents_synchronously(manager, tmp_path):
    manager.start("x", tmp_path)
    manager.shutdown()

    assert manager.made[0].cancelled and manager.made[0].closed


# -- the mini-wizards -------------------------------------------------------


# -- approvals reach their own owner ---------------------------------------


def test_same_request_id_from_two_owners_reaches_each_one(tmp_path, monkeypatch):
    """Owners number their requests independently.

    This used to route by `request_id in bridge_requests`: with a hook request
    and a Claude request both numbered 1 in the queue, answering Claude's could
    send the decision to the terminal instead.
    """
    import os

    monkeypatch.setenv("APPDATA", str(tmp_path))
    # No prewarm: a test must never start the real Claude Code CLI.
    config = tmp_path / "LittleWizard" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("[claude]\nprewarm = false\n", encoding="utf-8")
    from wizard.app import AvatarApp
    from wizard.presenter_remote import ProtocolPresenter

    app = AvatarApp([], ProtocolPresenter("test-token"))
    try:
        main_answers, bridge_answers = [], []
        app.claude.answer_permission = lambda rid, d: main_answers.append((rid, d))
        app.bridge.answer = lambda rid, d: bridge_answers.append((rid, d))
        agent_session = FakeSession(tmp_path)

        app._approval_queue.append(("bridge", 1, ToolRequest("Bash", "ls")))
        app._approval_queue.append((app.claude, 1, ToolRequest("Edit", "a.py")))
        app._approval_queue.append((agent_session, 1, ToolRequest("Write", "b.py")))

        app._show_next_approval()
        app._on_approval_decided("deny")
        app._on_approval_decided("allow")
        app._on_approval_decided("always")

        assert bridge_answers == [(1, "deny")]
        assert main_answers == [(1, "allow")]
        assert agent_session.answers == [(1, "always")]
    finally:
        app.claude.shutdown()
        app.storage.close()
        assert os.environ["APPDATA"] == str(tmp_path)
