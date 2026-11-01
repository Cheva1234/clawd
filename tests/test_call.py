import math
import random
from array import array

import pytest
from PySide6.QtCore import QObject, Signal

from clawd.call import Call
from clawd.gate import FRAME_BYTES, SpeechGate


class FakeMic(QObject):
    chunk = Signal(bytes)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.started = self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


class FakeGate(QObject):
    speech_started = Signal(bytes)
    speech_chunk = Signal(bytes)
    speech_ended = Signal()

    def __init__(self):
        super().__init__()
        self.fed = []
        self.speaking = False
        self.resets = 0

    def feed(self, data):
        self.fed.append(data)

    def reset(self):
        self.resets += 1
        self.speaking = False


class FakeListener(QObject):
    partial = Signal(str)
    final = Signal(str)
    failed = Signal(str)
    ended = Signal()

    def __init__(self, um):
        super().__init__()
        self.um = um
        self.active = False
        self.log = []
        self.heard = []
        um.chunk.connect(self.heard.append)

    def start(self):
        self.log.append("start")
        self.active = True

    def stop(self):
        self.log.append("stop")

    def cancel(self):
        self.log.append("cancel")
        self.active = False
        self.ended.emit()


class Rig:
    def __init__(self, gate=None, waiting=False, auto_mute_secs=120.0):
        self.mic, self.gate = FakeMic(), gate or FakeGate()
        self.listeners = []
        self.flags = {"waiting": waiting}
        self.clock = [0.0]

        def factory(um):
            listener = FakeListener(um)
            self.listeners.append(listener)
            return listener

        self.call = Call(
            self.mic, self.gate, factory, lambda: self.flags["waiting"],
            countdown_secs=0.12, interval_ms=10, auto_mute_secs=auto_mute_secs, clock=lambda: self.clock[0],
        )
        self.out = {k: [] for k in ("transcript", "pending", "submit", "notice", "live", "speech", "barge", "auto")}
        c = self.call
        c.transcript.connect(lambda t, f: self.out["transcript"].append((t, f)))
        c.pending.connect(lambda t, s: self.out["pending"].append(t))
        c.submit.connect(self.out["submit"].append)
        c.notice.connect(self.out["notice"].append)
        c.live_changed.connect(self.out["live"].append)
        c.speech_changed.connect(self.out["speech"].append)
        c.barge_in.connect(lambda: self.out["barge"].append(1))
        c.auto_muted.connect(lambda: self.out["auto"].append(1))

    def hear(self, text="list the files", preroll=b"PRE"):
        """The user says something: speech starts, a result comes back, speech ends."""
        self.gate.speech_started.emit(preroll)
        self.gate.speech_ended.emit()
        self.listeners[-1].final.emit(text)
        self.listeners[-1].ended.emit()


@pytest.fixture
def rig(qtbot):
    r = Rig()
    r.call.set_live(True)
    return r


def test_live_opens_the_mic_and_muted_closes_it_with_no_session(rig):
    assert rig.mic.started == 1 and rig.out["live"] == [True]
    rig.call.set_live(False)
    assert rig.mic.stopped == 1 and rig.out["live"] == [True, False]
    rig.gate.speech_started.emit(b"x")
    assert rig.listeners == []  # muted: nothing is listened to


def test_mic_audio_goes_to_the_detector(rig):
    rig.mic.chunk.emit(b"abc")
    assert rig.gate.fed == [b"abc"]


def test_speech_start_opens_one_session_seeded_with_the_preroll_and_signals_barge_in(rig):
    rig.gate.speech_started.emit(b"PRE")
    assert len(rig.listeners) == 1 and rig.listeners[0].log == ["start"]
    assert rig.listeners[0].heard == [b"PRE"] and rig.out["barge"] == [1] and rig.out["speech"] == [True]
    rig.gate.speech_chunk.emit(b"more")
    assert rig.listeners[0].heard == [b"PRE", b"more"]


def test_speech_end_commits_the_session(rig):
    rig.gate.speech_started.emit(b"PRE")
    rig.gate.speech_ended.emit()
    assert rig.listeners[0].log == ["start", "stop"]


