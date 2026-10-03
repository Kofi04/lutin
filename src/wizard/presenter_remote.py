"""The presenter for `--headless`: every visual becomes a protocol event.

The core creates no window here. What it would have shown goes to the Tauri
UI over the local WebSocket (ws_server.py), and what the user does there comes
back as commands, routed to the same app methods the Qt widgets call.

Two promises carry over from the Qt UI and are enforced here, in the core,
because the UI may be gone at any moment:

* silence is refusal: an approval nobody answers is denied at its timeout;
* nothing is sent without being seen: a capture reaches Claude only after a
  `capture.confirm` naming the exact capture the UI was shown.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import secrets
import sys
import threading
from collections import OrderedDict

from PySide6.QtCore import QObject, QRect, QTimer, Signal

from . import __version__, screens
from .assistant import selection as selection_actions
from .capture.cloak import RemoteCloak
from .overlay.scene import Highlight, Pointer
from .presenter import WINDOWS, Presenter
from .ws_server import UiServer

log = logging.getLogger(__name__)

#: The launcher puts the secret here. Read once, then removed from the
#: environment: every process the core starts (Claude Code, agents, the apps
#: of the launcher) would otherwise inherit it.
TOKEN_ENV = "WIZARD_UI_TOKEN"

#: Printed on stdout once the server listens, for the launcher to read.
READY_PREFIX = "WIZARD_READY "

#: Exit codes the launcher can tell apart.
EXIT_ALREADY_RUNNING = 3
EXIT_SERVER_FAILED = 4

#: Captures shown but not yet confirmed, or confirmed but not yet asked about.
_KEPT_CAPTURES = 5


class ParentWatch(QObject):
    """Quit when the launcher goes away.

    The launcher keeps our stdin open and never writes to it. When it exits,
    normally or by crashing, Windows closes the pipe and the read below ends:
    the core then shuts down cleanly instead of living on as an orphan that
    still holds the hotkeys and the single-instance lock.
    """

    gone = Signal()

    def __init__(self, stream=None) -> None:
        super().__init__()
        self._stream = stream if stream is not None else sys.stdin

    def start(self) -> bool:
        if self._stream is None:
            return False
        threading.Thread(
            target=self._wait, name="wizard-parent-watch", daemon=True
        ).start()
        return True

    def _wait(self) -> None:
        source = getattr(self._stream, "buffer", self._stream)
        try:
            while source.read(4096):
                pass  # nothing is ever sent; drain anything that is
        except (OSError, ValueError):
            pass
        # Emitted from this thread, delivered on the GUI thread (queued).
        self.gone.emit()


def take_token() -> tuple[str, bool]:
    """The token from the environment, or a fresh one. True if generated."""
    token = os.environ.pop(TOKEN_ENV, "")
    if token:
        return token, False
    return secrets.token_urlsafe(32), True


class ProtocolPresenter(Presenter):
    """Events out, commands in."""

    def __init__(self, token: str, announce_token: bool = False) -> None:
        self.server = UiServer(token, version=__version__)
        self._announce_token = announce_token
        self._token = token
        self._cloak = RemoteCloak(self.server.broadcast, lambda: self.server.clients)
        self.server.received.connect(self._on_message)
        self.server.client_ready.connect(self._send_state)
        self.server.client_gone.connect(self._cloak.forget)

        # What a window connecting late (or reconnecting) must be told.
        self._mood = "calm"
        self._connection = ("connecting", "")
        self._sessions: list[dict] = []
        self._quiet = False
        self._approval: dict | None = None
        self._approval_timer = QTimer()
        self._approval_timer.setSingleShot(True)
        self._approval_timer.timeout.connect(self._approval_timed_out)

        self._ids = itertools.count(1)
        self._previews: OrderedDict[str, object] = OrderedDict()
        self._attached: OrderedDict[str, object] = OrderedDict()
        self._selection_id: str | None = None
        self._selection_action = ""
        self._selection_replaces = False
        self._last_system: tuple | None = None

        self._handlers = {
            "ask": self._on_ask,
            "ask.cancel": lambda client, p: self.app.claude.cancel(),
            "approval.answer": self._on_approval_answer,
            "capture.start": self._on_capture_start,
            "capture.region": self._on_capture_region,
            "capture.file": lambda client, p: self.app._on_files_dropped([p["path"]]),
            "capture.confirm": self._on_capture_confirm,
            "capture.cancel": self._on_capture_cancel,
            "selection.pick": self._on_selection_pick,
            "selection.replace": self._on_selection_replace,
            "selection.copy": lambda client, p: self.app.clipboard.copy_to_clipboard(
                p["text"]
            ),
            "agent.start": lambda client, p: self.app._launch_agent(
                p["task"], p["folder"]
            ),
            "agent.stop": lambda client, p: self.app.agents.stop(p["agent_id"]),
            "session.dismiss": lambda client, p: self.app.sessions.forget(
                p["session_id"]
            ),
            "guide.active": lambda client, p: self.app._grab_escape(p["active"]),
            "guide.done": lambda client, p: self.guide_clear(),
            "cloak.ack": lambda client, p: self._cloak.ack(client, p["cloak_id"]),
            "action": self._on_action,
        }

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids)}"

    def _emit(self, type_: str, payload: dict | None = None) -> None:
        self.server.broadcast(type_, payload)

    # -- lifecycle --------------------------------------------------------

    def make_cloak(self):
        return self._cloak

    def report_already_running(self) -> int:
        print("Little Wizard is already running.", file=sys.stderr)
        return EXIT_ALREADY_RUNNING

    def preflight(self) -> int | None:
        if not self.server.start():
            print(f"UI server failed to listen: {self.server.error}", file=sys.stderr)
            return EXIT_SERVER_FAILED
        ready = {"port": self.server.port, "pid": os.getpid()}
        if self._announce_token:
            # Only when nobody handed us one (a manual run): whoever reads our
            # stdout started us, so it is the one party allowed to know it.
            ready["token"] = self._token
        if sys.stdout is not None:
            print(READY_PREFIX + json.dumps(ready), flush=True)
        return None

    def stop(self) -> None:
        self.server.stop()

    # -- incoming ---------------------------------------------------------

    def _on_message(self, client, message) -> None:
        handler = self._handlers.get(message.type)
        if handler is None:
            return
        try:
            handler(client, message.payload)
        except Exception as exc:  # one bad command must not take the core down
            log.exception("command %s failed", message.type)
            self.server.send(
                client,
                "error",
                {"error": "command_failed", "message": f"{message.type}: {exc}"},
                message.id,
            )

    def _send_state(self, client) -> None:
        send = self.server.send
        send(client, "mood", {"mood": self._mood})
        state, detail = self._connection
        send(client, "connection", {"state": state, "detail": detail})
        send(client, "sessions.update", {"sessions": self._sessions})
        if self._quiet:
            send(client, "quiet", {"on": True})
        if self._approval is not None:
            remaining = max(1, round(self._approval_timer.remainingTime() / 1000))
            send(
                client,
                "approval.request",
                {**self._approval, "timeout_seconds": remaining},
            )

    def _on_ask(self, client, payload) -> None:
        capture = None
        capture_id = payload.get("capture_id")
        if capture_id:
            capture = self._attached.pop(capture_id, None)
            if capture is None:
                # A capture the user never confirmed, or one already sent.
                raise ValueError(f"unknown capture {capture_id}")
        self.app._on_asked(payload["text"], capture)

    def _on_action(self, client, payload) -> None:
        app = self.app
        {
            "ask": lambda: app._open_ask(None),
            "capture.region": lambda: app._start_region("ask"),
            "capture.screen": app.capture.capture_active_screen,
            "capture.text": app._start_text_copy,
            "selection": app._start_selection,
            "conversation.reset": app._reset_claude,
            "config.reload": app.reload_config,
            "config.open_folder": app._open_config_folder,
            "quit": app.shutdown,
        }[payload["name"]]()

    # -- status -----------------------------------------------------------

    def notify(self, title: str, body: str, kind: str) -> None:
        self._emit("toast", {"title": title, "body": body, "kind": kind})

    def set_mood(self, mood) -> None:
        if mood.value != self._mood:
            self._mood = mood.value
            self._emit("mood", {"mood": self._mood})

    def set_connection(self, state: str, detail: str) -> None:
        self._connection = (state, detail)
        self._emit("connection", {"state": state, "detail": detail})

    def update_system(self, sample, mood) -> None:
        # Sent only when a rounded value moves: a sample every few seconds
        # with the same numbers is traffic for nothing.
        key = (round(sample.cpu), round(sample.ram), sample.battery_percent, sample.on_ac)
        if key == self._last_system:
            return
        self._last_system = key
        payload = {"cpu": float(sample.cpu), "memory": float(sample.ram)}
        if sample.battery_percent is not None:
            payload["battery"] = int(sample.battery_percent)
            payload["charging"] = bool(sample.on_ac)
        self._emit("system", payload)

    def set_quiet(self, quiet: bool) -> None:
        self._quiet = quiet
        self._emit("quiet", {"on": quiet})

    def toggle_avatar(self) -> None:
        self._emit("avatar.toggle")

    # -- the panel --------------------------------------------------------

    def open_ask(
        self, capture=None, context: str | None = None, status: str = ""
    ) -> None:
        payload: dict = {"state": "bar" if context is None else "answer"}
        if capture is not None:
            capture_id = self._remember(self._attached, capture)
            payload["capture"] = {
                "capture_id": capture_id,
                "label": capture.label,
                "width": capture.width,
                "height": capture.height,
            }
        if context is not None:
            payload["context"] = context
        if status:
            payload["status"] = status
        self._emit("panel.open", payload)

    def reset_conversation(self) -> None:
        self._attached.clear()
        self._emit("stream.reset")

    def answer_started(self) -> None:
        self._emit("stream.start")

    def answer_chunk(self, text: str) -> None:
        self._emit("stream.chunk", {"text": text})

    def answer_status(self, text: str) -> None:
        self._emit("stream.status", {"text": text})

    def answer_reset(self) -> None:
        self._emit("stream.reset")

    def answer_finished(self, status: str) -> None:
        self._emit("stream.end", {"status": status})

    def answer_failed(self, message: str) -> None:
        self._emit("stream.error", {"message": message})

    # -- approvals --------------------------------------------------------

    def ask_approval(self, request, timeout_seconds: int) -> None:
        self._approval = {
            "request_id": self._next_id("r"),
            "tool": request.tool,
            "detail": request.detail,
            "project": request.project,
        }
        timeout = max(1, int(timeout_seconds))
        self._approval_timer.start(timeout * 1000)
        self._emit("approval.request", {**self._approval, "timeout_seconds": timeout})

    def _on_approval_answer(self, client, payload) -> None:
        if (
            self._approval is None
            or payload["request_id"] != self._approval["request_id"]
        ):
            return  # answered elsewhere already, or timed out
        self._settle_approval(payload["decision"])

    def _approval_timed_out(self) -> None:
        if self._approval is not None:
            # Silence is not consent.
            self._settle_approval("deny")

    def _settle_approval(self, decision: str) -> None:
        request_id = self._approval["request_id"]
        self._approval = None
        self._approval_timer.stop()
        # Every window drops its card, including those that did not answer.
        self._emit("approval.cancel", {"request_id": request_id})
        self.app._on_approval_decided(decision)

    # -- captures ---------------------------------------------------------

    def _remember(self, store: OrderedDict, capture) -> str:
        capture_id = self._next_id("k")
        store[capture_id] = capture
        while len(store) > _KEPT_CAPTURES:
            store.popitem(last=False)
        return capture_id

    def select_region(self, mode: str) -> None:
        self._emit("capture.select", {"mode": mode})

    def _on_capture_start(self, client, payload) -> None:
        mode = payload["mode"]
        if mode == "screen":
            self.app.capture.capture_active_screen()
        elif mode == "text":
            self.app._start_text_copy()
        else:
            self.app._start_region("ask")

    def _on_capture_region(self, client, payload) -> None:
        x, y = screens.from_screen(
            payload["screen_id"], payload["x"], payload["y"], screens.current_screens()
        )
        rect = QRect(
            round(x), round(y), round(payload["width"]), round(payload["height"])
        )
        self.app.capture.grab_region(rect, for_text=payload["mode"] == "text")

    def preview_capture(self, capture) -> None:
        capture_id = self._remember(self._previews, capture)
        self._emit(
            "capture.preview",
            {
                "capture_id": capture_id,
                "kind": capture.kind.value,
                "label": capture.label,
                "width": capture.width,
                "height": capture.height,
                "tokens": capture.estimated_tokens,
                "png_base64": capture.base64_png(),
            },
        )

    def _on_capture_confirm(self, client, payload) -> None:
        capture = self._previews.pop(payload["capture_id"], None)
        if capture is None:
            raise ValueError(f"unknown capture {payload['capture_id']}")
        self.app._on_capture_confirmed(capture)

    def _on_capture_cancel(self, client, payload) -> None:
        capture_id = payload.get("capture_id")
        if capture_id:
            self._previews.pop(capture_id, None)

    # -- selection --------------------------------------------------------

    def choose_selection_action(self, text: str) -> None:
        self._selection_id = self._next_id("s")
        preview = " ".join(text.split())
        self._emit(
            "selection.menu",
            {
                "selection_id": self._selection_id,
                "preview": preview[:200],
                "actions": [
                    {"key": a.key, "label": a.label, "replaces": a.replaces}
                    for a in selection_actions.ACTIONS
                ],
            },
        )

    def _on_selection_pick(self, client, payload) -> None:
        if payload["selection_id"] != self._selection_id:
            return
        self.app._on_selection_action(payload["action"])

    def _on_selection_replace(self, client, payload) -> None:
        if payload["selection_id"] == self._selection_id:
            self.app._replace_selection(payload["text"])

    def _selection_event(self, status: str, text: str) -> None:
        if self._selection_id is None:
            return
        self._emit(
            "selection.result",
            {
                "selection_id": self._selection_id,
                "action": self._selection_action,
                "status": status,
                "text": text,
                "replaces": self._selection_replaces,
            },
        )

    def selection_started(self, chosen, text: str) -> None:
        self._selection_action = chosen.key
        self._selection_replaces = chosen.replaces
        self._selection_event("working", "")

    def selection_done(self, text: str) -> None:
        self._selection_event("done", text)

    def selection_failed(self, message: str) -> None:
        self._selection_event("error", message)

    # -- sessions ---------------------------------------------------------

    def update_sessions(self, sessions: list) -> None:
        agents = {agent.key: agent for agent in self.app.agents.agents}
        self._sessions = []
        for session in sessions:
            entry = {
                "id": session.session_id,
                "label": session.label,
                "colour": session.colour,
                "state": session.state,
                "last_action": session.last_action,
            }
            agent = agents.get(session.session_id)
            if agent is not None:
                entry["agent_id"] = agent.id
                entry["running"] = agent.running
                entry["report"] = agent.report
            self._sessions.append(entry)
        self._emit("sessions.update", {"sessions": self._sessions})

    # -- the guide --------------------------------------------------------

    # Escape is claimed here, by the one side that knows the whole picture.
    # Each overlay window only sees its own screen: when the guide moved from
    # one screen to the other, one sent "inactive" and the other "active", in
    # no guaranteed order, and Escape could be let go with a guide on screen.

    def guide_point(self, x: float, y: float, label: str) -> None:
        self._emit("guide.point", _point(x, y, label))
        self.app._grab_escape(True)

    def guide_highlight(
        self, left: float, top: float, width: float, height: float, label: str, shape: str
    ) -> None:
        self._emit("guide.highlight", _box(left, top, width, height, label, shape))
        self.app._grab_escape(True)

    def guide_steps(self, steps: list) -> None:
        payload = []
        for step in steps:
            target = None
            if isinstance(step.target, Pointer):
                target = {
                    "kind": "point",
                    **_point(step.target.x, step.target.y, step.target.label),
                }
            elif isinstance(step.target, Highlight):
                box = step.target
                target = {
                    "kind": "highlight",
                    **_box(
                        box.left, box.top, box.width, box.height, box.label, box.shape
                    ),
                }
            payload.append({"text": step.text, "target": target})
        self._emit("guide.steps", {"steps": payload})
        self.app._grab_escape(True)

    def guide_clear(self) -> None:
        self._emit("guide.clear")
        self.app._grab_escape(False)

    # -- windows not ported yet -------------------------------------------

    def open_window(self, name: str) -> None:
        if name in WINDOWS:
            self._emit("window.open", {"name": name})

    def confirm_hooks(self, plan, installing: bool) -> bool:
        # Writing settings.json needs the diff shown first, and that window
        # does not exist on the Tauri side yet: ask for it, change nothing.
        self.open_window("hooks.install" if installing else "hooks.uninstall")
        return False


def _point(x: float, y: float, label: str) -> dict:
    screen_id, sx, sy = screens.to_screen(x, y, screens.current_screens())
    return {"screen_id": screen_id, "x": sx, "y": sy, "label": label}


def _box(
    left: float, top: float, width: float, height: float, label: str, shape: str
) -> dict:
    # Placed by its centre: a box straddling two monitors belongs to the one
    # holding most of it.
    screen_id, cx, cy = screens.to_screen(
        left + width / 2, top + height / 2, screens.current_screens()
    )
    return {
        "screen_id": screen_id,
        "x": cx - width / 2,
        "y": cy - height / 2,
        "width": width,
        "height": height,
        "label": label,
        "shape": shape if shape in ("rect", "ellipse") else "rect",
    }
