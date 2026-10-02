"""A small WebSocket client for tests: connects, sends, collects, waits."""

from __future__ import annotations

import json
import time

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtWebSockets import QWebSocket

from wizard import protocol


def spin_until(condition, timeout_ms: int = 3000) -> bool:
    """Run the Qt event loop until `condition()` holds or time runs out."""
    end = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.002)
    QCoreApplication.processEvents()
    return condition()


class TestClient:
    __test__ = False  # not a test class, despite the name

    def __init__(self, port: int, origin: str = "") -> None:
        self.socket = QWebSocket(origin)
        self.messages: list[protocol.Message] = []
        self.closed = False
        self.close_reason = ""
        self.socket.textMessageReceived.connect(self._on_text)
        self.socket.disconnected.connect(self._on_closed)
        self.socket.open(QUrl(f"ws://127.0.0.1:{port}"))

    def _on_text(self, text: str) -> None:
        self.messages.append(protocol.decode(text, protocol.CORE))

    def _on_closed(self) -> None:
        self.closed = True
        self.close_reason = self.socket.closeReason()

    def wait_open(self) -> bool:
        from PySide6.QtNetwork import QAbstractSocket

        return (
            spin_until(
                lambda: (
                    self.socket.state() == QAbstractSocket.SocketState.ConnectedState
                    or self.closed
                )
            )
            and not self.closed
        )

    def send(self, type_: str, payload: dict | None = None, id: str | None = None):
        envelope = {"type": type_, "payload": payload or {}}
        if id is not None:
            envelope["id"] = id
        self.send_raw(json.dumps(envelope))

    def send_raw(self, text: str) -> None:
        # A message sent before the handshake completes is silently dropped.
        assert self.wait_open(), "the connection did not open"
        self.socket.sendTextMessage(text)

    def hello(self, token: str, role: str = "dev") -> bool:
        self.send(
            "hello", {"token": token, "protocol": protocol.PROTOCOL_VERSION, "role": role}
        )
        return self.wait_for("hello.ok") is not None

    def of_type(self, type_: str) -> list[protocol.Message]:
        return [m for m in self.messages if m.type == type_]

    def wait_for(self, type_: str, count: int = 1, timeout_ms: int = 3000):
        """The `count`-th message of this type, or None."""
        spin_until(lambda: len(self.of_type(type_)) >= count or self.closed, timeout_ms)
        found = self.of_type(type_)
        return found[count - 1] if len(found) >= count else None

    def wait_closed(self, timeout_ms: int = 3000) -> bool:
        return spin_until(lambda: self.closed, timeout_ms)

    def close(self) -> None:
        self.socket.close()
        spin_until(lambda: self.closed, 500)
