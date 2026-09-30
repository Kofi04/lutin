"""Every Claude Code session Little Wizard knows about, internal or external.

A session is named after its working directory, the way coucou does it: that is
what you recognise at a glance, and it survives restarts of the terminal.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

#: Per-session colours, borrowed in spirit from coucou's agent palette.
PALETTE = (
    "#FF6B5B",
    "#2DD4A7",
    "#F7B32B",
    "#A78BFA",
    "#38BDF8",
    "#F472B6",
    "#34D399",
    "#FB923C",
)

#: How many recent actions to keep per session for the activity feed.
_FEED_DEPTH = 12


@dataclass
class Session:
    session_id: str
    project: str
    colour: str
    state: str = "idle"  # idle | thinking | working | waiting | done | error
    feed: deque = field(default_factory=lambda: deque(maxlen=_FEED_DEPTH))

    @property
    def label(self) -> str:
        return self.project or self.session_id[:8]

    @property
    def last_action(self) -> str:
        return self.feed[-1] if self.feed else ""


class SessionRegistry(QObject):
    """Tracks sessions and their latest activity."""

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sessions: dict[str, Session] = {}
        self._colour_index = 0

    @property
    def sessions(self) -> list[Session]:
        return list(self._sessions.values())

    @property
    def active(self) -> list[Session]:
        busy = ("thinking", "working", "waiting")
        return [s for s in self._sessions.values() if s.state in busy]

    def _next_colour(self) -> str:
        colour = PALETTE[self._colour_index % len(PALETTE)]
        self._colour_index += 1
        return colour

    def ensure(self, session_id: str, project: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            session = Session(
                session_id=session_id, project=project, colour=self._next_colour()
            )
            self._sessions[session_id] = session
        elif project and not session.project:
            session.project = project
        return session

    def record(
        self, session_id: str, project: str, state: str, action: str = ""
    ) -> Session:
        session = self.ensure(session_id, project)
        session.state = state
        if action:
            session.feed.append(action)
        self.changed.emit()
        return session

    def forget(self, session_id: str) -> None:
        if self._sessions.pop(session_id, None) is not None:
            self.changed.emit()

    def clear(self) -> None:
        if self._sessions:
            self._sessions.clear()
            self.changed.emit()


#: Hook event name -> (state, whether it contributes a feed line).
EVENT_STATES = {
    "SessionStart": ("idle", False),
    "UserPromptSubmit": ("thinking", False),
    "PreToolUse": ("working", True),
    "PostToolUse": ("working", False),
    "PostToolUseFailure": ("error", True),
    "PermissionRequest": ("waiting", True),
    "Stop": ("done", False),
    "SessionEnd": ("done", False),
}


def describe(event) -> str:
    """One feed line for a hook event, e.g. "Edit app.py"."""
    tool = event.tool_name
    if not tool:
        return event.name
    payload = event.tool_input
    for key in ("command", "file_path", "path", "pattern", "url"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            target = value
            if key != "command":
                target = value.replace("\\", "/").rsplit("/", 1)[-1]
            if len(target) > 60:
                target = target[:59] + "…"
            return f"{tool} {target}"
    return tool
