"""Receives hook events over a named pipe and answers permission requests.

`QLocalServer` is a named pipe on Windows, which is the direct equivalent of
the Unix socket coucou uses on macOS - and it already lives in the Qt event
loop, so no extra thread and no extra dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .protocol import HEADER_SIZE, PIPE_NAME, decode, encode, frame_length


@dataclass
class HookEvent:
    """One event from a Claude Code session outside Lutin."""

    name: str
    payload: dict = field(default_factory=dict)
    terminal: dict = field(default_factory=dict)
    wants_decision: bool = False

    @property
    def session_id(self) -> str:
        return str(self.payload.get("session_id", ""))

    @property
    def cwd(self) -> str:
        return str(self.payload.get("cwd", ""))

    @property
    def tool_name(self) -> str:
        return str(self.payload.get("tool_name", ""))

    @property
    def tool_input(self) -> dict:
        value = self.payload.get("tool_input")
        return value if isinstance(value, dict) else {}

    @property
    def project(self) -> str:
        """Short name for the session: the working directory's last segment."""
        cwd = self.cwd.replace("\\", "/").rstrip("/")
        return cwd.rsplit("/", 1)[-1] if cwd else ""


class HookServer(QObject):
    """Listens on the pipe; one connection per event."""

    #: An observational event arrived.
    event = Signal(object)  # HookEvent
    #: A session is asking permission: (request_id, HookEvent).
    decision_requested = Signal(int, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        self._buffers: dict[QLocalSocket, bytearray] = {}
        self._pending: dict[int, QLocalSocket] = {}
        self._next_id = 1

    # -- lifecycle --------------------------------------------------------

    def start(self) -> bool:
        """Begin listening. Returns False if the pipe could not be claimed."""
        # A previous run that crashed can leave the name taken; Qt removes a
        # stale one for us.
        QLocalServer.removeServer(PIPE_NAME)
        return bool(self._server.listen(PIPE_NAME))

    def stop(self) -> None:
        for request_id in list(self._pending):
            self.answer(request_id, "defer")
        self._server.close()

    @property
    def listening(self) -> bool:
        return self._server.isListening()

    @property
    def error(self) -> str:
        return self._server.errorString()

    # -- reading ----------------------------------------------------------

    def _on_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda s=socket: self._on_ready(s))
            socket.disconnected.connect(lambda s=socket: self._on_closed(s))

    def _on_ready(self, socket: QLocalSocket) -> None:
        buffer = self._buffers.get(socket)
        if buffer is None:
            return
        buffer += bytes(socket.readAll())

        while True:
            if len(buffer) < HEADER_SIZE:
                return
            try:
                length = frame_length(bytes(buffer[:HEADER_SIZE]))
            except ValueError:
                socket.abort()  # not our protocol; drop it
                return
            if len(buffer) < HEADER_SIZE + length:
                return

            body = bytes(buffer[HEADER_SIZE : HEADER_SIZE + length])
            del buffer[: HEADER_SIZE + length]
            self._dispatch(socket, body)

    def _dispatch(self, socket: QLocalSocket, body: bytes) -> None:
        try:
            message = decode(body)
        except (ValueError, UnicodeDecodeError):
            return

        event = HookEvent(
            name=str(message.get("event", "Unknown")),
            payload=message.get("payload") or {},
            terminal=message.get("terminal") or {},
            wants_decision=bool(message.get("wants_decision")),
        )

        if not event.wants_decision:
            self.event.emit(event)
            socket.disconnectFromServer()
            return

        request_id = self._next_id
        self._next_id += 1
        self._pending[request_id] = socket
        self.decision_requested.emit(request_id, event)

    def _on_closed(self, socket: QLocalSocket) -> None:
        self._buffers.pop(socket, None)
        for request_id, pending in list(self._pending.items()):
            if pending is socket:
                # The session gave up (its own timeout, or the user answered in
                # the terminal). Nothing to send.
                self._pending.pop(request_id, None)
        socket.deleteLater()

    # -- answering --------------------------------------------------------

    def answer(self, request_id: int, decision: str) -> None:
        """Send a decision back. "defer" means: leave the normal flow alone."""
        socket = self._pending.pop(request_id, None)
        if socket is None:
            return
        try:
            socket.write(encode({"decision": decision}))
            socket.flush()
            socket.disconnectFromServer()
        except RuntimeError:
            pass  # socket already destroyed by Qt
