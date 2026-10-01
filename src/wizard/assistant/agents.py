"""Background agents: a task, a folder, and its own Claude Code session.

You describe a job — "fix the failing tests", "write the README for this
project" — and pick the folder it may work in. It runs in its own session,
beside the conversation in the answer panel rather than inside it, reports
what it is doing on a mini-avatar, asks for every action through the same
approval card as everything else, and tells you when it is done.

Two limits are deliberate:

* **Every action is approved.** An agent that edits files unsupervised is
  exactly what "act, with my approval" ruled out; `allow_actions` is on and
  `auto_approve_read_only` only covers reading.
* **A few at a time.** Each agent is a Claude Code process; three running is
  plenty to supervise, and more would mostly queue approvals you cannot keep
  up with.
"""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..claude.session import ClaudeSession

MAX_RUNNING = 3

AGENT_PROMPT = (
    "Tu es un agent qui travaille en arrière-plan pour l'utilisateur, dans le "
    "dossier qu'il t'a confié. Fais la tâche de bout en bout sans poser de "
    "question, sauf blocage réel. Chaque action qui modifie quelque chose lui "
    "sera soumise pour accord : un refus veut dire de trouver une autre voie ou "
    "de t'arrêter, jamais de contourner. Termine par un court compte rendu en "
    "français : ce que tu as fait, ce qui reste, ce qu'il doit vérifier."
)


@dataclass
class Agent:
    id: int
    task: str
    folder: Path
    session: ClaudeSession
    #: "running" | "done" | "failed" | "stopped"
    state: str = "running"
    last_action: str = ""
    report: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    conversation_id: int | None = None

    @property
    def key(self) -> str:
        """The id this agent has in the session registry."""
        return f"agent-{self.id}"

    @property
    def label(self) -> str:
        return self.folder.name or str(self.folder)

    @property
    def running(self) -> bool:
        return self.state == "running"


class AgentError(ValueError):
    """The agent cannot be started, with a reason fit for the user."""


class AgentManager(QObject):
    """Starts, tracks and stops background agents."""

    #: (agent, state, action line) whenever an agent does something.
    progressed = Signal(object, str, str)
    #: (agent, request_id, ToolRequest)
    permission_requested = Signal(object, int, object)
    #: (agent) when it finishes, fails or is stopped.
    ended = Signal(object)

    def __init__(
        self,
        permission_timeout: int = 110,
        make_session=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._timeout = permission_timeout
        self._ids = itertools.count(1)
        self._agents: dict[int, Agent] = {}
        #: The user's memory.md, given to each new agent.
        self.memory = ""
        # Injectable so the tests can run agents without Claude Code.
        self._make_session = make_session or self._real_session

    def _real_session(self, folder: Path) -> ClaudeSession:
        return ClaudeSession(
            permission_timeout=self._timeout,
            allow_actions=True,
            auto_approve_read_only=True,
            prewarm=False,
            cwd=str(folder),
            system_prompt=AGENT_PROMPT,
            overlay=False,
        )

    # -- starting -----------------------------------------------------------

    @property
    def agents(self) -> list[Agent]:
        return list(self._agents.values())

    @property
    def running(self) -> list[Agent]:
        return [agent for agent in self._agents.values() if agent.running]

    def start(self, task: str, folder: str | Path) -> Agent:
        task = task.strip()
        if not task:
            raise AgentError("Décrivez la tâche à confier à l'agent.")
        path = Path(folder).expanduser()
        if not path.is_dir():
            raise AgentError(f"Ce dossier n'existe pas : {path}")
        if len(self.running) >= MAX_RUNNING:
            raise AgentError(
                f"Déjà {MAX_RUNNING} agents en cours. Attendez qu'un finisse "
                "ou arrêtez-en un."
            )

        session = self._make_session(path.resolve())
        if self.memory and hasattr(session, "set_memory"):
            session.set_memory(self.memory)
        agent = Agent(next(self._ids), task, path.resolve(), session)
        self._agents[agent.id] = agent

        session.activity.connect(lambda line, a=agent: self._on_activity(a, line))
        session.chunk.connect(lambda text, a=agent: self._on_chunk(a, text))
        session.finished.connect(lambda status, a=agent: self._on_finished(a, status))
        session.failed.connect(lambda message, a=agent: self._on_failed(a, message))
        session.permission_requested.connect(
            lambda rid, request, a=agent: self._on_permission(a, rid, request)
        )

        self.progressed.emit(agent, "thinking", "Démarrage…")
        session.ask(task)
        return agent

    # -- what the session reports ------------------------------------------

    def _on_activity(self, agent: Agent, line: str) -> None:
        if not agent.running:
            return
        agent.last_action = line
        self.progressed.emit(agent, "working", line)

    def _on_chunk(self, agent: Agent, text: str) -> None:
        agent.report += text

    def _on_permission(self, agent: Agent, request_id: int, request) -> None:
        self.progressed.emit(agent, "waiting", f"Attend votre accord : {request.tool}")
        self.permission_requested.emit(agent, request_id, request)

    def _on_finished(self, agent: Agent, status: str) -> None:
        if not agent.running:
            return
        agent.state = "stopped" if status == "Interrompu." else "done"
        self._end(agent)

    def _on_failed(self, agent: Agent, message: str) -> None:
        if not agent.running:
            return
        agent.state = "failed"
        agent.report = agent.report or message
        agent.last_action = message
        self._end(agent)

    def _end(self, agent: Agent) -> None:
        state = {"done": "done", "failed": "error", "stopped": "done"}[agent.state]
        self.progressed.emit(agent, state, agent.last_action)
        self.ended.emit(agent)
        # The process is not needed once the job is over; the report is kept.
        _close_later(agent.session)

    # -- stopping -----------------------------------------------------------

    def stop(self, agent_id: int) -> None:
        agent = self._agents.get(agent_id)
        if agent is None or not agent.running:
            return
        agent.state = "stopped"
        agent.last_action = "Arrêté."
        agent.session.cancel()
        self._end(agent)

    def forget(self, agent_id: int) -> None:
        agent = self._agents.pop(agent_id, None)
        if agent is not None and agent.running:
            agent.session.cancel()
            _close_later(agent.session)

    def shutdown(self) -> None:
        """At app exit: close synchronously.

        Windows does not kill child processes when their parent exits, so a
        background close racing the interpreter's exit would leave Claude
        Code processes running with nobody to stop them.
        """
        for agent in list(self._agents.values()):
            if agent.running:
                agent.session.cancel()
                agent.session.shutdown()


def _close_later(session: ClaudeSession) -> None:
    """Shut a finished agent's session down without freezing the interface.

    `shutdown` waits for the Claude Code process to close, which can take a
    second; this is called from a signal handler on the GUI thread. The
    method only touches the session's own loop through thread-safe calls,
    so running it on a helper thread is safe.
    """
    threading.Thread(
        target=session.shutdown, name="wizard-agent-close", daemon=True
    ).start()
