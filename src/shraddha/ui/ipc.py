"""Single-instance IPC over Qt's local socket (Windows named pipe, POSIX socket).

The lock file in :mod:`shraddha.instance` decides *who* runs. This module answers the
friendlier question: when the user launches SHRADDHA AI a second time, can we wake up
the instance they already have instead of doing nothing?

Protocol: one short line of JSON, no framing, no authentication needed - the socket is
local and carries no data beyond "show yourself".
"""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from shraddha.logging_setup import get_logger

log = get_logger("ui.ipc")

SERVER_NAME = "shraddha-ai-single-instance-v1"
_ACTIVATE = b'{"command": "activate"}\n'
_CONNECT_TIMEOUT_MS = 300


def notify_running_instance(server_name: str = SERVER_NAME) -> bool:
    """Ask an already-running instance to show itself. True if one answered."""
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(_CONNECT_TIMEOUT_MS):
        return False
    socket.write(_ACTIVATE)
    socket.flush()
    socket.waitForBytesWritten(_CONNECT_TIMEOUT_MS)
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        socket.waitForDisconnected(_CONNECT_TIMEOUT_MS)
    return True


class ActivationServer(QObject):
    """Listens for activation requests from later launches."""

    activated = Signal()

    def __init__(self, server_name: str = SERVER_NAME, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = server_name
        self._server: QLocalServer | None = None
        self._sockets: list[QLocalSocket] = []

    @property
    def is_listening(self) -> bool:
        return self._server is not None and self._server.isListening()

    def start(self) -> bool:
        """Begin listening, clearing any stale socket left by a crash."""
        if self.is_listening:
            return True
        # A previous process may have died without cleaning up its endpoint.
        QLocalServer.removeServer(self._name)

        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(self._name):
            log.warning("could not listen on %s: %s", self._name, server.errorString())
            return False
        server.newConnection.connect(self._on_new_connection)
        self._server = server
        log.debug("activation server listening on %s", self._name)
        return True

    def stop(self) -> None:
        for socket in self._sockets:
            socket.abort()
            socket.deleteLater()
        self._sockets.clear()
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None
        QLocalServer.removeServer(self._name)

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        while (socket := self._server.nextPendingConnection()) is not None:
            socket.readyRead.connect(lambda s=socket: self._on_ready_read(s))
            socket.disconnected.connect(lambda s=socket: self._release(s))
            self._sockets.append(socket)

    def _on_ready_read(self, socket: QLocalSocket) -> None:
        payload = bytes(socket.readAll()).decode("utf-8", errors="replace").strip()
        if not payload:
            return
        try:
            command = json.loads(payload).get("command", "")
        except json.JSONDecodeError:
            command = payload
        if command == "activate":
            log.debug("activation requested by another launch")
            self.activated.emit()

    def _release(self, socket: QLocalSocket) -> None:
        if socket in self._sockets:
            self._sockets.remove(socket)
        socket.deleteLater()
