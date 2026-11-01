"""The countdown between 'Clawd heard you' and 'the request goes to Claude'. Nothing is sent until it ends."""
import time

from PySide6.QtCore import QObject, QTimer, Signal


class PendingRequest(QObject):
    tick = Signal(float)  # seconds left
    sent = Signal(str)
    cancelled = Signal()

    def __init__(self, text: str, seconds: float = 3.0, interval_ms: int = 100):
        super().__init__()
        self._text = text
        self._seconds = seconds
        self._deadline = 0.0
        self._left = seconds  # remembered while paused
        self._done = False
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._on_timer)

    @property
    def text(self) -> str:
        return self._text

    def start(self) -> None:
        if self._done:
            return
        if not self._text.strip():
            self.cancel()
            return
        self._restart(self._seconds)

    def cancel(self) -> None:
        if self._done:
            return
        self._done = True
        self._timer.stop()
        self.cancelled.emit()

    def send_now(self) -> None:
        if self._done:
            return
        self._done = True
        self._timer.stop()
        self.sent.emit(self._text)

    def edit(self, text: str) -> None:
        if self._done:
            return
        self._text = text
        if not text.strip():
            self.cancel()
        else:
            self._restart(self._seconds)  # a changed request gets a fresh countdown

    def pause(self) -> None:
        if self._done or not self._timer.isActive():
            return
        self._left = max(0.0, self._deadline - time.monotonic())
        self._timer.stop()

    def resume(self) -> None:
        if self._done or self._timer.isActive():
            return
        self._restart(self._left)

    def _restart(self, seconds: float) -> None:
        self._deadline = time.monotonic() + seconds
        self._timer.start()
        self.tick.emit(seconds)

    def _on_timer(self) -> None:
        left = self._deadline - time.monotonic()
        self.tick.emit(max(left, 0.0))
        if left <= 0:
            self.send_now()
