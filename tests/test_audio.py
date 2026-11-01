from PySide6.QtMultimedia import QAudio

from clawd.audio import QtAudioOut


class FakeIO:
    def __init__(self, sink):
        self.sink = sink
        self.data = bytearray()

    def write(self, data):
        n = min(len(data), self.sink.free)
        self.sink.free -= n
        self.data += data[:n]
        return n


class FakeSink:
    def __init__(self, free=10):
        self.free = free
        self.io = FakeIO(self)
        self.active = False
        self.stopped = 0

    def start(self):
        return self.io

    def bytesFree(self):
        return self.free

    def state(self):
        return QAudio.State.ActiveState if self.active else QAudio.State.IdleState

    def stop(self):
        self.stopped += 1


def test_only_what_fits_is_written_and_the_rest_follows(qtbot):
    sink = FakeSink(free=10)
    out = QtAudioOut(sink=sink)
    out.start()
    out.write(b"ab" * 13)  # 26 mono bytes = 52 stereo bytes
    assert len(sink.io.data) == 10
    sink.free = 100  # the device played something
    qtbot.waitUntil(lambda: len(sink.io.data) == 52, timeout=2000)


def test_drained_only_after_finish_and_when_the_device_is_idle(qtbot):
    sink = FakeSink(free=100)
    out = QtAudioOut(sink=sink)
    out.start()
    out.write(b"x" * 20)
    sink.active = True
    out.finish()
    seen = []
    out.drained.connect(lambda: seen.append(1))
    qtbot.wait(120)
    assert seen == []  # still playing
    sink.active = False
    qtbot.waitUntil(lambda: seen == [1], timeout=2000)


def test_stop_discards_pending_audio_and_never_drains(qtbot):
    sink = FakeSink(free=0)
    out = QtAudioOut(sink=sink)
    out.start()
    out.write(b"z" * 50)
    seen = []
    out.drained.connect(lambda: seen.append(1))
    out.finish()
    out.stop()
    qtbot.wait(120)
    assert sink.stopped == 1 and seen == []


def test_mono_samples_are_duplicated_to_left_and_right():
    from clawd.audio import mono_to_stereo

    out, carry = mono_to_stereo(b"\x01\x02\x03\x04")
    assert out == b"\x01\x02\x01\x02\x03\x04\x03\x04" and carry == b""


def test_a_chunk_that_splits_a_sample_keeps_the_odd_byte_for_the_next_one():
    from clawd.audio import mono_to_stereo

    first, carry = mono_to_stereo(b"\x01\x02\x03")
    assert first == b"\x01\x02\x01\x02" and carry == b"\x03"
    second, carry = mono_to_stereo(b"\x04\x05\x06", carry)
    assert second == b"\x03\x04\x03\x04\x05\x06\x05\x06" and carry == b""


def test_the_output_writes_both_channels(qtbot):
    sink = FakeSink(free=1000)
    out = QtAudioOut(sink=sink)
    out.start()
    out.write(b"\x01\x02\x03")  # odd length on purpose
    out.write(b"\x04")
    assert bytes(sink.io.data) == b"\x01\x02\x01\x02\x03\x04\x03\x04"


def test_the_real_sink_is_opened_as_stereo():
    import pytest
    from PySide6.QtMultimedia import QMediaDevices

    if QMediaDevices.defaultAudioOutput().isNull():
        pytest.skip("no audio output device here")
    out = QtAudioOut()
    assert out._sink.format().channelCount() == 2
    assert out._sink.format().sampleRate() == 24000
