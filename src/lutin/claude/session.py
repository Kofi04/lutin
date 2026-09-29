"""Driving a Claude Code session from the GUI thread.

The Agent SDK is asyncio; Qt is not. A single worker thread owns an event loop
for the whole life of the app, and every public method here is safe to call
from the GUI thread. Results come back as Qt signals.

Permissions are the delicate part. `can_use_tool` runs inside the event loop
and must *block* until the user answers, while the answer arrives from the Qt
thread. The handoff is an `asyncio.Future` completed through
`loop.call_soon_threadsafe`, with a timeout that denies rather than allows:
silence is not consent.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import itertools
import json
import subprocess
import sys
import threading
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from ..capture import Capture
from ..ui_claude import ToolRequest

#: Tools Claude may use without ever asking. Read-only, no side effects.
READ_ONLY_TOOLS = ["Read", "Glob", "Grep", "WebFetch", "WebSearch"]

_DENY_ON_TIMEOUT = "Aucune réponse de Lutin : action refusée par sécurité."


@dataclass(frozen=True)
class AuthStatus:
    logged_in: bool
    method: str
    detail: str = ""

    def message(self) -> str:
        if self.logged_in:
            return f"Connecté ({self.method})"
        return (
            "Claude Code n'est pas connecté sur cette machine. "
            "Lance `claude auth login` dans un terminal, puis réessaie."
        )


def check_auth(timeout: float = 20.0) -> AuthStatus:
    """Ask the CLI whether it can authenticate at all.

    Run this before the first question: without it, a missing login surfaces as
    a raw "OAuth session expired" deep inside the SDK, which tells the user
    nothing about what to do.
    """
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        completed = subprocess.run(
            ["claude", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return AuthStatus(False, "unknown", f"impossible de lancer claude ({exc})")

    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return AuthStatus(False, "unknown", completed.stdout.strip()[:200])

    return AuthStatus(
        logged_in=bool(data.get("loggedIn")),
        method=str(data.get("authMethod", "unknown")),
    )


class _PendingPermission:
    """One question waiting for the user, bridged across two threads."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.future: asyncio.Future = loop.create_future()

    def answer(self, decision: str) -> None:
        if not self.future.done():
            self.loop.call_soon_threadsafe(self.future.set_result, decision)


