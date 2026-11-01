"""Local plumbing between the Claude Code plugin and the app.

Plugin -> app: HTTP `POST /event` with a JSON body over a Unix socket (the plugin API's
`$.http.fetch` can only speak HTTP). App -> plugin: one JSON line per command on stdout.
"""
import json
import os
import re
import sys
from collections.abc import Callable
from typing import TextIO

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_MAX_REQUEST = 1_000_000
_OK = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
_BAD = b"HTTP/1.1 400 Bad Request\r\nContent-Length: 3\r\nConnection: close\r\n\r\nbad"


class AlreadyRunning(RuntimeError):
    """Another Clawd already answers on this socket."""


class EventServer(QObject):
    event = Signal(dict)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._on_connection)
        self._buffers: dict[QLocalSocket, bytearray] = {}
        self._path: str | None = None

    def start(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        probe = QLocalSocket()
        probe.connectToServer(path)
        if probe.waitForConnected(300):
            probe.abort()
            raise AlreadyRunning(path)
        QLocalServer.removeServer(path)  # a stale file from a crashed run
        if not self._server.listen(path):
            raise OSError(self._server.errorString())
        self._path = path

    def stop(self) -> None:
        self._server.close()
        if self._path:
            QLocalServer.removeServer(self._path)
            self._path = None

    def is_listening(self) -> bool:
        return self._server.isListening()

    def _on_connection(self) -> None:
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            self._buffers[sock] = bytearray()
            sock.readyRead.connect(lambda s=sock: self._on_ready(s))
            sock.disconnected.connect(lambda s=sock: self._buffers.pop(s, None))

    def _on_ready(self, sock: QLocalSocket) -> None:
        buf = self._buffers.get(sock)
        if buf is None:
            return
        buf += sock.readAll().data()
        if len(buf) > _MAX_REQUEST:
            sock.abort()
            return
        end = buf.find(b"\r\n\r\n")
        if end < 0:
            return
        match = re.search(rb"(?i)^content-length:\s*(\d+)", bytes(buf[:end]), re.MULTILINE)
        length = int(match.group(1)) if match else 0
        body = bytes(buf[end + 4 :])
        if len(body) < length:
            return
        self._buffers.pop(sock, None)
        try:
            data = json.loads(body[:length])
            ok = isinstance(data, dict)
        except ValueError:
            ok = False
        sock.write(_OK if ok else _BAD)
        sock.flush()
        sock.disconnectFromServer()
        if ok:
            self.event.emit(data)


def emit_command(obj: dict, stream: TextIO | None = None) -> None:
    """Send one command line (JSON) to the plugin on stdout."""
    out = stream or sys.stdout
    out.write(json.dumps(obj) + "\n")
    out.flush()


class ParentWatchdog(QObject):
    """Signals when the parent process (Claude Code) is gone, so the pet never outlives its session."""

    parent_gone = Signal()

    def __init__(self, interval_ms: int = 2000, getppid: Callable[[], int] = os.getppid):
        super().__init__()
        self._getppid = getppid
        self._original = getppid()
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        if self._getppid() != self._original:
            self._timer.stop()
            self.parent_gone.emit()