def test_live_words_then_a_countdown_then_one_submit(rig, qtbot):
    rig.gate.speech_started.emit(b"PRE")
    rig.listeners[0].partial.emit("list the")
    rig.gate.speech_ended.emit()
    rig.listeners[0].final.emit("list the files")
    rig.listeners[0].ended.emit()
    assert rig.out["transcript"] == [("list the", False), ("list the files", True)]
    assert rig.out["pending"][0] == "list the files" and rig.out["submit"] == []
    qtbot.waitUntil(lambda: rig.out["submit"] == ["list the files"], timeout=2000)
    qtbot.wait(150)
    assert rig.out["submit"] == ["list the files"] and rig.out["pending"][-1] is None
    assert rig.out["speech"] == [True, False]


def test_cancel_during_the_countdown_sends_nothing(rig, qtbot):
    rig.hear()
    rig.call.cancel_pressed()
    qtbot.wait(300)
    assert rig.out["submit"] == [] and rig.out["pending"][-1] is None


def test_send_button_sends_immediately(rig):
    rig.hear()
    rig.call.send_pressed()
    assert rig.out["submit"] == ["list the files"]


def test_an_edit_replaces_the_text_and_restarts_the_countdown(rig, qtbot):
    rig.hear()
    rig.call.edited("list all the files")
    qtbot.waitUntil(lambda: rig.out["submit"] == ["list all the files"], timeout=2000)


def test_the_countdown_pauses_while_claude_waits_for_you(rig, qtbot):
    rig.hear()
    rig.call.set_waiting(True)
    qtbot.wait(300)
    assert rig.out["submit"] == []
    rig.call.set_waiting(False)
    qtbot.waitUntil(lambda: rig.out["submit"] == ["list the files"], timeout=2000)


def test_muting_mid_utterance_cancels_the_session_and_sends_nothing(rig, qtbot):
    rig.gate.speech_started.emit(b"PRE")
    rig.call.set_live(False)
    assert "cancel" in rig.listeners[0].log
    rig.listeners[0].final.emit("too late")  # a late answer after muting
    qtbot.wait(300)
    assert rig.out["submit"] == [] and rig.out["pending"] == []


def test_noise_or_empty_results_are_ignored_silently(rig):
    for message in ("I didn't catch that", "I didn't hear anything"):
        rig.gate.speech_started.emit(b"x")
        rig.listeners[-1].failed.emit(message)
        rig.listeners[-1].ended.emit()
    assert rig.out["notice"] == [] and rig.out["auto"] == [] and rig.out["transcript"][-1] == ("", True)


def test_three_failures_in_a_row_mute_the_call_with_a_notice(rig):
    for _ in range(3):
        rig.gate.speech_started.emit(b"x")
        rig.listeners[-1].failed.emit("network error: cannot reach ElevenLabs")
        rig.listeners[-1].ended.emit()
    assert rig.out["auto"] == [1] and rig.out["live"][-1] is False
    assert any("muted" in n.lower() for n in rig.out["notice"])


def test_a_success_resets_the_failure_count(rig):
    for _ in range(2):
        rig.gate.speech_started.emit(b"x")
        rig.listeners[-1].failed.emit("network error: cannot reach ElevenLabs")
        rig.listeners[-1].ended.emit()
    rig.hear()
    for _ in range(2):
        rig.gate.speech_started.emit(b"x")
        rig.listeners[-1].failed.emit("network error: cannot reach ElevenLabs")
        rig.listeners[-1].ended.emit()
    assert rig.out["auto"] == []


def test_two_minutes_without_speech_auto_mutes(qtbot):
    rig = Rig(auto_mute_secs=120.0)
    rig.call.set_live(True)
    rig.clock[0] = 119.0
    rig.call.tick()
    assert rig.out["auto"] == []
    rig.clock[0] = 121.0
    rig.call.tick()
    assert rig.out["auto"] == [1] and rig.out["live"][-1] is False
    assert any("2 minutes" in n for n in rig.out["notice"])


def test_the_users_speech_and_clawds_speech_both_reset_the_silence_timer(qtbot):
    rig = Rig(auto_mute_secs=120.0)
    rig.call.set_live(True)
    rig.clock[0] = 100.0
    rig.gate.speech_started.emit(b"x")
    rig.clock[0] = 200.0
    rig.call.note_clawd_speaking()
    rig.clock[0] = 300.0
    rig.call.tick()
    assert rig.out["auto"] == []
    rig.clock[0] = 330.0
    rig.call.tick()
    assert rig.out["auto"] == [1]


