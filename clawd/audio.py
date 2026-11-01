"""Plays streamed 24 kHz mono 16-bit PCM through the default output device."""
from PySide6.QtCore import QObject, QTimer, Signal
from typing import Any

from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QAudioSource, QMediaDevices


def mono_to_stereo(data: bytes, carry: bytes = b"") -> tuple[bytes, bytes]:
    """Duplicate each 16-bit mono sample to left and right. Returns (stereo, leftover odd byte)."""
    data = carry + data
    usable = len(data) - len(data) % 2
    out = bytearray(usable * 2)
    out[0::4] = data[0:usable:2]
    out[1::4] = data[1:usable:2]
    out[2::4] = data[0:usable:2]
    out[3::4] = data[1:usable:2]
    return bytes(out), data[usable:]


class QtAudioOut(QObject):
    drained = Signal()  # everything written has been played

    def __init__(self, sink: Any = None) -> None:
        super().__init__()
        if sink is None:
            fmt = QAudioFormat()
            fmt.setSampleRate(24000)
            fmt.setChannelCount(2)  # headphones play a mono stream on the left only: send both channels
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt)
        self._sink = sink
        self._io = None
        self._pending = bytearray()
        self._carry = b""
        self._finishing = False
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._io = self._sink.start()
        self._timer.start()

    def write(self, data: bytes) -> None:
        """`data` is 16-bit mono PCM from ElevenLabs; the device gets it as stereo."""
        stereo, self._carry = mono_to_stereo(data, self._carry)
        self._pending += stereo
        self._flush()

    def finish(self) -> None:
        self._finishing = True

    def stop(self) -> None:
        self._timer.stop()
        self._pending.clear()
        self._carry = b""
        self._finishing = False
        self._sink.stop()

    def _flush(self) -> None:
        if self._io is None or not self._pending:
            return
        room = self._sink.bytesFree()
        if room > 0:
            written = self._io.write(bytes(self._pending[:room]))
            del self._pending[: max(written, 0)]

    def _tick(self) -> None:
        self._flush()
        if self._finishing and not self._pending and self._sink.state() != QAudio.State.ActiveState:
            self._timer.stop()
            self._finishing = False
            self.drained.emit()


class QtMicIn(QObject):
    """Captures 16 kHz mono 16-bit PCM from the default microphone, as raw chunks."""

    chunk = Signal(bytes)
    failed = Signal(str)

    def __init__(self, device: Any = None, source: Any = None) -> None:
        super().__init__()
        self._device = device
        self._source = source
        self._io: Any = None
        self._active = False

    def start(self) -> None:
        device = self._device or QMediaDevices.defaultAudioInput()
        fmt = QAudioFormat()
        fmt.setSampleRate(16000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if device.isNull():
            self.failed.emit("No microphone found")
            return
        if not device.isFormatSupported(fmt):
            self.failed.emit("The microphone does not support 16 kHz mono audio")
            return
        self._source = self._source or QAudioSource(device, fmt)
        self._io = self._source.start()
        if self._io is None:
            self.failed.emit("Could not open the microphone")
            return
        self._io.readyRead.connect(self._on_ready)
        self._active = True

    def stop(self) -> None:
        self._active = False
        if self._source is not None:
            self._source.stop()

    def _on_ready(self) -> None:
        if not self._active:
            return
        data = self._io.readAll().data()
        if data:
            self.chunk.emit(bytes(data))
