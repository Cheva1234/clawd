import asyncio
import base64
import json
import threading
from http import HTTPStatus
from urllib.parse import parse_qs, urlparse

import pytest
from PySide6.QtCore import QObject, Signal
from websockets.asyncio.server import serve

from clawd.config import Config
from clawd.credits import DailyCap
from clawd.keys import KeyFileError
from clawd.stt import Listener

KEY = "sk_test_not_a_real_key"


class FakeMic(QObject):
    chunk = Signal(bytes)
    failed = Signal(str)

    def __init__(self, fail=None):
        super().__init__()
        self.fail, self.started, self.stopped = fail, 0, 0

    def start(self):
        self.started += 1
        if self.fail:
            self.failed.emit(self.fail)

    def stop(self):
        self.stopped += 1


class Server:
    """A real WebSocket server on localhost that plays a script and records what it was sent."""

    def __init__(self, mode="normal"):
        self.mode = mode
        self.requests, self.messages = [], []
        self.loop = asyncio.new_event_loop()
        self.stop = None
        self.ready = threading.Event()
        self.port = 0
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.ready.wait(5)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main())
        self.loop.close()

    async def _main(self):
        self.stop = asyncio.Event()

        async def reject(connection, request):
            self.requests.append((request.path, dict(request.headers)))
            if self.mode == "reject":
                return connection.respond(HTTPStatus.UNAUTHORIZED, "no")

        async with serve(self._handler, "127.0.0.1", 0, process_request=reject) as server:
            self.port = server.sockets[0].getsockname()[1]
            self.ready.set()
            await self.stop.wait()

    async def _handler(self, ws):
        chunks = 0
        async for raw in ws:
            msg = json.loads(raw)
            self.messages.append(msg)
            if self.mode == "silent":
                continue
            if msg["message_type"] == "input_audio_chunk" and msg.get("audio_base_64"):
                chunks += 1
                if self.mode == "normal" and chunks == 1:
                    await ws.send(json.dumps({"message_type": "partial_transcript", "text": "list the"}))
                if self.mode == "normal" and chunks == 3:
                    await ws.send(json.dumps({"message_type": "partial_transcript", "text": "list the files"}))
                    await ws.send(json.dumps({"message_type": "committed_transcript", "text": "List the files."}))
                if self.mode == "empty" and chunks == 1:
                    await ws.send(json.dumps({"message_type": "committed_transcript", "text": ""}))
            if msg.get("commit") is True and self.mode == "commit":
                await ws.send(json.dumps({"message_type": "committed_transcript", "text": "Stopped text."}))

    @property
    def url(self):
        return f"ws://127.0.0.1:{self.port}"

    def close(self):
        self.loop.call_soon_threadsafe(self.stop.set)
        self.thread.join(3)


@pytest.fixture
def make(tmp_path):
    servers = []

    def factory(mode="normal", enabled=lambda: True, key_loader=lambda: KEY, mic=None, cap_chars=600, **kw):
        server = Server(mode)
        servers.append(server)
        mic = mic or FakeMic()
        cap = DailyCap(tmp_path / "listen.json", cap_chars, today=lambda: "d")
        listener = Listener(
            Config(), enabled=enabled, key_loader=key_loader, mic_factory=lambda: mic,
            base_url=server.url, listen_cap=cap, **kw,
        )
        out = {"partial": [], "final": [], "failed": [], "ended": []}
        listener.partial.connect(out["partial"].append)
        listener.final.connect(out["final"].append)
        listener.failed.connect(out["failed"].append)
        listener.ended.connect(lambda: out["ended"].append(1))
        return listener, server, mic, out, cap

    yield factory
    for s in servers:
        s.close()


def test_mic_audio_streams_out_and_transcripts_come_back(make, qtbot):
    listener, server, mic, out, cap = make()
    listener.start()
    for data in (b"\x01\x00" * 160, b"\x02\x00" * 160, b"\x03\x00" * 160):
        mic.chunk.emit(data)
        qtbot.wait(40)
    qtbot.waitUntil(lambda: out["final"] == ["List the files."], timeout=5000)
    qtbot.waitUntil(lambda: out["ended"] == [1], timeout=2000)
    assert out["partial"] == ["list the", "list the files"]
    path, headers = server.requests[0]
    url = urlparse(path)
    assert url.path == "/v1/speech-to-text/realtime"
    q = parse_qs(url.query)
    assert q["model_id"] == ["scribe_v2_realtime"] and q["audio_format"] == ["pcm_16000"]
    assert q["commit_strategy"] == ["manual"] and q["language_code"] == ["en"]  # our detector decides when a sentence ends
    assert headers["xi-api-key"] == KEY
    sent = [m for m in server.messages if m["message_type"] == "input_audio_chunk"]
    assert base64.b64decode(sent[0]["audio_base_64"]) == b"\x01\x00" * 160
    assert sent[0]["sample_rate"] == 16000 and sent[0]["commit"] is False
    assert mic.stopped >= 1 and cap.used() >= 1


