import json
import os
import tempfile

from PySide6.QtNetwork import QLocalSocket


def make_sockpath() -> str:
    d = tempfile.mkdtemp(prefix="clawd")
    os.chmod(d, 0o700)
    return os.path.join(d, "c.sock")


def post(path: str, body: dict) -> QLocalSocket:
    data = json.dumps(body).encode()
    request = (
        b"POST /event HTTP/1.1\r\nHost: clawd\r\nContent-Type: application/json\r\n"
        + f"Content-Length: {len(data)}\r\n\r\n".encode()
        + data
    )
    sock = QLocalSocket()
    sock.connectToServer(path)
    assert sock.waitForConnected(2000)
    sock.write(request)
    sock.flush()
    return sock
