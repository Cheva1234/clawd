import math
import random
from array import array

from clawd.gate import FRAME_BYTES, SpeechGate, rms

RATE = 16000


def tone(ms, amp=8000):
    n = RATE * ms // 1000
    return array("h", (int(amp * math.sin(2 * math.pi * 220 * i / RATE)) for i in range(n))).tobytes()


def quiet(ms, amp=30, seed=1):
    rnd = random.Random(seed)
    n = RATE * ms // 1000
    return array("h", (rnd.randint(-amp, amp) for _ in range(n))).tobytes()


def make():
    gate = SpeechGate()
    log = {"started": [], "chunks": [], "ended": 0}
    gate.speech_started.connect(log["started"].append)
    gate.speech_chunk.connect(log["chunks"].append)
    gate.speech_ended.connect(lambda: log.__setitem__("ended", log["ended"] + 1))
    return gate, log


def feed(gate, data, size=FRAME_BYTES):
    for i in range(0, len(data), size):
        gate.feed(data[i : i + size])


def test_silence_never_triggers():
    gate, log = make()
    feed(gate, quiet(3000))
    assert log["started"] == [] and log["ended"] == 0


def test_a_steady_hum_never_triggers():
    gate, log = make()
    feed(gate, tone(3000, amp=400))  # a fan: loud-ish but constant
    assert log["started"] == []


def test_a_50ms_click_does_not_trigger():
    gate, log = make()
    feed(gate, quiet(1000) + tone(50) + quiet(1000, seed=2))
    assert log["started"] == []


def test_speech_starts_after_150ms_and_carries_300ms_of_preroll():
    gate, log = make()
    feed(gate, quiet(1000) + tone(500))
    assert len(log["started"]) == 1
    first = log["started"][0]
    assert len(first) == (15 + 8) * FRAME_BYTES  # 300 ms before + the 160 ms that proved it was speech
    assert rms(first[:FRAME_BYTES]) < 100  # the preroll is the quiet before the word
    assert rms(first[-FRAME_BYTES:]) > 4000  # ...and it ends in the loud part


def test_speech_chunks_flow_until_the_end_and_nothing_before():
    gate, log = make()
    feed(gate, quiet(1000))
    assert log["chunks"] == []
    feed(gate, tone(500))
    assert log["chunks"], "audio after the start must reach the listener"


def test_speech_ends_after_about_700ms_of_quiet_and_not_before():
    gate, log = make()
    feed(gate, quiet(1000) + tone(500))
    feed(gate, quiet(600, seed=3))
    assert log["ended"] == 0
    feed(gate, quiet(300, seed=4))  # the level is smoothed over a few frames, so "about" 700 ms
    assert log["ended"] == 1


def test_a_pause_shorter_than_700ms_stays_one_utterance():
    gate, log = make()
    feed(gate, quiet(1000) + tone(400) + quiet(400, seed=5) + tone(400))
    assert len(log["started"]) == 1 and log["ended"] == 0


def test_odd_chunk_sizes_give_the_same_result():
    signal = quiet(1000) + tone(500) + quiet(900, seed=6)
    base, base_log = make()
    feed(base, signal)
    for size in (100, 333, 1001, 4096):
        gate, log = make()
        feed(gate, signal, size)
        assert len(log["started"]) == 1 and log["ended"] == 1
        assert log["started"][0] == base_log["started"][0]


def test_a_second_utterance_after_the_first_works():
    gate, log = make()
    feed(gate, quiet(1000) + tone(500) + quiet(900, seed=7) + tone(500) + quiet(900, seed=8))
    assert len(log["started"]) == 2 and log["ended"] == 2


def test_a_room_that_gets_gradually_louder_raises_the_threshold_instead_of_triggering():
    gate, log = make()
    rnd = random.Random(9)
    frames = 500  # 10 seconds
    for i in range(frames):
        amp = int(30 * (600 / 30) ** (i / frames))
        n = FRAME_BYTES // 2
        feed(gate, array("h", (rnd.randint(-amp, amp) for _ in range(n))).tobytes())
    assert log["started"] == []


def room(ms, base=208, spike=780, every_ms=300, seed=11):
    """A noisy room like a USB mic with a loud background: steady noise (RMS about 120) with 40 ms bursts (about 450)."""
    rnd = random.Random(seed)
    out = array("h")
    for i in range(RATE * ms // 1000):
        in_burst = (i * 1000 // RATE) % every_ms < 40
        amp = spike if in_burst else base
        out.append(rnd.randint(-amp, amp))
    return out.tobytes()


def talk(ms, amp=2500, seed=12):
    """Someone talking in that room: a tone plus the room's noise."""
    mixed = array("h", tone(ms, amp=amp))
    noise = array("h", room(ms, seed=seed))
    return array("h", (max(-32768, min(32767, a + b)) for a, b in zip(mixed, noise))).tobytes()


def test_in_a_noisy_room_speech_still_ends_and_the_next_sentence_is_heard():
    gate, log = make()
    feed(gate, room(3000) + talk(1200) + room(2000, seed=13))
    assert log["ended"] == 1, "the end of speech must be noticed although the room is noisy"
    feed(gate, talk(1200, seed=14) + room(2000, seed=15))
    assert len(log["started"]) == 2 and log["ended"] == 2


def test_three_sentences_in_a_noisy_room_are_all_heard():
    gate, log = make()
    feed(gate, room(3000))
    for n in range(3):
        feed(gate, talk(1000, seed=20 + n) + room(1800, seed=30 + n))
    assert len(log["started"]) == 3 and log["ended"] == 3


def test_reset_leaves_a_stuck_speaking_state():
    gate, log = make()
    feed(gate, room(1000) + talk(500))
    assert gate.speaking
    gate.reset()
    assert not gate.speaking
    feed(gate, room(1500, seed=40) + talk(800, seed=41))
    assert len(log["started"]) == 2


def test_an_endless_loud_sound_is_cut_off_instead_of_speaking_forever():
    gate, log = make()
    feed(gate, quiet(1000) + tone(30000))
    assert log["ended"] >= 1  # forced end of a very long utterance (the session limit is 30 s anyway)
