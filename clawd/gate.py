"""A small, local speech detector: decides when someone is talking, so only speech is streamed out.

Energy based, plain Python: follows the background noise level (slowly up, quickly down), calls
a stretch of 20 ms frames "speech" once about 150 ms of it is clearly louder than the background,
hands over the 300 ms before that (so the first word is not clipped), and ends after 700 ms of quiet.
It is weaker than a neural detector in a noisy room; the countdown and the server's own detection
are the safety net.

Built for noisy rooms (a USB mic with a loud background and bursts):
- the background level is the quietest fifth of the last 2 seconds, so noise bursts and talking do not raise it;
- the end of speech is judged on a smoothed level against a fraction of how loud the speaker is, and a
  burst only pushes the end back a little instead of restarting the wait;
- an utterance cannot last longer than 25 s, and `reset()` lets whoever feeds the gate recover it.
"""
import math
from array import array
from collections import deque
from statistics import fmean

from PySide6.QtCore import QObject, Signal

FRAME_MS = 20
SAMPLE_RATE = 16000
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2  # 16-bit mono
MIN_RMS = 150.0  # never call anything quieter than this speech
FACTOR = 3.0  # speech is this many times louder than the background
RISE = 0.02  # how fast the background estimate follows a louder room
FALL = 0.2  # ...and a quieter one
END_FRACTION = 0.25  # speech has ended when the (smoothed) level falls below this fraction of how loud it was
END_FLOOR_FACTOR = 2.0  # ...but never below this many times the background
SMOOTH_FRAMES = 4  # the end of speech is judged on the average of the last 80 ms
RECENT_FRAMES = 100  # 2 s of levels: the background is their quietest fifth
MAX_SPEECH_FRAMES = 1250  # 25 s: a longer utterance is cut (the listening session limit is 30 s)


def rms(frame: bytes) -> float:
    n = len(frame) // 2
    if not n:
        return 0.0
    samples = array("h")
    samples.frombytes(frame[: n * 2])
    return math.sqrt(sum(x * x for x in samples) / n)


class SpeechGate(QObject):
    speech_started = Signal(bytes)  # the preroll (about 300 ms before) plus the first 150 ms of speech
    speech_chunk = Signal(bytes)  # every 20 ms frame while speech goes on
    speech_ended = Signal()

    def __init__(self, sample_rate: int = SAMPLE_RATE, start_ms: int = 150, preroll_ms: int = 300, end_ms: int = 700):
        super().__init__()
        self._frame_bytes = sample_rate * FRAME_MS // 1000 * 2
        self._start_frames = math.ceil(start_ms / FRAME_MS)
        self._end_frames = end_ms // FRAME_MS
        self._ring: deque[bytes] = deque(maxlen=preroll_ms // FRAME_MS + self._start_frames)
        self._recent: deque[float] = deque(maxlen=RECENT_FRAMES)
        self._smooth: deque[float] = deque(maxlen=SMOOTH_FRAMES)
        self._buf = bytearray()
        self._floor: float | None = None
        self._loud_run = 0
        self._quiet_run = 0
        self._speech_level = 0.0
        self._speech_frames = 0
        self._speaking = False

    @property
    def speaking(self) -> bool:
        return self._speaking

    def reset(self) -> None:
        """Back to listening for a new start, e.g. when the caller sees it stuck. Emits nothing."""
        self._speaking = False
        self._loud_run = self._quiet_run = self._speech_frames = 0
        self._speech_level = 0.0
        self._ring.clear()
        self._smooth.clear()

    def feed(self, data: bytes) -> None:
        self._buf += data
        while len(self._buf) >= self._frame_bytes:
            frame = bytes(self._buf[: self._frame_bytes])
            del self._buf[: self._frame_bytes]
            self._process(frame)

    def _learn_background(self, level: float) -> float:
        self._recent.append(level)
        target = sorted(self._recent)[len(self._recent) // 5]
        if self._floor is None:
            self._floor = max(target, 1.0)
        elif target < self._floor:
            self._floor += (target - self._floor) * FALL
        elif not self._speaking:  # speech never raises the background
            self._floor += (target - self._floor) * RISE
        return self._floor

    def _process(self, frame: bytes) -> None:
        level = rms(frame)
        floor = self._learn_background(level)
        threshold = max(floor * FACTOR, MIN_RMS)
        if not self._speaking:
            self._ring.append(frame)
            self._loud_run = self._loud_run + 1 if level > threshold else 0
            if self._loud_run >= self._start_frames:
                self._speaking = True
                self._quiet_run = self._speech_frames = 0
                recent_loud = list(self._recent)[-self._start_frames :]
                self._speech_level = fmean(recent_loud)
                self._smooth.clear()
                started = b"".join(self._ring)
                self._ring.clear()
                self.speech_started.emit(started)
            return
        self.speech_chunk.emit(frame)
        self._speech_frames += 1
        if level > threshold:
            self._speech_level += (level - self._speech_level) * 0.1
        self._smooth.append(level)
        end_threshold = max(floor * END_FLOOR_FACTOR, self._speech_level * END_FRACTION, MIN_RMS * 0.5)
        if fmean(self._smooth) < end_threshold:
            self._quiet_run += 1
        else:
            self._quiet_run = max(0, self._quiet_run - 2)  # a burst pushes the end back, it does not restart the wait
        if self._quiet_run >= self._end_frames or self._speech_frames >= MAX_SPEECH_FRAMES:
            self.reset()
            self.speech_ended.emit()
