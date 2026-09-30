"""Connecting to Claude, and what happens when that fails.

`ClaudeSession` owns a worker thread and an asyncio loop, so these tests drive
the coroutines directly on their own loop rather than starting the real thing:
what is worth protecting is the decision-making — when to retry, when not to,
what state to report — not Qt's threading.
"""

from __future__ import annotations

import asyncio

import pytest

from wizard.claude import session as mod
from wizard.claude.session import CONNECTING, OFFLINE, READY


class FakeClient:
    """Stands in for ClaudeSDKClient."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.fail_with = fail_with
        self.connected = False
        self.disconnected = False
        self.interrupted = False

    async def connect(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def interrupt(self) -> None:
        self.interrupted = True


class Harness:
    """A ClaudeSession with its threading replaced by a loop we control."""

    def __init__(self, clients):
        self.session = mod.ClaudeSession.__new__(mod.ClaudeSession)
        session = self.session
        session._permission_timeout = 110
        session._allow_actions = True
        session._auto_approve_read_only = True
        session._session_id = None
        session._pending = {}
        session._always = set()
        session._task = None
        session._client = None
        session._state = OFFLINE
        session._connect_lock = None
        session._retry_at = 0.0
        session._backoff = mod._BACKOFF_START
        session._closing = False
        session._loop = asyncio.new_event_loop()

        self.states: list[tuple[str, str]] = []
        # The real one is a Qt signal; recording calls is all these tests need.
        session._set_state = self._record
        self.clients = list(clients)
        self.made: list[FakeClient] = []

    def _record(self, state, detail=""):
        self.session._state = state
        self.states.append((state, detail))

    def make_client(self, options=None):
        client = self.clients.pop(0)
        self.made.append(client)
        return client

    def run(self, coro):
        return self.session._loop.run_until_complete(coro)

    def close(self):
        self.session._loop.close()


@pytest.fixture
def harness(monkeypatch):
    built: list[Harness] = []

    def build(*clients):
        h = Harness(clients)
        monkeypatch.setattr(
            mod.ClaudeSession, "_options", lambda self: None, raising=True
        )
        import claude_agent_sdk

        monkeypatch.setattr(
            claude_agent_sdk, "ClaudeSDKClient", h.make_client, raising=True
        )
        built.append(h)
        return h

    yield build
    for h in built:
        h.close()


# -- the happy path --------------------------------------------------------


def test_connecting_reports_connecting_then_ready(harness):
    h = harness(FakeClient())

    client = h.run(h.session._ensure_client())

    assert client is not None
    assert client.connected
    assert [state for state, _ in h.states] == [CONNECTING, READY]


def test_a_second_call_reuses_the_live_client(harness):
    h = harness(FakeClient())

    first = h.run(h.session._ensure_client())
    second = h.run(h.session._ensure_client())

    assert first is second
    assert len(h.made) == 1, "connected twice"


def test_a_successful_connect_resets_the_backoff(harness):
    h = harness(FakeClient(fail_with=RuntimeError("boom")), FakeClient())

    h.run(h.session._ensure_client())
    assert h.session._backoff > mod._BACKOFF_START

    h.session._retry_at = 0.0
    h.run(h.session._ensure_client())

    assert h.session._backoff == pytest.approx(mod._BACKOFF_START)
    assert h.session._retry_at == 0.0


# -- failure ---------------------------------------------------------------


def test_a_failed_connect_reports_offline_with_a_reason(harness):
    h = harness(FakeClient(fail_with=RuntimeError("pipe is closed")))

    assert h.run(h.session._ensure_client()) is None
    assert h.states[-1][0] == OFFLINE
    assert "pipe is closed" in h.states[-1][1]


def test_a_failed_connect_closes_the_client_it_gave_up_on(harness):
    client = FakeClient(fail_with=RuntimeError("nope"))
    h = harness(client)

    h.run(h.session._ensure_client())

    # Otherwise every failed attempt leaks a CLI subprocess.
    assert client.disconnected


def test_the_backoff_grows_and_is_capped(harness):
    failures = [FakeClient(fail_with=RuntimeError("down")) for _ in range(12)]
    h = harness(*failures)

    seen = []
    for _ in range(12):
        h.session._retry_at = 0.0
        h.run(h.session._ensure_client())
        seen.append(h.session._backoff)

    assert seen[0] < seen[1] < seen[2], "backoff did not grow"
    assert max(seen) <= mod._BACKOFF_MAX


def test_the_backoff_is_respected(harness):
    h = harness(FakeClient(fail_with=RuntimeError("down")), FakeClient())

    h.run(h.session._ensure_client())
    # Still inside the wait: it must not try again, and must not report a
    # second identical failure.
    assert h.run(h.session._ensure_client()) is None
    assert len(h.made) == 1


def test_an_auth_failure_stops_the_retry_loop(harness):
    h = harness(FakeClient(fail_with=RuntimeError("OAuth session expired")))

    h.run(h.session._ensure_client())

    # Retrying cannot log anyone in, and each attempt spawns a process.
    assert h.session._retry_at == float("inf")
    assert h.states[-1][1] == mod.AUTH_HINT


def test_an_auth_failure_still_yields_to_an_explicit_retry(harness):
    h = harness(FakeClient(fail_with=RuntimeError("OAuth session expired")), FakeClient())

    h.run(h.session._ensure_client())
    # What `reconnect()` does, and what asking a question does.
    h.session._retry_at = 0.0
    client = h.run(h.session._ensure_client())

    assert client is not None
    assert h.states[-1][0] == READY


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("OAuth session expired", True),
        ("could not authenticate", True),
        ("Not logged in", True),
        ("connection reset by peer", False),
        ("", False),
    ],
)
def test_auth_problems_are_told_apart_from_outages(message, expected):
    assert mod._is_auth_problem(RuntimeError(message)) is expected


# -- shutting down ---------------------------------------------------------


def test_closing_refuses_to_connect(harness):
    h = harness(FakeClient())
    h.session._closing = True

    assert h.run(h.session._ensure_client()) is None
    assert not h.made


def test_dropping_the_client_disconnects_it(harness):
    client = FakeClient()
    h = harness(client)
    h.run(h.session._ensure_client())

    h.run(h.session._drop_client())

    assert client.disconnected
    assert h.session._client is None


def test_dropping_survives_a_disconnect_that_throws(harness):
    client = FakeClient()

    async def explode():
        raise RuntimeError("already dead")

    client.disconnect = explode
    h = harness(client)
    h.run(h.session._ensure_client())

    # Shutdown must not be the thing that raises.
    h.run(h.session._drop_client())
    assert h.session._client is None


def test_interrupting_asks_the_client_to_stop(harness):
    client = FakeClient()
    h = harness(client)
    h.run(h.session._ensure_client())

    h.run(h.session._interrupt())

    # Cancelling the task alone would leave the CLI still working.
    assert client.interrupted


# -- what the user is told -------------------------------------------------


def test_the_offline_message_points_at_the_login_when_that_is_the_problem(harness):
    h = harness(FakeClient(fail_with=RuntimeError("OAuth expired")))
    h.run(h.session._ensure_client())

    assert h.session._offline_message() == mod.AUTH_HINT


def test_the_offline_message_promises_a_retry_otherwise(harness):
    h = harness(FakeClient(fail_with=RuntimeError("socket died")))
    h.run(h.session._ensure_client())

    message = h.session._offline_message()
    assert "tentative automatique" in message


# -- a handshake that succeeds while the login is broken -------------------


class FakeResult:
    """A ResultMessage that reports the turn failed."""

    def __init__(self, text: str) -> None:
        self.is_error = True
        self.result = text
        self.session_id = "abc123"


def test_an_auth_error_mid_turn_marks_the_connection_offline(harness):
    # connect() succeeds even with no usable login: the CLI starts and
    # negotiates fine, and only the first real query fails. Staying "ready"
    # would leave the staff lit while nothing works.
    h = harness(FakeClient())
    h.run(h.session._ensure_client())
    assert h.states[-1][0] == READY

    reason = h.session._explain_result(
        FakeResult("Failed to authenticate: OAuth session expired")
    )
    assert reason == mod.AUTH_HINT


def test_a_non_auth_turn_failure_keeps_the_connection(harness):
    h = harness(FakeClient())
    h.run(h.session._ensure_client())

    reason = h.session._explain_result(FakeResult("the tool blew up"))

    assert reason != mod.AUTH_HINT
    assert h.session._state == READY