def test_muted_or_closed_opens_no_mic_and_no_connection(make, qtbot):
    listener, server, mic, out, _ = make(enabled=lambda: False)
    listener.start()
    qtbot.wait(150)
    assert mic.started == 0 and server.requests == [] and out["ended"] == []


def test_no_microphone_fails_without_connecting(make, qtbot):
    listener, server, mic, out, _ = make(mic=FakeMic(fail="No microphone found"))
    listener.start()
    qtbot.waitUntil(lambda: out["ended"] == [1], timeout=2000)
    assert out["failed"] == ["No microphone found"] and server.requests == []


def test_a_rejected_key_is_reported_without_leaking_it(make, qtbot):
    listener, server, mic, out, _ = make(mode="reject")
    listener.start()
    qtbot.waitUntil(lambda: out["ended"] == [1], timeout=5000)
    assert "key" in out["failed"][0].lower() and KEY not in out["failed"][0]
    assert mic.stopped >= 1 and out["final"] == []


def test_stopping_by_hand_commits_and_delivers_the_text(make, qtbot):
    listener, server, mic, out, _ = make(mode="commit")
    listener.start()
    mic.chunk.emit(b"\x01\x00" * 160)
    qtbot.wait(150)
    listener.stop()
    qtbot.waitUntil(lambda: out["final"] == ["Stopped text."], timeout=5000)
    assert any(m.get("commit") is True for m in server.messages)


def test_saying_nothing_gives_up_with_a_message(make, qtbot):
    listener, server, mic, out, _ = make(mode="silent", no_speech_secs=0.4)
    listener.start()
    qtbot.waitUntil(lambda: out["ended"] == [1], timeout=5000)
    assert "hear" in out["failed"][0].lower() and out["final"] == []
    assert mic.stopped >= 1


def test_an_empty_transcript_is_not_a_request(make, qtbot):
    listener, server, mic, out, _ = make(mode="empty")
    listener.start()
    mic.chunk.emit(b"\x00\x00" * 160)
    qtbot.waitUntil(lambda: out["ended"] == [1], timeout=5000)
    assert out["final"] == [] and "catch" in out["failed"][0].lower()


def test_cancel_discards_everything_and_ends_once(make, qtbot):
    listener, server, mic, out, _ = make(mode="silent")
    listener.start()
    mic.chunk.emit(b"\x00\x00" * 160)
    qtbot.wait(100)
    listener.cancel()
    qtbot.wait(200)
    assert out["ended"] == [1] and out["final"] == [] and out["failed"] == []
    assert mic.stopped >= 1


def test_a_key_problem_fails_without_a_mic_or_connection(make, qtbot):
    def bad():
        raise KeyFileError("key not set yet")

    listener, server, mic, out, _ = make(key_loader=bad)
    listener.start()
    assert out["failed"] == ["key not set yet"] and mic.started == 0 and server.requests == []


def test_the_daily_listening_cap_blocks_without_a_connection(make, qtbot):
    listener, server, mic, out, cap = make(cap_chars=0)
    listener.start()
    qtbot.wait(100)
    assert "limit" in out["failed"][0].lower() and server.requests == [] and mic.started == 0


def test_query_asks_for_no_verbatim_text(make, qtbot):
    listener, server, mic, out, _ = make()
    listener.start()
    mic.chunk.emit(b"\x01\x00" * 160)
    qtbot.waitUntil(lambda: server.requests != [], timeout=5000)
    assert parse_qs(urlparse(server.requests[0][0]).query)["no_verbatim"] == ["true"]
    listener.cancel()


def test_a_monologue_past_the_session_limit_is_committed_not_lost(make, qtbot):
    listener, server, mic, out, _ = make(mode="commit", max_secs=0.5)
    listener.start()
    mic.chunk.emit(b"\x01\x00" * 160)
    qtbot.waitUntil(lambda: out["final"] == ["Stopped text."], timeout=5000)
    assert any(m.get("commit") is True for m in server.messages) and out["failed"] == []


def test_the_commit_is_an_empty_audio_chunk_with_commit_true(make, qtbot):
    listener, server, mic, out, _ = make(mode="commit")
    listener.start()
    mic.chunk.emit(b"\x01\x00" * 160)
    qtbot.wait(150)
    listener.stop()
    qtbot.waitUntil(lambda: out["final"] == ["Stopped text."], timeout=5000)
    commits = [m for m in server.messages if m.get("commit") is True]
    assert commits == [{"message_type": "input_audio_chunk", "audio_base_64": "", "commit": True, "sample_rate": 16000}]
    assert not any(m["message_type"] == "commit" for m in server.messages)


def test_a_worker_posting_after_the_listener_was_deleted_is_harmless(make):
    import shiboken6

    listener, server, mic, out, _ = make()
    shiboken6.delete(listener)  # the call releases finished listeners while a thread may still post a last event
    listener._post(1, "done", "")  # must not raise