def test_speech_while_claude_waits_for_a_permission_is_ignored_with_one_notice(qtbot):
    rig = Rig(waiting=True)
    rig.call.set_live(True)
    rig.gate.speech_started.emit(b"x")
    rig.gate.speech_started.emit(b"x")
    assert rig.listeners == [] and len(rig.out["notice"]) == 1 and "waiting" in rig.out["notice"][0].lower()


def test_more_speech_during_the_countdown_is_merged_into_one_request(rig, qtbot):
    rig.hear("list the files")
    rig.gate.speech_started.emit(b"x")  # the user keeps talking
    qtbot.wait(300)
    assert rig.out["submit"] == []  # the countdown waits while they talk
    rig.gate.speech_ended.emit()
    rig.listeners[-1].final.emit("in this folder")
    rig.listeners[-1].ended.emit()
    qtbot.waitUntil(lambda: rig.out["submit"] == ["list the files in this folder"], timeout=2000)
    qtbot.wait(150)
    assert rig.out["submit"] == ["list the files in this folder"]


def test_a_microphone_failure_stops_the_call_with_a_notice(rig):
    rig.mic.failed.emit("No microphone found")
    assert rig.out["notice"] == ["VOICE: No microphone found"] and rig.out["auto"] == [1]
    assert rig.out["live"][-1] is False


def test_cancel_all_drops_a_pending_request(rig, qtbot):
    rig.hear()
    rig.call.cancel_all()
    qtbot.wait(300)
    assert rig.out["submit"] == []


def tone(ms, amp=8000):
    n = 16000 * ms // 1000
    return array("h", (int(amp * math.sin(2 * math.pi * 220 * i / 16000)) for i in range(n))).tobytes()


def quiet(ms, amp=30):
    rnd = random.Random(1)
    return array("h", (rnd.randint(-amp, amp) for _ in range(16000 * ms // 1000))).tobytes()


def test_with_the_real_detector_one_utterance_opens_one_session_with_the_preroll(qtbot):
    gate = SpeechGate()
    rig = Rig(gate=gate)
    rig.call.set_live(True)
    audio = quiet(1000) + tone(500) + quiet(900)
    for i in range(0, len(audio), FRAME_BYTES):
        rig.mic.chunk.emit(audio[i : i + FRAME_BYTES])
    assert len(rig.listeners) == 1
    heard = rig.listeners[0].heard
    assert len(heard[0]) == (15 + 8) * FRAME_BYTES  # the first thing the session got was the preroll
    assert rig.listeners[0].log == ["start", "stop"]


def test_speech_resuming_while_the_last_result_is_still_pending_is_not_lost(rig, qtbot):
    rig.gate.speech_started.emit(b"A")  # first half of the sentence
    rig.gate.speech_ended.emit()  # a pause of 0.7 s: committed, the text is not back yet
    rig.gate.speech_started.emit(b"B")  # ...and they carry on
    assert len(rig.listeners) == 2 and rig.listeners[1].log == ["start"] and rig.listeners[1].heard == [b"B"]
    rig.gate.speech_chunk.emit(b"more")
    assert rig.listeners[1].heard == [b"B", b"more"] and rig.listeners[0].heard == [b"A"]
    rig.gate.speech_ended.emit()
    rig.listeners[0].final.emit("list the files")
    rig.listeners[0].ended.emit()
    rig.listeners[1].final.emit("in this folder")
    rig.listeners[1].ended.emit()
    qtbot.waitUntil(lambda: rig.out["submit"] == ["list the files in this folder"], timeout=2000)
    assert rig.out["speech"] == [True, False]  # one continuous 'listening' stretch, not two


def test_finished_sessions_are_released(rig):
    rig.hear()
    assert rig.call._pending_sessions == set() and rig.call._session is None


def test_a_session_that_ends_while_the_detector_still_hears_speech_resets_the_detector(rig):
    rig.gate.speech_started.emit(b"x")
    rig.gate.speaking = True  # the detector never noticed the end (a noisy room)
    rig.listeners[0].failed.emit("I didn't catch that")
    rig.listeners[0].ended.emit()
    assert rig.gate.resets == 1  # otherwise the call would stay deaf from here on


def test_a_normal_end_does_not_reset_the_detector(rig):
    rig.hear()
    assert rig.gate.resets == 0
