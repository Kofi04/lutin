"""The local WebSocket: who gets in, and what they receive.

Real sockets on 127.0.0.1, so this is the actual handshake and framing, not a
mock of it.
"""

from __future__ import annotations

import pytest

from wizard import ws_server
from wizard.ws_server import UiServer

from .ws_client import TestClient, spin_until

TOKEN = "s3cret-token"


@pytest.fixture
def server():
    made = UiServer(TOKEN, version="test")
    assert made.start(), made.error
    yield made
    made.stop()


@pytest.fixture
def clients():
    made = []
    yield made
    for client in made:
        client.close()


def connect(server, clients, origin: str = "") -> TestClient:
    client = TestClient(server.port, origin)
    clients.append(client)
    return client


def test_listens_on_loopback_only(server):
    from PySide6.QtNetwork import QHostAddress

    assert server._server.serverAddress() == QHostAddress(
        QHostAddress.SpecialAddress.LocalHost
    )
    assert server.port > 0


def test_good_token_is_welcomed(server, clients):
    client = connect(server, clients)
    assert client.hello(TOKEN)
    welcome = client.of_type("hello.ok")[0]
    assert welcome.payload["protocol"] == 1
    assert welcome.payload["version"] == "test"
    assert len(server.clients) == 1


def test_bad_token_is_closed(server, clients):
    client = connect(server, clients)
    client.send("hello", {"token": "guess", "protocol": 1, "role": "dev"})
    assert client.wait_closed()
    assert client.of_type("hello.ok") == []
    assert server.clients == []


def test_anything_before_hello_is_closed(server, clients):
    client = connect(server, clients)
    client.send("ask", {"text": "let me in"})
    assert client.wait_closed()


def test_garbage_before_hello_is_closed(server, clients):
    client = connect(server, clients)
    client.send_raw("{not json")
    assert client.wait_closed()


def test_silence_is_closed(server, clients, monkeypatch):
    monkeypatch.setattr(ws_server, "HELLO_TIMEOUT_MS", 50)
    client = connect(server, clients)
    assert client.wait_open()
    assert client.wait_closed(timeout_ms=1000)


def test_wrong_protocol_version_is_closed(server, clients):
    client = connect(server, clients)
    client.send("hello", {"token": TOKEN, "protocol": 99, "role": "dev"})
    assert client.wait_closed()


def test_a_web_page_from_elsewhere_is_refused(server, clients):
    """What a malicious page open in a browser would look like."""
    client = connect(server, clients, origin="https://evil.example")
    assert client.wait_closed()
    assert "origin" in client.close_reason


@pytest.mark.parametrize("origin", ["http://tauri.localhost", "http://localhost:5173"])
def test_our_own_origins_are_accepted(server, clients, origin):
    client = connect(server, clients, origin=origin)
    assert client.hello(TOKEN)


def test_oversized_message_is_refused(server, clients, monkeypatch):
    monkeypatch.setattr(ws_server, "MAX_MESSAGE_BYTES", 1000)
    client = connect(server, clients)
    assert client.hello(TOKEN)
    client.send("ask", {"text": "x" * 2000})
    assert client.wait_closed()


def test_binary_messages_are_refused(server, clients):
    from PySide6.QtCore import QByteArray

    client = connect(server, clients)
    assert client.hello(TOKEN)
    client.socket.sendBinaryMessage(QByteArray(b"\x00\x01"))
    assert client.wait_closed()


def test_ping_gets_a_reply_with_its_id(server, clients):
    client = connect(server, clients)
    assert client.hello(TOKEN)
    client.send("ping", id="p7")
    reply = client.wait_for("reply")
    assert reply.id == "p7"
    assert reply.payload == {"ok": True}


def test_invalid_message_after_hello_gets_an_error_not_a_close(server, clients):
    client = connect(server, clients)
    assert client.hello(TOKEN)
    client.send("approval.answer", {"request_id": "r1", "decision": "maybe"})
    error = client.wait_for("error")
    assert error.payload["error"] == "bad_payload"
    assert not client.closed


def test_valid_commands_reach_the_app(server, clients):
    received = []
    server.received.connect(lambda c, m: received.append((c.role, m.type, m.payload)))
    client = connect(server, clients)
    assert client.hello(TOKEN, role="panel")
    client.send("ask", {"text": "Bonjour"})
    assert spin_until(lambda: received)
    assert received == [("panel", "ask", {"text": "Bonjour"})]


def test_broadcast_reaches_every_authenticated_client_only(server, clients):
    avatar = connect(server, clients)
    panel = connect(server, clients)
    stranger = connect(server, clients)
    assert avatar.hello(TOKEN, "avatar")
    assert panel.hello(TOKEN, "panel")
    assert stranger.wait_open()

    server.broadcast("toast", {"title": "Hé", "body": "", "kind": "info"})

    assert avatar.wait_for("toast") is not None
    assert panel.wait_for("toast") is not None
    assert stranger.of_type("toast") == []


def test_departures_are_reported(server, clients):
    gone, all_gone = [], []
    server.client_gone.connect(lambda c: gone.append(c.role))
    server.all_gone.connect(lambda: all_gone.append(True))
    avatar = connect(server, clients)
    panel = connect(server, clients)
    assert avatar.hello(TOKEN, "avatar")
    assert panel.hello(TOKEN, "panel")

    avatar.close()
    assert spin_until(lambda: gone == ["avatar"])
    assert all_gone == []
    panel.close()
    assert spin_until(lambda: all_gone == [True])


def test_an_empty_token_is_refused_at_construction():
    with pytest.raises(ValueError):
        UiServer("")


def test_stopping_with_clients_connected_is_clean(capsys):
    """Found by running the real core: at exit, a socket was destroyed before
    its `disconnected` handler ran, and the handler then raised. The exit
    itself is checked by running the core; this pins the orderly part."""
    server = UiServer(TOKEN)
    assert server.start()
    client = TestClient(server.port)
    assert client.hello(TOKEN)

    server.stop()
    assert client.wait_closed()
    assert server.clients == []
    spin_until(lambda: False, timeout_ms=100)

    assert "Traceback" not in capsys.readouterr().err
