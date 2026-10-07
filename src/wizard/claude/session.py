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
from ..overlay.tools import PROMPT_HINT as OVERLAY_HINT
from ..overlay.tools import QUALIFIED as OVERLAY_TOOLS
from ..overlay.tools import SERVER as OVERLAY_SERVER
from ..overlay.tools import OverlayBridge
from ..overlay.tools import build_server as build_overlay_server
from .tool_request import ToolRequest

#: Tools Claude may use without ever asking. Read-only, no side effects.
READ_ONLY_TOOLS = ["Read", "Glob", "Grep", "WebFetch", "WebSearch"]

_DENY_ON_TIMEOUT = "Aucune réponse de Little Wizard : action refusée par sécurité."

#: Connection states, as plain strings so the UI never imports this module
#: just to name one.
OFFLINE = "offline"
CONNECTING = "connecting"
READY = "ready"

#: Reconnect backoff, in seconds. Capped so a long outage settles into one
#: attempt a minute rather than climbing forever.
_BACKOFF_START = 1.0
_BACKOFF_MAX = 60.0


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
    #: (state, detail) - OFFLINE / CONNECTING / READY, plus a reason when there
    #: is one worth giving the user.
    connection_changed = Signal(str, str)
    #: (job id, text) for a one-shot job; see `run_oneshot`.
    oneshot_done = Signal(int, str)
    #: (job id, message fit for the user).
    oneshot_failed = Signal(int, str)

    def __init__(
        self,
        permission_timeout: int = 110,
        allow_actions: bool = True,
        auto_approve_read_only: bool = True,
        prewarm: bool = True,
        cwd: str | None = None,
        system_prompt: str | None = None,
        overlay: bool = True,
        memory: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        #: Working folder; None is wherever the app was started from.
        self._cwd = cwd
        #: Replaces the default "answer in a bubble" instructions (agents).
        self._base_prompt = system_prompt
        #: Whether this session gets the on-screen pointing tools.
        self._with_overlay = overlay
        #: The user's memory.md, appended to the system prompt. Taken in the
        #: constructor because prewarm connects from here: set afterwards, it
        #: could arrive after the first connection's prompt was built.
        self._memory = memory
        self._permission_timeout = permission_timeout
        self._allow_actions = allow_actions
        self._auto_approve_read_only = auto_approve_read_only

        self._session_id: str | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, _PendingPermission] = {}
        self._always: set[str] = set()
        self._task: asyncio.Task | None = None

        self._client = None  # ClaudeSDKClient, once connected

        #: Where the last screen capture came from. The overlay tools map
        #: Claude's coordinates against this, so it must be the capture
        #: Claude is actually looking at. None until one is sent, and after a
        #: dropped file, which has no place on the screen.
        self._frame = None
        self.overlay = OverlayBridge(self)
        self._state = OFFLINE
        self._connect_lock: asyncio.Lock | None = None
        self._retry_at: float = 0.0
        self._backoff = _BACKOFF_START
        self._closing = False

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="wizard-claude", daemon=True
        )
        self._thread.start()

        #: The prewarm attempt, so shutdown can cancel one still in flight.
        self._connect_task: asyncio.Future | None = None
        if prewarm:
            # Connecting spawns the Claude Code CLI and negotiates a session,
            # which takes seconds. Doing it now, on the worker thread, is the
            # whole point: the first question should not pay for it.
            self._connect_task = asyncio.run_coroutine_threadsafe(
                self._ensure_client(), self._loop
            )

    # -- connection -------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    def reconnect(self) -> None:
        """Try again now, whatever the backoff says. Safe from the GUI thread."""
        self._retry_at = 0.0
        self._backoff = _BACKOFF_START
        asyncio.run_coroutine_threadsafe(self._ensure_client(), self._loop)

    def _set_state(self, state: str, detail: str = "") -> None:
        if state == self._state:
            return
        self._state = state
        self.connection_changed.emit(state, detail)

    async def _ensure_client(self):
        """Return a live client, connecting if needed. One attempt at a time."""
        if self._closing:
            return None
        if self._client is not None:
            return self._client

        # The lock is built here rather than in __init__ because an asyncio.Lock
        # binds to the running loop, and __init__ runs on the GUI thread.
        if self._connect_lock is None:
            self._connect_lock = asyncio.Lock()

        async with self._connect_lock:
            if self._client is not None or self._closing:
                return self._client
            if self._loop.time() < self._retry_at:
                return None
            return await self._connect()

    async def _connect(self):
        from claude_agent_sdk import ClaudeSDKClient

        self._set_state(CONNECTING)
        client = ClaudeSDKClient(options=self._options())
        try:
            await client.connect()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await _quietly_disconnect(client)
            self._note_failure(exc)
            return None

        if self._closing:
            # Shutdown started while the handshake was in progress. Close
            # the client we just opened rather than publishing it.
            await _quietly_disconnect(client)
            return None

        self._client = client
        self._backoff = _BACKOFF_START
        self._retry_at = 0.0
        self._set_state(READY)
        return client

    def _note_failure(self, exc: Exception) -> None:
        detail = self._explain(exc)
        if _is_auth_problem(exc):
            # Retrying cannot fix a missing login, and each attempt spawns a
            # CLI process. Wait for the user to act; asking a question also
            # retries, so they are never stuck.
            self._retry_at = float("inf")
        else:
            self._retry_at = self._loop.time() + self._backoff
            self._backoff = min(self._backoff * 2, _BACKOFF_MAX)
        self._set_state(OFFLINE, detail)

    async def _drop_client(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await _quietly_disconnect(client)

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
        self._closing = True
        # A prewarm still in flight would otherwise finish after we stop
        # looking, set _client, and leave a CLI subprocess running with
        # nobody left to disconnect it.
        connecting = self._connect_task
        if connecting is not None and not connecting.done():
            connecting.cancel()
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
        await self._drop_client()
        await asyncio.sleep(0.15)

    @property
    def session_id(self) -> str | None:
        """The Claude Code session being continued, once one exists."""
        return self._session_id

    def reset(self) -> None:
        """Start a fresh conversation.

        The conversation lives inside the connected client, so a new one
        means a new connection; clearing the id alone would keep talking to
        the same session.
        """
        self._session_id = None
        self._always.clear()
        self._frame = None
        asyncio.run_coroutine_threadsafe(self._restart(), self._loop)

    def run_oneshot(self, job_id: int, prompt: str, system_prompt: str) -> None:
        """Ask one thing outside the conversation, with no tools. GUI-safe.

        Runs beside a turn in progress rather than queueing behind it: it is
        a separate Claude Code session and shares nothing with this one.
        """
        asyncio.run_coroutine_threadsafe(
            self._oneshot(job_id, prompt, system_prompt), self._loop
        )

    async def _oneshot(self, job_id: int, prompt: str, system_prompt: str) -> None:
        from .oneshot import ask_once

        try:
            text = await ask_once(prompt, system_prompt)
        except Exception as exc:  # the SDK raises a wide range of errors
            self.oneshot_failed.emit(job_id, self._explain(exc))
        else:
            self.oneshot_done.emit(job_id, text)

    def resume(self, session_id: str) -> None:
        """Continue an earlier conversation, picked from the history.

        Same mechanics as `reset`, but reconnecting with `resume=` so Claude
        Code reloads that session's context instead of starting blank. The
        screenshot frame is dropped: the arrows must never be aimed through an
        image from a conversation Claude is no longer looking at.
        """
        self._session_id = session_id
        self._always.clear()
        self._frame = None
        asyncio.run_coroutine_threadsafe(self._restart(), self._loop)

    async def _restart(self) -> None:
        await self._drop_client()
        self._set_state(OFFLINE)
        self._retry_at = 0.0
        self._backoff = _BACKOFF_START
        await self._ensure_client()

    # -- asking -----------------------------------------------------------

    def ask(self, question: str, capture: Capture | None = None) -> None:
        """Send a question (optionally with an image). Safe from the GUI thread."""
        if self._task is not None and not self._task.done():
            self.failed.emit("Une question est déjà en cours.")
            return
        asyncio.run_coroutine_threadsafe(self._start(question, capture), self._loop)

    def cancel(self) -> None:
        """Stop the turn in flight, keeping the connection.

        The client is long-lived now, so cancelling the task alone would
        leave the CLI still working on the other side of the pipe. The SDK
        interrupt is what actually stops it.
        """
        task = self._task
        if task is None or task.done():
            return
        asyncio.run_coroutine_threadsafe(self._interrupt(), self._loop)

    async def _interrupt(self) -> None:
        client = self._client
        if client is not None:
            with contextlib.suppress(Exception):
                await client.interrupt()
        task = self._task
        if task is not None and not task.done():
            task.cancel()

    async def _start(self, question: str, capture: Capture | None) -> None:
        self._task = asyncio.current_task()
        try:
            await self._run_turn(question, capture)
        except asyncio.CancelledError:
            self.finished.emit("Interrompu.")
        except Exception as exc:  # the SDK raises a wide range of errors
            # The pipe may be gone; keeping the client would fail every
            # later question the same way, with no path back.
            await self._drop_client()
            self._set_state(OFFLINE, self._explain(exc))
            self.failed.emit(self._explain(exc))

    def _explain(self, exc: Exception) -> str:
        text = str(exc)
        if _is_auth_problem(exc):
            return AUTH_HINT
        return text[:400]

    def _offline_message(self) -> str:
        """Why a question could not be sent, in the user's words."""
        if self._retry_at == float("inf"):
            return AUTH_HINT
        return (
            "Claude n'est pas joignable pour le moment. "
            "Nouvelle tentative automatique dans quelques secondes."
        )

    def _options(self):
        import warnings

        from claude_agent_sdk import ClaudeAgentOptions
        from claude_agent_sdk.types import CanUseToolShadowedWarning

        # `allowed_tools` pre-approves; it does not restrict. Anything outside
        # the list still reaches `can_use_tool`, which is where the user decides.
        allowed = list(READ_ONLY_TOOLS) if self._auto_approve_read_only else []
        # Drawing on the screen cannot change anything, so asking permission
        # to point at a button would be absurd.
        if self._with_overlay:
            allowed += list(OVERLAY_TOOLS)
        # The SDK warns that `allowed_tools` shadows `can_use_tool`. That is
        # exactly what auto_approve_read_only asks for, so silence it here
        # rather than train the user to ignore warnings.
        warnings.filterwarnings("ignore", category=CanUseToolShadowedWarning)

        return ClaudeAgentOptions(
            allowed_tools=allowed,
            permission_mode="default",
            # Only meaningful when we are reconnecting to a conversation
            # that already existed; None starts a new one.
            resume=self._session_id,
            can_use_tool=self._can_use_tool if self._allow_actions else None,
            # Text arrives one content block at a time, which is progressive
            # enough. Token-level streaming means parsing raw stream events,
            # and that is not worth the risk for the gain here.
            include_partial_messages=False,
            mcp_servers=(
                {OVERLAY_SERVER: build_overlay_server(self.overlay, lambda: self._frame)}
                if self._with_overlay
                else {}
            ),
            system_prompt=self._system_prompt(),
            cwd=self._cwd,
            # Marks sessions Little Wizard started, so the hook bridge can tell them
            # apart from the user's own terminals and stay out of the way.
            env={"WIZARD_OWN_SESSION": "1"},
        )

    def _system_prompt(self) -> str:
        base = self._base_prompt or (
            "Tu réponds dans une petite bulle sur le bureau de l'utilisateur. "
            "Réponds en français, de façon concise et directe. "
            "Si on te montre une capture d'écran, décris ce qui compte, "
            "pas chaque pixel. " + OVERLAY_HINT
        )
        if not self._memory.strip():
            return base
        return (
            f"{base}\n\n"
            "Ce que l'utilisateur t'a demandé de retenir sur lui (sa mémoire, "
            "qu'il a écrite lui-même) :\n"
            f"<memoire>\n{self._memory.strip()}\n</memoire>"
        )

    def set_memory(self, text: str) -> None:
        """Change what Claude knows about the user. GUI-safe.

        The system prompt is fixed per connection, so taking a new memory
        into account means reconnecting — onto the same session, so the
        conversation in progress is kept.
        """
        if text == self._memory:
            return
        self._memory = text
        if self._client is not None:
            asyncio.run_coroutine_threadsafe(self._restart(), self._loop)

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
        )

        client = await self._ensure_client()
        if client is None:
            self.failed.emit(self._offline_message())
            return

        if capture is not None:
            # A new image replaces the old one as the frame of reference; a
            # dropped file clears it, so the tools refuse rather than point
            # into a screenshot Claude is no longer looking at.
            self._frame = capture.frame

        pending_text: list[str] = []

        await client.query(self._prompt(question, capture))
        async for message in client.receive_response():
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
                    reason = self._explain_result(message)
                    # Connecting succeeds even with no usable login: the CLI
                    # starts and negotiates fine, and only the first real query
                    # fails. Reporting "ready" after that would leave the staff
                    # lit and the user guessing, so the turn's verdict, not the
                    # handshake's, decides the state.
                    if reason == AUTH_HINT:
                        self._retry_at = float("inf")
                        self._set_state(OFFLINE, reason)
                    self.failed.emit(reason)
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
        return PermissionResultDeny(
            message="Refusé depuis Little Wizard.", interrupt=False
        )

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


AUTH_HINT = (
    "Claude Code n'est pas connecté. Lance `claude auth login` "
    "dans un terminal, puis réessaie."
)


def _is_auth_problem(exc: Exception) -> bool:
    """Whether retrying could possibly help. A missing login it cannot."""
    text = str(exc).lower()
    return "oauth" in text or "authenticate" in text or "not logged in" in text


async def _quietly_disconnect(client) -> None:
    """Close a client we are giving up on. Failing to close is not news."""
    with contextlib.suppress(Exception):
        await client.disconnect()


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
