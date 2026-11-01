import io
import json
import os
import socket
import stat
import tempfile

import pytest
from PySide6.QtNetwork import QLocalSocket

from tests.helpers import make_sockpath, post
from clawd.ipc import AlreadyRunning, EventServer, ParentWatchdog, emit_command


@pytest.fixture
def sockpath():
    return make_sockpath()


def test_event_posted_to_socket_emits_signal_and_answers_200(qtbot, sockpath):
    server = EventServer()
    server.start(sockpath)
    try:
        with qtbot.waitSignal(server.event, timeout=3000) as sig:
            client = post(sockpath, {"kind": "tool.call", "tool": "Bash"})
        assert sig.args == [{"kind": "tool.call", "tool": "Bash"}]
        qtbot.waitUntil(lambda: client.bytesAvailable() > 0, timeout=3000)
        assert client.readAll().data().startswith(b"HTTP/1.1 200")
    finally:
        server.stop()


def test_body_split_across_packets_still_parses(qtbot, sockpath):
    server = EventServer()
    server.start(sockpath)
    try:
        data = json.dumps({"kind": "turn.start"}).encode()
        sock = QLocalSocket()
        sock.connectToServer(sockpath)
        assert sock.waitForConnected(2000)
        sock.write(b"POST /event HTTP/1.1\r\nContent-Length: " + str(len(data)).encode() + b"\r\n\r\n")
        sock.flush()
        qtbot.wait(50)
        with qtbot.waitSignal(server.event, timeout=3000):
            sock.write(data)
            sock.flush()
    finally:
        server.stop()


def test_garbage_request_is_ignored_and_server_keeps_working(qtbot, sockpath):
    server = EventServer()
    server.start(sockpath)
    try:
        bad = QLocalSocket()
        bad.connectToServer(sockpath)
        assert bad.waitForConnected(2000)
        bad.write(b"POST /event HTTP/1.1\r\nContent-Length: 5\r\n\r\nnot{j")
        bad.flush()
        qtbot.wait(100)
        with qtbot.waitSignal(server.event, timeout=3000):
            post(sockpath, {"kind": "ok"})
    finally:
        server.stop()


def test_stale_socket_file_is_replaced_on_start(sockpath):
    dead = socket.socket(socket.AF_UNIX)
    dead.bind(sockpath)
    dead.close()  # leaves the socket file behind, nobody listening
    assert os.path.exists(sockpath)
    server = EventServer()
    server.start(sockpath)
    try:
        assert server.is_listening()
    finally:
        server.stop()


def test_second_instance_refuses_when_socket_is_live(sockpath):
    first = EventServer()
    first.start(sockpath)
    try:
        with pytest.raises(AlreadyRunning):
            EventServer().start(sockpath)
    finally:
        first.stop()


def test_socket_is_private_to_the_user(sockpath):
    server = EventServer()
    server.start(sockpath)
    try:
        assert stat.S_IMODE(os.stat(sockpath).st_mode) & 0o077 == 0
    finally:
        server.stop()


def test_stop_removes_the_socket_file(sockpath):
    server = EventServer()
    server.start(sockpath)
    server.stop()
    assert not os.path.exists(sockpath)


def test_emit_command_writes_one_json_line():
    out = io.StringIO()
    emit_command({"type": "submit", "text": "list the files"}, stream=out)
    assert out.getvalue() == '{"type": "submit", "text": "list the files"}\n'


def test_watchdog_signals_when_parent_changes(qtbot):
    pids = iter([100, 100, 1])
    dog = ParentWatchdog(interval_ms=10, getppid=lambda: next(pids))
    with qtbot.waitSignal(dog.parent_gone, timeout=2000):
        dog.start()
    dog.stop()


def test_start_creates_a_private_parent_directory(tmp_path):
    path = os.path.join(tempfile.mkdtemp(prefix="clawd"), "run", "c.sock")
    server = EventServer()
    server.start(path)
    try:
        assert stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode) == 0o700
    finally:
        server.stop()
