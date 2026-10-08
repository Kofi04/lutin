"""The core without windows, driven over the WebSocket as the Tauri UI will.

The whole app is built, with the protocol presenter, and a real client talks
to it. What is checked is what must survive the move to Tauri: no window of
ours, silence is refusal, nothing sent without being seen, captures without
our own windows in them.
"""

from __future__ import annotations

import json
import os

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from wizard.capture.prepare import CaptureKind, prepare
from wizard.claude.tool_request import ToolRequest
from wizard.mood import Mood
from wizard.presenter_remote import (
    READY_PREFIX,
    TOKEN_ENV,
    ProtocolPresenter,
    take_token,
)

from .ws_client import TestClient, spin_until

TOKEN = "headless-test-token"


class FakeOwner:
    """An agent session: it only has to receive the decision."""

    def __init__(self):
        self.answers = []

    def answer_permission(self, request_id, decision):
        self.answers.append((request_id, decision))


@pytest.fixture
def core(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config = tmp_path / "LittleWizard" / "config.toml"
    config.parent.mkdir(parents=True)
    # No prewarm: a test must never start the real Claude Code CLI.
    config.write_text("[claude]\nprewarm = false\n", encoding="utf-8")
    from wizard.app import AvatarApp

    before = set(QApplication.topLevelWidgets())
    presenter = ProtocolPresenter(TOKEN)
    app = AvatarApp([], presenter)
    app._auth_checked = True  # no `claude auth status` from a test
    # Escape is a global hotkey: a test must not steal it from the desktop.
    app._grab_escape = lambda active: escapes.append(active)
    escapes: list = []
    app.test_escapes = escapes
    assert presenter.preflight() is None
    app.test_new_widgets = set(QApplication.topLevelWidgets()) - before
    app.test_stdout = capsys.readouterr().out
    clients: list[TestClient] = []

    def connect(role="dev"):
        client = TestClient(presenter.server.port)
        clients.append(client)
        assert client.hello(TOKEN, role)
        return client

    app.test_connect = connect
    yield app
    for client in clients:
        client.close()
    presenter.stop()
    app.hotkeys.unregister_all()
    app.claude.shutdown()
    app.storage.close()


def _capture():
    image = QImage(64, 32, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    return prepare(image, CaptureKind.REGION, "Zone 64×32", region=(0, 0, 64, 32))


# -- no windows ---------------------------------------------------------------


def test_headless_core_shows_no_window(core):
    visible = [w for w in core.test_new_widgets if w.isVisible()]
    assert visible == []
    # Only the hidden owner window of the global hotkeys may exist at all.
    names = {type(w).__name__ for w in core.test_new_widgets}
    assert names <= {"QWidget"}


def test_ready_line_gives_the_port_but_not_a_token_it_was_handed(core):
    line = next(
        line for line in core.test_stdout.splitlines() if line.startswith(READY_PREFIX)
    )
    ready = json.loads(line[len(READY_PREFIX) :])
    assert ready["port"] == core.ui.server.port
    assert "token" not in ready
    assert TOKEN not in core.test_stdout


def test_token_is_taken_out_of_the_environment(monkeypatch):
    """Claude Code, agents and launched apps would otherwise inherit it."""
    monkeypatch.setenv(TOKEN_ENV, "from-the-launcher")
    assert take_token() == ("from-the-launcher", False)
    assert TOKEN_ENV not in os.environ


def test_without_a_token_one_is_generated():
    token, generated = take_token()
    assert generated and len(token) >= 32


# -- state on connection ------------------------------------------------------


def test_a_new_window_is_told_the_current_state(core):
    core.ui.set_mood(Mood.WORKING)
    core.ui.set_connection("online", "")
    client = core.test_connect()
    assert client.wait_for("mood").payload == {"mood": "working"}
    assert client.wait_for("connection").payload == {"state": "online", "detail": ""}
    assert client.wait_for("sessions.update").payload == {"sessions": []}


def test_toasts_go_to_every_window(core):
    avatar, panel = core.test_connect("avatar"), core.test_connect("panel")
    core.notify("Titre", "Corps", kind="success")
    for client in (avatar, panel):
        toast = client.wait_for("toast")
        assert toast.payload == {"title": "Titre", "body": "Corps", "kind": "success"}


# -- approvals ------------------------------------------------------------------


def test_an_approval_answered_in_the_ui_reaches_its_owner(core):
    client = core.test_connect()
    owner = FakeOwner()
    core._approval_queue.append((owner, 7, ToolRequest("Bash", "ls", "demo")))
    core._show_next_approval()

    request = client.wait_for("approval.request")
    assert request.payload["tool"] == "Bash"
    assert request.payload["detail"] == "ls"
    client.send(
        "approval.answer",
        {"request_id": request.payload["request_id"], "decision": "allow"},
    )

    assert spin_until(lambda: owner.answers == [(7, "allow")])
    assert client.wait_for("approval.cancel") is not None


def test_silence_is_refusal(core):
    client = core.test_connect()
    owner = FakeOwner()
    # What _show_next_approval does, with a one-second timeout instead of 110.
    core._approval_current, core._approval_owner = 1, owner
    core.ui.ask_approval(ToolRequest("Edit", "a.py"), timeout_seconds=1)

    assert client.wait_for("approval.request") is not None
    assert spin_until(lambda: owner.answers == [(1, "deny")], timeout_ms=2500)


def test_a_stale_answer_is_ignored(core):
    client = core.test_connect()
    owner = FakeOwner()
    core._approval_queue.append((owner, 1, ToolRequest("Bash", "rm -rf build")))
    core._show_next_approval()
    assert client.wait_for("approval.request") is not None

    client.send("approval.answer", {"request_id": "r999", "decision": "allow"})
    client.send("ping", id="sync")
    assert client.wait_for("reply") is not None
    assert owner.answers == []


def test_a_window_connecting_late_still_sees_the_pending_request(core):
    owner = FakeOwner()
    core._approval_queue.append((owner, 1, ToolRequest("Bash", "ls")))
    core._show_next_approval()

    late = core.test_connect("panel")
    request = late.wait_for("approval.request")
    assert request is not None
    assert 1 <= request.payload["timeout_seconds"] <= 110


# -- captures -----------------------------------------------------------------


def test_a_capture_is_shown_then_sent_only_once_confirmed(core):
    asked = []
    core._on_asked = lambda text, capture: asked.append((text, capture))
    client = core.test_connect()

    core.capture.captured.emit(_capture())
    preview = client.wait_for("capture.preview")
    assert preview.payload["width"] == 64
    assert preview.payload["png_base64"]
    capture_id = preview.payload["capture_id"]

    # Asking about it before confirming it is refused.
    client.send("ask", {"text": "Et ça ?", "capture_id": capture_id})
    assert client.wait_for("error") is not None
    assert asked == []

    client.send("capture.confirm", {"capture_id": capture_id})
    opened = client.wait_for("panel.open")
    attached = opened.payload["capture"]["capture_id"]
    client.send("ask", {"text": "Et ça ?", "capture_id": attached})

    assert spin_until(lambda: asked)
    assert asked[0][0] == "Et ça ?"
    assert asked[0][1].label == "Zone 64×32"


def test_a_cancelled_capture_cannot_be_confirmed(core):
    client = core.test_connect()
    core.capture.captured.emit(_capture())
    capture_id = client.wait_for("capture.preview").payload["capture_id"]

    client.send("capture.cancel", {"capture_id": capture_id})
    client.send("capture.confirm", {"capture_id": capture_id})

    error = client.wait_for("error")
    assert error.payload["error"] == "command_failed"
    assert client.of_type("panel.open") == []


def test_screen_grab_waits_for_the_windows_to_hide(core):
    client = core.test_connect("avatar")
    client.send("capture.start", {"mode": "screen"})

    hide = client.wait_for("cloak.hide")
    assert hide is not None
    assert client.of_type("cloak.show") == []
    client.send("cloak.ack", {"cloak_id": hide.payload["cloak_id"]})

    show = client.wait_for("cloak.show")
    assert show.payload == hide.payload


def test_a_window_that_does_not_hide_cancels_the_grab(core):
    client = core.test_connect("avatar")
    client.send("capture.start", {"mode": "screen"})
    assert client.wait_for("cloak.hide") is not None

    toast = client.wait_for("toast", timeout_ms=2000)
    assert toast is not None
    assert "annulée" in toast.payload["body"]
    assert client.of_type("capture.preview") == []


def test_region_selection_is_asked_of_the_ui(core):
    client = core.test_connect("overlay")
    client.send("action", {"name": "capture.region"})
    assert client.wait_for("capture.select").payload == {"mode": "ask"}


def test_escape_cancels_a_selection_and_lets_escape_go(core):
    client = core.test_connect("overlay")
    client.send("action", {"name": "capture.region"})
    client.wait_for("capture.select")
    assert core.test_escapes[-1] is True  # held while the veils are up

    core.ui.on_escape()

    assert client.wait_for("capture.select.end").payload == {}
    assert core.test_escapes[-1] is False


def test_a_drawn_rectangle_ends_the_selection_before_the_grab(core):
    grabbed = []
    core.capture.grab_region = lambda rect, for_text=False: grabbed.append(
        (rect.width(), rect.height(), for_text)
    )
    client = core.test_connect("overlay")
    client.send("action", {"name": "capture.text"})
    mode = client.wait_for("capture.select").payload["mode"]
    from wizard import screens

    screen_id = screens.current_screens()[0].id
    client.send(
        "capture.region",
        {
            "mode": mode,
            "screen_id": screen_id,
            "x": 10,
            "y": 20,
            "width": 300,
            "height": 200,
        },
    )
    client.wait_for("capture.select.end")
    spin_until(lambda: grabbed)
    assert grabbed == [(300, 200, True)]
    assert core.test_escapes[-1] is False


# -- selection, guide, actions -----------------------------------------------


def test_selection_menu_and_result(core):
    jobs = []
    core._run_job = lambda purpose, prompt, system: jobs.append(purpose)
    client = core.test_connect("panel")

    core._on_selection_grabbed("Bonjour   le\nmonde", 0)
    menu = client.wait_for("selection.menu")
    assert menu.payload["preview"] == "Bonjour le monde"
    keys = [action["key"] for action in menu.payload["actions"]]
    assert "translate_en" in keys

    client.send(
        "selection.pick",
        {"selection_id": menu.payload["selection_id"], "action": "translate_en"},
    )
    working = client.wait_for("selection.result")
    assert working.payload["status"] == "working"
    assert spin_until(lambda: jobs)

    core.ui.selection_done("Hello world")
    done = client.wait_for("selection.result", count=2)
    assert done.payload["status"] == "done"
    assert done.payload["text"] == "Hello world"


def test_guide_point_is_sent_relative_to_its_screen(core):
    from wizard import screens

    client = core.test_connect("overlay")
    core.claude.overlay.point_requested.emit(40.0, 30.0, "ici")

    point = client.wait_for("guide.point")
    expected = screens.to_screen(40.0, 30.0, screens.current_screens())
    assert (
        point.payload["screen_id"],
        point.payload["x"],
        point.payload["y"],
    ) == expected
    assert point.payload["label"] == "ici"


def test_the_core_holds_escape_while_a_guide_is_shown(core):
    """Not the overlays: each sees one screen, and when the guide moved from
    one to the other their "inactive" and "active" raced each other."""
    client = core.test_connect("overlay")
    core.claude.overlay.point_requested.emit(40.0, 30.0, "ici")
    core.claude.overlay.highlight_requested.emit(10.0, 10.0, 50.0, 20.0, "là", "rect")
    assert core.test_escapes == [True, True]

    core.claude.overlay.clear_requested.emit()
    assert core.test_escapes[-1] is False
    assert client.wait_for("guide.clear") is not None


def test_guide_done_from_the_ui_clears_every_screen(core):
    avatar, overlay = core.test_connect("avatar"), core.test_connect("overlay")
    core.claude.overlay.point_requested.emit(40.0, 30.0, "ici")
    overlay.send("guide.done")

    assert avatar.wait_for("guide.clear") is not None
    assert core.test_escapes[-1] is False


def test_guide_activity_claims_and_releases_escape(core):
    client = core.test_connect("overlay")
    client.send("guide.active", {"active": True})
    client.send("guide.active", {"active": False})
    assert spin_until(lambda: core.test_escapes == [True, False])


def test_windows_are_requested_from_the_ui(core):
    client = core.test_connect()
    core._open_settings()
    assert client.wait_for("window.open").payload == {"name": "settings"}


def test_hooks_are_never_written_without_the_diff_window(core, monkeypatch):
    from wizard.bridge import installer

    written = []
    monkeypatch.setattr(installer, "apply", lambda plan: written.append(plan))
    client = core.test_connect()
    core._manage_hooks(True)

    assert client.wait_for("window.open").payload == {"name": "hooks.install"}
    assert written == []


def test_the_welcome_waits_for_a_window_then_stops_once_dismissed(core):
    from wizard.onboarding import mark_shown

    core.ui.show_onboarding()  # at startup, before any window connected
    first = core.test_connect()
    assert first.wait_for("window.open").payload == {"name": "onboarding"}

    mark_shown()
    later = core.test_connect()
    later.wait_for("sessions.update")
    assert later.of_type("window.open") == []


# -- the launcher going away ---------------------------------------------------


def test_closing_stdin_means_the_launcher_is_gone():
    """Tauri keeps the pipe open; when it dies, Windows closes it for us."""
    from wizard.presenter_remote import ParentWatch

    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "rb")
    watch = ParentWatch(stream)
    gone = []
    watch.gone.connect(lambda: gone.append(True))
    assert watch.start()

    os.write(write_fd, b"ignored")
    assert not spin_until(lambda: gone, timeout_ms=200)
    os.close(write_fd)

    assert spin_until(lambda: gone == [True])
    stream.close()


def test_no_stdin_no_watch():
    from wizard.presenter_remote import ParentWatch

    watch = ParentWatch()
    watch._stream = None  # pythonw.exe: sys.stdin is None
    assert not watch.start()


def test_a_window_is_told_the_real_claude_state_not_a_guess(core):
    """Without prewarm the core connects to Claude on the first question and
    never announces anything before: the window must not be told
    "connecting" forever."""
    client = core.test_connect()
    connection = client.wait_for("connection")
    assert connection.payload["state"] == core.claude.state == "offline"


# -- requests (rpc.py) ---------------------------------------------------------


def test_a_request_is_answered_with_its_id(core):
    core.rpc.register("test.echo", lambda params: {"echo": params["text"]})
    client = core.test_connect("settings")
    client.send("request", {"method": "test.echo", "params": {"text": "été"}}, id="q1")
    reply = client.wait_for("reply")
    assert reply.id == "q1"
    assert reply.payload == {"ok": True, "data": {"echo": "été"}}


def test_an_unknown_method_is_refused(core):
    client = core.test_connect("settings")
    client.send("request", {"method": "shell.run", "params": {}}, id="q2")
    reply = client.wait_for("reply")
    assert reply.payload["ok"] is False
    assert reply.payload["error"] == "unknown_method"


def test_a_request_without_an_id_cannot_be_answered(core):
    client = core.test_connect("settings")
    client.send("request", {"method": "test.echo"})
    assert client.wait_for("error").payload["error"] == "missing_id"


def test_the_app_window_services_run_on_the_real_app(core):
    """The services, wired to a real AvatarApp: what the app window gets."""
    client = core.test_connect("app")

    def ask(method, params=None, id="q"):
        client.send("request", {"method": method, "params": params or {}}, id=id)
        return client.wait_for("reply", count=len(client.of_type("reply")) + 1).payload

    fields = ask("settings.read", id="a")["data"]["fields"]
    assert {"section": "claude", "key": "enabled"}.items() <= next(
        f for f in fields if f["key"] == "enabled" and f["section"] == "claude"
    ).items()

    assert ask("notes.add", {"body": "pain"}, id="b")["ok"]
    assert ask("notes.list", id="c")["data"]["items"][0]["body"] == "pain"

    added = ask("timers.add", {"duration": "25"}, id="d")["data"]
    assert ask("timers.list", id="e")["data"]["items"][0]["id"] == added["id"]
    ask("timers.cancel_all", id="f")

    refused = ask("settings.write", {"values": {"appearance.scale": 99}}, id="g")
    assert refused["ok"] is False and refused["error"] == "invalid"


def test_the_look_of_the_avatar_is_sent_on_connect_and_on_reload(core):
    client = core.test_connect("avatar")
    assert client.wait_for("appearance").payload == {
        "scale": core.config.appearance.scale,
        "opacity": core.config.appearance.opacity,
        "click_through": core.config.appearance.click_through_when_idle,
        "exclude_from_capture": core.config.ui.exclude_from_capture,
    }
    core.config.appearance.opacity = 0.5
    core.ui.apply_config(core.config)
    assert client.wait_for("appearance", count=2).payload["opacity"] == 0.5


def test_ctrl_drag_released_over_nothing_says_so(core, monkeypatch):
    from wizard import winapi

    monkeypatch.setattr(winapi, "window_at", lambda x, y, ignore=None: None)
    failures = []
    core.capture.failed.connect(failures.append)
    client = core.test_connect("avatar")
    client.send("capture.window", {"x": 10, "y": 20})
    spin_until(lambda: failures)
    assert failures == ["Aucune fenêtre à cet endroit."]
