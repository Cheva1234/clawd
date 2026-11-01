import json
import threading

import httpx
import pytest
from PySide6.QtCore import QObject, Signal

from clawd.config import Config
from clawd.credits import DailyCap
from clawd.keys import KeyFileError
from clawd.tts import Speaker

KEY = "sk_test_not_a_real_key"


class FakeOut(QObject):
    drained = Signal()

    def __init__(self):
        super().__init__()
        self.data = b""
        self.started = self.stopped = 0

    def start(self):
        self.started += 1

    def write(self, data):
        self.data += data

    def finish(self):
        self.drained.emit()

    def stop(self):
        self.stopped += 1


class Rig:
    def __init__(self, tmp_path, handler, enabled=lambda: True, key_loader=lambda: KEY, max_chars=1000):
        self.calls = []
        self.outs = []

        def wrapped(request):
            self.calls.append(request)
            return handler(request)

        self.cap = DailyCap(tmp_path / "cap.json", max_chars, today=lambda: "d")
        self.speaker = Speaker(
            Config(),
            self.cap,
            enabled=enabled,
            client=httpx.Client(transport=httpx.MockTransport(wrapped)),
            out_factory=self._make_out,
            key_loader=key_loader,
        )
        self.failures = []
        self.speaker.failed.connect(self.failures.append)

    def _make_out(self):
        out = FakeOut()
        self.outs.append(out)
        return out


def ok(chunks):
    return lambda request: httpx.Response(200, content=b"".join(chunks))


def test_speak_streams_audio_to_the_sink_and_finishes(tmp_path, qtbot):
    rig = Rig(tmp_path, ok([b"\x01\x02" * 50, b"\x03\x04" * 50]))
    with qtbot.waitSignal(rig.speaker.finished, timeout=3000):
        rig.speaker.speak("All done.")
    assert rig.outs[0].data == b"\x01\x02" * 50 + b"\x03\x04" * 50
    req = rig.calls[0]
    assert req.url.path == f"/v1/text-to-speech/{Config().voice_id}/stream"
    assert req.url.params["output_format"] == "pcm_24000"
    assert req.headers["xi-api-key"] == KEY
    assert json.loads(req.content) == {"text": "All done.", "model_id": "eleven_flash_v2_5"}
    assert rig.cap.used() == len("All done.")


def test_muted_or_closed_makes_zero_http_calls_and_spends_nothing(tmp_path, qtbot):
    rig = Rig(tmp_path, ok([b"x"]), enabled=lambda: False)
    rig.speaker.speak("hello")
    qtbot.wait(80)
    assert rig.calls == [] and rig.cap.used() == 0 and rig.outs == []


def test_empty_text_speaks_nothing(tmp_path, qtbot):
    rig = Rig(tmp_path, ok([b"x"]))
    rig.speaker.speak("   ")
    qtbot.wait(80)
    assert rig.calls == []


def test_a_new_speak_cuts_the_earlier_audio(tmp_path, qtbot):
    gate = threading.Event()

    def slow_then_fast(request):
        text = json.loads(request.content)["text"]
        if text == "first":
            def body():
                gate.wait(3)
                yield b"AAAA"

            return httpx.Response(200, stream=_Stream(body()))
        return httpx.Response(200, content=b"BBBB")

    rig = Rig(tmp_path, slow_then_fast)
    rig.speaker.speak("first")
    qtbot.wait(100)
    with qtbot.waitSignal(rig.speaker.finished, timeout=3000):
        rig.speaker.speak("second")
    gate.set()
    qtbot.wait(150)
    assert rig.outs[0].stopped >= 1
    assert all(b"AAAA" not in out.data for out in rig.outs[1:])
    assert rig.outs[-1].data == b"BBBB"


class _Stream(httpx.SyncByteStream):
    def __init__(self, gen):
        self._gen = gen

    def __iter__(self):
        yield from self._gen


@pytest.mark.parametrize("status,words", [(401, "key"), (429, "rate")])
def test_http_errors_become_a_failed_message_without_retry_or_spend(tmp_path, qtbot, status, words):
    rig = Rig(tmp_path, lambda request: httpx.Response(status, json={"detail": "x"}))
    with qtbot.waitSignal(rig.speaker.failed, timeout=3000):
        rig.speaker.speak("hello")
    qtbot.wait(100)
    assert len(rig.calls) == 1 and rig.cap.used() == 0
    assert words in rig.failures[0].lower() and KEY not in rig.failures[0]


def test_network_error_becomes_a_failed_message(tmp_path, qtbot):
    def boom(request):
        raise httpx.ConnectError("down")

    rig = Rig(tmp_path, boom)
    with qtbot.waitSignal(rig.speaker.failed, timeout=3000):
        rig.speaker.speak("hello")
    assert "network" in rig.failures[0].lower() and len(rig.calls) == 1


def test_daily_cap_blocks_without_a_call(tmp_path, qtbot):
    rig = Rig(tmp_path, ok([b"x"]), max_chars=5)
    with qtbot.waitSignal(rig.speaker.failed, timeout=1000):
        rig.speaker.speak("this is more than five characters")
    assert rig.calls == []
    assert "limit" in rig.failures[0].lower()


def test_a_key_problem_fails_without_a_call(tmp_path, qtbot):
    def bad_key():
        raise KeyFileError("key not set")

    rig = Rig(tmp_path, ok([b"x"]), key_loader=bad_key)
    with qtbot.waitSignal(rig.speaker.failed, timeout=1000):
        rig.speaker.speak("hello")
    assert rig.calls == []
