"""The local WebSocket the Tauri UI talks to the core through.

A WebSocket on 127.0.0.1 is reachable by every web page open in every browser
on this machine, so being local is not a protection. What keeps strangers out:

* a secret token, handed to the core by the process that launched it, that
  every connection must present in its first message, within two seconds;
* the Origin header: a browser always sends it, and only our own UI's origins
  are accepted (a native client sends none, and still needs the token);
* a cap on message size, and text messages only.

Every authenticated client receives every event: one connection per Tauri
window, each drawing the part it is responsible for.
"""

from __future__ import annotations

import hmac
import logging
import os
from dataclasses import dataclass, field

import shiboken6
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QHostAddress
from PySide6.QtWebSockets import QWebSocket, QWebSocketProtocol, QWebSocketServer

from . import protocol
from .protocol import Message, ProtocolError

log = logging.getLogger(__name__)

#: Where the UI pages are served from. Tauri 2 on Windows serves the app from
#: http://tauri.localhost; Vite's dev server is the other two.
DEFAULT_ORIGINS = frozenset(
    {
        "http://tauri.localhost",
        "https://tauri.localhost",
        "tauri://localhost",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }
)

HELLO_TIMEOUT_MS = 2000

#: Generous for anything the UI sends (a question, a file path); far below
#: what it would take to hurt the core.
MAX_MESSAGE_BYTES = 1 << 20

_CLOSE_POLICY = QWebSocketProtocol.CloseCode.CloseCodePolicyViolated


@dataclass(eq=False)
class Client:
    """One connected UI window."""

    socket: QWebSocket
    authenticated: bool = False
    role: str = ""
    pid: int | None = None
    timer: QTimer | None = field(default=None, repr=False)


class UiServer(QObject):
    """Accepts UI connections, checks them, and routes their messages."""

    #: A validated message from an authenticated client.
    received = Signal(object, object)  # (Client, Message)
    #: A client just authenticated: send it the current state.
    client_ready = Signal(object)  # Client
    #: An authenticated client left.
    client_gone = Signal(object)  # Client
    #: The last authenticated client left.
    all_gone = Signal()

    def __init__(
        self,
        token: str,
        origins: frozenset[str] = DEFAULT_ORIGINS,
        version: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if not token:
            raise ValueError("the UI server needs a non-empty token")
        self._token = token.encode("utf-8")
        self._origins = origins
        self._version = version
        self._clients: list[Client] = []
        self._server = QWebSocketServer(
            "LittleWizard", QWebSocketServer.SslMode.NonSecureMode, self
        )
        self._server.newConnection.connect(self._on_new_connection)

    # -- lifecycle --------------------------------------------------------

    def start(self, port: int = 0) -> bool:
        """Listen on 127.0.0.1 only; port 0 lets the system pick a free one."""
        return self._server.listen(
            QHostAddress(QHostAddress.SpecialAddress.LocalHost), port
        )

    @property
    def port(self) -> int:
        return self._server.serverPort()

    @property
    def error(self) -> str:
        return self._server.errorString()

    def stop(self) -> None:
        clients, self._clients = self._clients, []
        for client in clients:
            # Shutting down: nothing left to keep track of. Left connected,
            # the handler could run after Qt has destroyed the socket.
            client.socket.disconnected.disconnect()
            client.socket.close()
        self._server.close()

    @property
    def clients(self) -> list[Client]:
        """Authenticated clients only."""
        return [c for c in self._clients if c.authenticated]

    # -- sending ----------------------------------------------------------

    def broadcast(self, type_: str, payload: dict | None = None) -> None:
        """Send an event to every authenticated client."""
        text = protocol.encode(type_, payload)
        for client in self.clients:
            client.socket.sendTextMessage(text)

    def send(
        self,
        client: Client,
        type_: str,
        payload: dict | None = None,
        id: str | None = None,
    ) -> None:
        client.socket.sendTextMessage(protocol.encode(type_, payload, id))

    # -- connections ------------------------------------------------------

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            origin = socket.origin()
            if origin and origin not in self._origins:
                # Logged without the token or the payload: there is none yet.
                log.warning("refused a UI connection from origin %s", origin)
                socket.close(_CLOSE_POLICY, "origin not allowed")
                socket.deleteLater()
                continue

            socket.setMaxAllowedIncomingMessageSize(MAX_MESSAGE_BYTES)
            client = Client(socket)
            timer = QTimer(socket)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda c=client: self._drop(c, "no hello in time"))
            timer.start(HELLO_TIMEOUT_MS)
            client.timer = timer
            self._clients.append(client)

            socket.textMessageReceived.connect(
                lambda text, c=client: self._on_text(c, text)
            )
            socket.binaryMessageReceived.connect(
                lambda _data, c=client: self._drop(c, "binary messages are not accepted")
            )
            socket.disconnected.connect(lambda c=client: self._forget(c))

    def _on_text(self, client: Client, text: str) -> None:
        if len(text.encode("utf-8")) > MAX_MESSAGE_BYTES:
            self._drop(client, "message too large")
            return
        try:
            message = protocol.decode(text, protocol.UI)
        except ProtocolError as exc:
            if not client.authenticated:
                self._drop(client, "invalid first message")
                return
            self.send(client, "error", {"error": exc.code, "message": str(exc)})
            return

        if not client.authenticated:
            self._authenticate(client, message)
            return
        if message.type == "hello":
            self.send(
                client,
                "error",
                {"error": "already_authenticated", "message": "hello sent twice"},
                message.id,
            )
            return
        if message.type == "ping":
            self.send(client, "reply", {"ok": True}, message.id)
            return
        self.received.emit(client, message)

    def _authenticate(self, client: Client, message: Message) -> None:
        if message.type != "hello":
            self._drop(client, "the first message must be hello")
            return
        offered = message.payload["token"].encode("utf-8")
        # Constant time: comparing byte by byte and stopping at the first
        # difference would tell a patient attacker how much they got right.
        if not hmac.compare_digest(offered, self._token):
            self._drop(client, "bad token")
            return
        if message.payload["protocol"] != protocol.PROTOCOL_VERSION:
            self._drop(client, "protocol version mismatch")
            return

        if client.timer is not None:
            client.timer.stop()
        client.authenticated = True
        client.role = message.payload["role"]
        client.pid = message.payload.get("pid")
        self.send(
            client,
            "hello.ok",
            {
                "protocol": protocol.PROTOCOL_VERSION,
                "version": self._version,
                "pid": os.getpid(),
            },
            message.id,
        )
        self.client_ready.emit(client)

    def _drop(self, client: Client, reason: str) -> None:
        log.warning("closing a UI connection: %s", reason)
        client.socket.close(_CLOSE_POLICY, reason)

    def _forget(self, client: Client) -> None:
        was_authenticated = client.authenticated
        if client in self._clients:
            self._clients.remove(client)
        if shiboken6.isValid(client.socket):
            client.socket.deleteLater()
        if was_authenticated:
            self.client_gone.emit(client)
        if was_authenticated and not self.clients:
            self.all_gone.emit()
