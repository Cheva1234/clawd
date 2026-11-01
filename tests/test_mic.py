from PySide6.QtCore import QObject, Signal

from clawd.audio import QtMicIn


class FakeDevice:
    def __init__(self, null=False, supported=True):
        self._null, self._supported = null, supported

    def isNull(self):
        return self._null

    def isFormatSupported(self, fmt):
        return self._supported


class FakeIO(QObject):
    readyRead = Signal()

    def __init__(self):
        super().__init__()
        self.buffer = b""

    def readAll(self):
        class Bytes:
            def __init__(self, b):
                self._b = b

            def data(self):
                return self._b

        data, self.buffer = self.buffer, b""
        return Bytes(data)


class FakeSource:
    def __init__(self):
        self.io = FakeIO()
        self.stopped = 0

    def start(self):
        return self.io

    def stop(self):
        self.stopped += 1


def test_no_microphone_reports_a_clear_failure(qtbot):
    mic = QtMicIn(device=FakeDevice(null=True))
    with qtbot.waitSignal(mic.failed) as sig:
        mic.start()
    assert "microphone" in sig.args[0].lower()


def test_unsupported_format_reports_a_failure(qtbot):
    mic = QtMicIn(device=FakeDevice(supported=False))
    with qtbot.waitSignal(mic.failed):
        mic.start()


def test_audio_from_the_device_is_forwarded_as_chunks(qtbot):
    src = FakeSource()
    mic = QtMicIn(device=FakeDevice(), source=src)
    chunks = []
    mic.chunk.connect(chunks.append)
    mic.start()
    src.io.buffer = b"\x01\x02" * 800
    src.io.readyRead.emit()
    assert chunks == [b"\x01\x02" * 800]
    src.io.readyRead.emit()  # nothing new: no empty chunk
    assert len(chunks) == 1


def test_stop_stops_the_source_and_ignores_later_audio(qtbot):
    src = FakeSource()
    mic = QtMicIn(device=FakeDevice(), source=src)
    chunks = []
    mic.chunk.connect(chunks.append)
    mic.start()
    mic.stop()
    src.io.buffer = b"late"
    src.io.readyRead.emit()
    assert src.stopped == 1 and chunks == []