class ClaudeSession(QObject):
    """One persistent conversation with Claude Code."""

    #: Streaming answer text.
    chunk = Signal(str)
    #: Short line describing what Claude is doing ("Lit config.py").
    activity = Signal(str)
    #: The turn ended. Carries a short status line.
    finished = Signal(str)
    #: The turn failed. Carries a message fit for the user.
    failed = Signal(str)
    #: Discard whatever has been streamed so far (the turn failed mid-answer).
    reset_answer = Signal()
    #: Claude wants to use a tool: (request_id, ToolRequest).
    permission_requested = Signal(int, object)

    def __init__(
        self,
        permission_timeout: int = 110,
        allow_actions: bool = True,
        auto_approve_read_only: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._permission_timeout = permission_timeout
        self._allow_actions = allow_actions
        self._auto_approve_read_only = auto_approve_read_only

        self._session_id: str | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, _PendingPermission] = {}
        self._always: set[str] = set()
        self._task: asyncio.Task | None = None

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="lutin-claude", daemon=True
        )
        self._thread.start()

    # -- lifecycle --------------------------------------------------------

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def shutdown(self) -> None:
        try:
            future = asyncio.run_coroutine_threadsafe(self._drain(), self._loop)
            future.result(timeout=5.0)
        except Exception:
            pass  # shutting down: nothing here is worth failing over
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=3.0)
        if not self._loop.is_running():
            self._loop.close()

    async def _drain(self) -> None:
        """Cancel the running turn and let the SDK close its subprocess.

        Without this the event loop stops while the transports are still open
        and Python finalises them at interpreter exit, which prints a wall of
        "I/O operation on closed pipe".
        """
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
        await asyncio.sleep(0.15)

    @property
    def session_id(self) -> str | None:
        """The Claude Code session being continued, once one exists."""
        return self._session_id

    def reset(self) -> None:
        """Start a fresh conversation next time."""
        self._session_id = None
        self._always.clear()

    # -- asking -----------------------------------------------------------

    def ask(self, question: str, capture: Capture | None = None) -> None:
        """Send a question (optionally with an image). Safe from the GUI thread."""
        if self._task is not None and not self._task.done():
            self.failed.emit("Une question est déjà en cours.")
            return
        asyncio.run_coroutine_threadsafe(self._start(question, capture), self._loop)

    def cancel(self) -> None:
        task = self._task
        if task is not None and not task.done():
            self._loop.call_soon_threadsafe(task.cancel)

    async def _start(self, question: str, capture: Capture | None) -> None:
        self._task = asyncio.current_task()
        try:
            await self._run_turn(question, capture)
        except asyncio.CancelledError:
            self.finished.emit("Interrompu.")
        except Exception as exc:  # the SDK raises a wide range of errors
            self.failed.emit(self._explain(exc))

    def _explain(self, exc: Exception) -> str:
        text = str(exc)
        if "OAuth" in text or "authenticate" in text.lower():
            return (
                "Claude Code n'est pas connecté. Lance `claude auth login` "
                "dans un terminal, puis réessaie."
            )
        return text[:400]

    def _options(self):
        import warnings

        from claude_agent_sdk import ClaudeAgentOptions
        from claude_agent_sdk.types import CanUseToolShadowedWarning

        # `allowed_tools` pre-approves; it does not restrict. Anything outside
        # the list still reaches `can_use_tool`, which is where the user decides.
        allowed = list(READ_ONLY_TOOLS) if self._auto_approve_read_only else []
        # The SDK warns that `allowed_tools` shadows `can_use_tool`. That is
        # exactly what auto_approve_read_only asks for, so silence it here
        # rather than train the user to ignore warnings.
        warnings.filterwarnings("ignore", category=CanUseToolShadowedWarning)

        return ClaudeAgentOptions(
            allowed_tools=allowed,
            permission_mode="default",
            resume=self._session_id,
            can_use_tool=self._can_use_tool if self._allow_actions else None,
            # Text arrives one content block at a time, which is progressive
            # enough. Token-level streaming means parsing raw stream events,
            # and that is not worth the risk for the gain here.
            include_partial_messages=False,
            system_prompt=(
                "Tu réponds dans une petite bulle sur le bureau de l'utilisateur. "
                "Réponds en français, de façon concise et directe. "
                "Si on te montre une capture d'écran, décris ce qui compte, "
                "pas chaque pixel."
            ),
            # Marks sessions Lutin started, so the hook bridge can tell them
            # apart from the user's own terminals and stay out of the way.
            env={"LUTIN_OWN_SESSION": "1"},
        )

    def _prompt(self, question: str, capture: Capture | None):
        """Build the SDK prompt: a bare string, or a stream carrying an image."""
        if capture is None:
            return question

        block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.standard_b64encode(capture.png).decode("ascii"),
            },
        }

        async def stream():
            yield {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [block, {"type": "text", "text": question}],
                },
            }

        return stream()

    async def _run_turn(self, question: str, capture: Capture | None) -> None:
        from claude_agent_sdk import (
            AssistantMessage,
            ResultMessage,
            TextBlock,
            ToolUseBlock,
            query,
        )

        pending_text: list[str] = []

        async for message in query(
            prompt=self._prompt(question, capture), options=self._options()
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        # Buffered, not emitted: if the turn turns out to be an
                        # error, this text is the raw SDK message and must not
                        # be shown as if it were Claude's answer.
                        pending_text.append(block.text)
                        self.chunk.emit(block.text)
                    elif isinstance(block, ToolUseBlock):
                        self.activity.emit(_describe(block.name, block.input))
            elif isinstance(message, ResultMessage):
                if message.session_id:
                    self._session_id = message.session_id
                if message.is_error:
                    # Wipe whatever the failed turn already streamed.
                    self.reset_answer.emit()
                    self.failed.emit(self._explain_result(message))
                    return
                self.finished.emit(_cost_line(message))

    def _explain_result(self, message) -> str:
        text = (message.result or "").strip()
        return self._explain(RuntimeError(text)) if text else "Claude a échoué."

    # -- permissions ------------------------------------------------------

    async def _can_use_tool(self, tool_name: str, tool_input: dict, context):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        signature = _signature(tool_name, tool_input)
        if signature in self._always:
            return PermissionResultAllow()

        request_id = next(self._ids)
        pending = _PendingPermission(asyncio.get_running_loop())
        self._pending[request_id] = pending

        self.permission_requested.emit(
            request_id,
            ToolRequest(tool=tool_name, detail=_detail(tool_name, tool_input)),
        )

        try:
            decision = await asyncio.wait_for(
                pending.future, timeout=self._permission_timeout
            )
        except TimeoutError:
            return PermissionResultDeny(message=_DENY_ON_TIMEOUT, interrupt=False)
        finally:
            self._pending.pop(request_id, None)

        if decision == "always":
            self._always.add(signature)
            return PermissionResultAllow()
        if decision == "allow":
            return PermissionResultAllow()
        return PermissionResultDeny(message="Refusé depuis Lutin.", interrupt=False)

    def answer_permission(self, request_id: int, decision: str) -> None:
        """Answer a pending request. Safe from the GUI thread."""
        pending = self._pending.get(request_id)
        if pending is not None:
            pending.answer(decision)

    @property
    def always_allowed(self) -> list[str]:
        return sorted(self._always)

    def forget_always(self) -> None:
        self._always.clear()


# ---------------------------------------------------------------------------
# Describing tool calls for humans
# ---------------------------------------------------------------------------


def _first_str(tool_input: dict, *keys: str) -> str:
    for key in keys:
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _detail(tool_name: str, tool_input: dict) -> str:
    """The body of the approval card: what exactly is about to happen."""
    detail = _first_str(
        tool_input, "command", "file_path", "path", "pattern", "url", "prompt"
    )
    if detail:
        return detail
    try:
        return json.dumps(tool_input, ensure_ascii=False, indent=2)[:2000]
    except (TypeError, ValueError):
        return str(tool_input)[:2000]


def _describe(tool_name: str, tool_input: dict) -> str:
    """One line for the activity feed."""
    target = _first_str(tool_input, "file_path", "path", "command", "pattern", "url")
    if not target:
        return tool_name
    if len(target) > 70:
        target = target[:69] + "…"
    return f"{tool_name} {target}"


def _signature(tool_name: str, tool_input: dict) -> str:
    """Key for an "always allow" rule.

    Deliberately coarse for paths (the tool plus the file) and exact for
    commands: allowing `npm test` forever must not also allow `npm publish`.
    """
    if tool_name == "Bash":
        return f"Bash:{_first_str(tool_input, 'command')}"
    return f"{tool_name}:{_first_str(tool_input, 'file_path', 'path', 'url')}"


def _cost_line(message) -> str:
    cost = getattr(message, "total_cost_usd", None)
    turns = getattr(message, "num_turns", None)
    parts = []
    if turns:
        parts.append(f"{turns} tour{'s' if turns > 1 else ''}")
    if cost:
        parts.append(f"${cost:.4f}")
    return " · ".join(parts) if parts else "Terminé."
