"""The phone call: a live mic, a local speech detector, one streaming session per stretch of speech.

Unmuted = live. Each stretch of speech becomes one session; its final text counts down (Cancel,
edit, Send) and is then submitted. Speech while Clawd talks is a barge-in (the app stops the voice).
"""
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from clawd.config import Config, load_config
from clawd.confirm import PendingRequest
from clawd.credits import DailyCap

LISTEN_USAGE_PATH = Path.home() / ".config" / "cheva-clawd" / "listen-usage.json"
_QUIET_RESULTS = ("I didn't catch that", "I didn't hear anything")  # noise, a cough, the TV: ignore silently
MAX_FAILURES = 3


class _UtteranceMic(QObject):
    """The 'microphone' one session reads from: the call pushes the detector's audio into it."""

    chunk = Signal(bytes)
    failed = Signal(str)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class _Session:
    def __init__(self, listener: Any, mic: _UtteranceMic):
        self.listener = listener
        self.mic = mic


class Call(QObject):
    transcript = Signal(str, bool)  # text, is_final
    pending = Signal(object, float)  # text (None = nothing pending), seconds left
    submit = Signal(str)  # approved text, for the session
    notice = Signal(str)
    live_changed = Signal(bool)
    speech_changed = Signal(bool)  # a stretch of speech is being heard / has ended
    barge_in = Signal()  # speech started: the app stops Clawd's voice
    auto_muted = Signal()  # the call muted itself (silence, failures, no mic)

    def __init__(
        self,
        mic: Any,
        gate: Any,
        listener_factory: Callable[[_UtteranceMic], Any],
        is_waiting: Callable[[], bool],
        countdown_secs: float = 1.5,
        interval_ms: int = 100,
        auto_mute_secs: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        super().__init__()
        self._mic = mic
        self._gate = gate
        self._factory = listener_factory
        self._is_waiting = is_waiting
        self._secs = countdown_secs
        self._interval = interval_ms
        self._auto_mute_secs = auto_mute_secs
        self._clock = clock
        self._live = False
        self._session: _Session | None = None  # the one receiving audio right now
        self._pending_sessions: set[_Session] = set()  # committed, waiting for their final text
        self._request: PendingRequest | None = None
        self._paused_for_speech = False
        self._failures = 0
        self._waiting_noticed = False
        self._last_voice = clock()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.tick)
        mic.chunk.connect(gate.feed)
        mic.failed.connect(self._on_mic_failed)
        gate.speech_started.connect(self._on_speech_started)
        gate.speech_chunk.connect(self._on_speech_chunk)
        gate.speech_ended.connect(self._on_speech_ended)

    # --- live / mute ----------------------------------------------------
    @property
    def live(self) -> bool:
        return self._live

    def set_live(self, on: bool) -> None:
        if on == self._live:
            return
        self._live = on
        if on:
            self._last_voice = self._clock()
            self._failures = 0
            self._mic.start()
            self._timer.start()
        else:
            self._timer.stop()
            self._mic.stop()
            self.cancel_all()
        self.live_changed.emit(on)

    def note_clawd_speaking(self) -> None:
        self._last_voice = self._clock()

    def tick(self) -> None:
        if self._live and self._clock() - self._last_voice >= self._auto_mute_secs:
            self._mute_myself(f"VOICE: muted after {int(self._auto_mute_secs // 60)} minutes of silence")

    def _mute_myself(self, message: str) -> None:
        self.notice.emit(message)
        self.set_live(False)
        self.auto_muted.emit()

    def _on_mic_failed(self, message: str) -> None:
        self._mute_myself(f"VOICE: {message}")

    # --- from the window ------------------------------------------------
    def send_pressed(self) -> None:
        if self._request is not None:
            self._request.send_now()

    def cancel_pressed(self) -> None:
        if self._request is not None:
            self._request.cancel()

    def edited(self, text: str) -> None:
        if self._request is not None:
            self._paused_for_speech = False
            self._request.edit(text)

    def set_waiting(self, waiting: bool) -> None:
        """While Claude waits on a permission prompt a request must not slip in: hold the countdown."""
        if not waiting:
            self._waiting_noticed = False
        if self._request is None:
            return
        if waiting:
            self._request.pause()
        elif not self._paused_for_speech:
            self._request.resume()

    def cancel_all(self) -> None:
        sessions = [s for s in (self._session, *self._pending_sessions) if s is not None]
        self._session = None
        self._pending_sessions = set()
        for session in sessions:
            session.listener.cancel()
        if sessions:
            self.speech_changed.emit(False)
        if self._request is not None:
            self._request.cancel()

    # --- from the detector ----------------------------------------------
    def _on_speech_started(self, preroll: bytes) -> None:
        if not self._live or self._session is not None:
            return
        self._last_voice = self._clock()
        if self._is_waiting():
            if not self._waiting_noticed:
                self._waiting_noticed = True
                self.notice.emit("VOICE: Claude is waiting for you. Answer in the terminal first.")
            return
        self.barge_in.emit()
        if self._request is not None:  # still talking: the countdown waits, the new words join the request
            self._request.pause()
            self._paused_for_speech = True
        mic = _UtteranceMic()
        listener = self._factory(mic)
        session = self._session = _Session(listener, mic)
        listener.partial.connect(lambda text, s=session: self._on_partial(s, text))
        listener.final.connect(lambda text, s=session: self._on_final(s, text))
        listener.failed.connect(lambda message, s=session: self._on_failed(s, message))
        listener.ended.connect(lambda s=session: self._on_ended(s))
        was_quiet = not self._pending_sessions
        listener.start()
        if not listener.active:  # it could not start (key, cap): its failure was already reported
            if self._session is session:
                self._session = None
            self._resume_after_speech()
            return
        mic.chunk.emit(preroll)
        if was_quiet:
            self.speech_changed.emit(True)

    def _on_speech_chunk(self, frame: bytes) -> None:
        if self._session is not None:
            self._session.mic.chunk.emit(frame)

    def _on_speech_ended(self) -> None:
        session = self._session
        if session is not None:
            self._session = None  # new speech may start a new session while this one waits for its text
            self._pending_sessions.add(session)
            session.listener.stop()  # commit by hand: no waiting for the server's silence

    # --- from a session -------------------------------------------------
    def _current(self, session: _Session) -> bool:
        return self._live and (session is self._session or session in self._pending_sessions)

    def _on_partial(self, session: _Session, text: str) -> None:
        if self._current(session):
            self.transcript.emit(text, False)

    def _on_final(self, session: _Session, text: str) -> None:
        if not self._current(session):
            return
        self._failures = 0
        self.transcript.emit(text, True)
        if self._request is not None:  # a continuation of the sentence still counting down
            self._paused_for_speech = False
            self._request.edit(f"{self._request.text} {text}")
            return
        request = self._request = PendingRequest(text, self._secs, self._interval)
        request.tick.connect(lambda left, r=request: self.pending.emit(r.text, left))
        request.sent.connect(lambda sent, r=request: self._done(r, sent))
        request.cancelled.connect(lambda r=request: self._done(r, None))
        request.start()
        if self._is_waiting():
            request.pause()

    def _on_failed(self, session: _Session, message: str) -> None:
        if not self._current(session):
            return
        self.transcript.emit("", True)
        if message in _QUIET_RESULTS:
            return
        self.notice.emit(f"VOICE: {message}")
        self._failures += 1
        if self._failures >= MAX_FAILURES:
            self._mute_myself(f"VOICE: muted after {MAX_FAILURES} failed tries in a row")

    def _on_ended(self, session: _Session) -> None:
        if session is self._session:
            self._session = None
        elif session in self._pending_sessions:
            self._pending_sessions.discard(session)
        else:
            return
        session.listener.deleteLater()
        if self._session is None and getattr(self._gate, "speaking", False):
            self._gate.reset()  # the detector missed the end of speech: without this the call stays deaf
        if self._session is None and not self._pending_sessions:
            self.speech_changed.emit(False)
            self._resume_after_speech()

    def _resume_after_speech(self) -> None:
        if self._paused_for_speech and self._request is not None:
            self._paused_for_speech = False
            if not self._is_waiting():
                self._request.resume()

    def _done(self, request: PendingRequest, text: str | None) -> None:
        if request is not self._request:
            return
        self._request = None
        self._paused_for_speech = False
        self.pending.emit(None, 0.0)
        if text is None:
            self.transcript.emit("", True)
        else:
            self.submit.emit(text)


def make_call(is_muted: Callable[[], bool], is_waiting: Callable[[], bool], config: Config | None = None) -> Call:
    """The real thing: the default mic, the local detector, ElevenLabs Scribe per stretch of speech."""
    from clawd.audio import QtMicIn
    from clawd.gate import SpeechGate
    from clawd.stt import Listener

    config = config or load_config()
    cap = DailyCap(LISTEN_USAGE_PATH, config.daily_listen_seconds)

    def listener_factory(utterance_mic: _UtteranceMic) -> Listener:
        return Listener(
            config, enabled=lambda: not is_muted(), mic_factory=lambda: utterance_mic, listen_cap=cap, no_speech_secs=6.0
        )

    return Call(QtMicIn(), SpeechGate(), listener_factory, is_waiting, countdown_secs=config.countdown_secs)
