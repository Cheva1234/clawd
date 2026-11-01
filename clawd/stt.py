"""Click-to-talk speech input: mic audio -> ElevenLabs Scribe realtime -> partial and final text.

One utterance per `start()`. The local detector ends it and `stop()` commits by hand (manual commit).
"""
import asyncio
import base64
import json
import queue
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from PySide6.QtCore import QObject, Signal
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from clawd.config import Config
from clawd.credits import DailyCap
from clawd.keys import KeyFileError, load_key

BASE_URL = "wss://api.elevenlabs.io"
_COMMIT = object()  # queue marker: the user pressed stop


class _Session:
    def __init__(self, gen: int):
        self.gen = gen
        self.chunks: queue.SimpleQueue = queue.SimpleQueue()
        self.abort = threading.Event()
        self.commit_at: float | None = None
        self.auto_committed = False
        self.started = time.monotonic()


class Listener(QObject):
    partial = Signal(str)
    final = Signal(str)
    failed = Signal(str)
    ended = Signal()
    _event = Signal(int, str, str)  # generation, kind, text (worker thread -> main thread)

    def __init__(
        self,
        config: Config,
        enabled: Callable[[], bool],
        key_loader: Callable[[], str] = load_key,
        mic_factory: Callable[[], Any] | None = None,
        base_url: str = BASE_URL,
        listen_cap: DailyCap | None = None,
        no_speech_secs: float = 12.0,
        max_secs: float = 30.0,
        commit_wait_secs: float = 4.0,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._config = config
        self._enabled = enabled
        self._key_loader = key_loader
        self._mic_factory = mic_factory or self._default_mic
        self._base_url = base_url
        self._cap = listen_cap
        self._no_speech = no_speech_secs
        self._max = max_secs
        self._commit_wait = commit_wait_secs
        self._gen = 0
        self._active = False
        self._mic: Any = None
        self._session: _Session | None = None
        self._event.connect(self._on_event)

    @staticmethod
    def _default_mic() -> Any:
        from clawd.audio import QtMicIn

        return QtMicIn()

    @property
    def active(self) -> bool:
        return self._active

    # --- public ---------------------------------------------------------
    def start(self) -> None:
        if self._active or not self._enabled():
            return  # busy, muted or closed: no mic, no connection, no spend
        try:
            key = self._key_loader()
        except KeyFileError as err:
            self.failed.emit(str(err))
            return
        if self._cap is not None and not self._cap.allow(1):
            self.failed.emit("daily listening limit reached")
            return
        self._gen += 1
        gen = self._gen
        self._active = True
        session = self._session = _Session(gen)
        mic = self._mic = self._mic_factory()
        mic.chunk.connect(lambda data, s=session: s.chunks.put(bytes(data)))
        mic.failed.connect(lambda message, g=gen: self._finish(g, failed=message))
        mic.start()
        if not self._active:  # the mic failed to open: nothing else to do
            return
        threading.Thread(target=self._run, args=(session, key), daemon=True).start()

    def stop(self) -> None:
        """The user is done talking: commit what was heard and wait for the final text."""
        if self._active and self._session is not None:
            if self._mic is not None:
                self._mic.stop()
            self._session.chunks.put(_COMMIT)

    def cancel(self) -> None:
        """Throw everything away (muted, closed, new action). Emits `ended` once, nothing else."""
        self._finish(self._gen, quiet=True)

    # --- worker thread --------------------------------------------------
    def _post(self, gen: int, kind: str, text: str) -> None:
        try:
            self._event.emit(gen, kind, text)
        except RuntimeError:
            pass  # the call already released this listener: nobody is waiting for the event

    def _run(self, session: _Session, key: str) -> None:
        try:
            asyncio.run(self._talk(session, key))
        except Exception as err:
            self._post(session.gen, "failed", f"voice input error: {type(err).__name__}")
        finally:
            self._post(session.gen, "done", "")

    async def _talk(self, session: _Session, key: str) -> None:
        params = {
            "model_id": "scribe_v2_realtime",
            "audio_format": "pcm_16000",
            "commit_strategy": "manual",  # the local detector decides when a sentence ends, then commits
            "language_code": "en",
            "no_verbatim": "true",  # no false starts or "uh" in what the user said
        }
        url = f"{self._base_url}/v1/speech-to-text/realtime?{urlencode(params)}"
        try:
            async with connect(url, additional_headers={"xi-api-key": key}, open_timeout=10, max_size=None) as ws:
                sender = asyncio.create_task(self._send(ws, session))
                try:
                    await self._receive(ws, session)
                finally:
                    sender.cancel()
        except InvalidStatus as err:
            code = err.response.status_code
            if code in (401, 403):
                self._post(session.gen, "failed", f"ElevenLabs rejected the key ({code})")
            elif code == 429:
                self._post(session.gen, "failed", "ElevenLabs rate limit reached (429)")
            else:
                self._post(session.gen, "failed", f"ElevenLabs error ({code})")
        except (OSError, TimeoutError):
            self._post(session.gen, "failed", "network error: cannot reach ElevenLabs")

    async def _send(self, ws: Any, session: _Session) -> None:
        while not session.abort.is_set():
            try:
                item = session.chunks.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.02)
                continue
            if item is _COMMIT:
                session.commit_at = time.monotonic()
                # the SDK's way to commit by hand: an empty audio chunk with commit=true
                await ws.send(
                    json.dumps(
                        {"message_type": "input_audio_chunk", "audio_base_64": "", "commit": True, "sample_rate": 16000}
                    )
                )
                continue
            await ws.send(
                json.dumps(
                    {
                        "message_type": "input_audio_chunk",
                        "audio_base_64": base64.b64encode(item).decode(),
                        "commit": False,
                        "sample_rate": 16000,
                    }
                )
            )

    async def _receive(self, ws: Any, session: _Session) -> None:
        heard = False
        while not session.abort.is_set():
            now = time.monotonic()
            if now - session.started > self._max and not session.auto_committed:
                session.auto_committed = True  # a very long monologue: commit what was heard, do not lose it
                session.chunks.put(_COMMIT)
            if not heard and now - session.started > self._no_speech:
                self._post(session.gen, "failed", "I didn't hear anything")
                return
            if session.commit_at is not None and now - session.commit_at > self._commit_wait:
                self._post(session.gen, "failed", "I didn't catch that")
                return
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.1)
            except TimeoutError:
                continue
            event = json.loads(raw)
            kind = event.get("message_type")
            text = event.get("text") or ""
            if kind == "partial_transcript":
                heard = heard or bool(text.strip())
                self._post(session.gen, "partial", text)
            elif kind == "committed_transcript":
                if text.strip():
                    self._post(session.gen, "final", text.strip())
                else:
                    self._post(session.gen, "failed", "I didn't catch that")
                return
            elif kind in ("error", "invalid_request", "auth_error", "quota_exceeded", "rate_limited"):
                self._post(session.gen, "failed", f"voice input error: {kind}")
                return

    # --- main thread ----------------------------------------------------
    def _on_event(self, gen: int, kind: str, text: str) -> None:
        if gen != self._gen or not self._active:
            return
        if kind == "partial":
            self.partial.emit(text)
        elif kind == "final":
            self.final.emit(text)
            self._finish(gen)
        elif kind == "failed":
            self._finish(gen, failed=text)
        elif kind == "done":
            self._finish(gen)

    def _finish(self, gen: int, failed: str | None = None, quiet: bool = False) -> None:
        if gen != self._gen or not self._active:
            return
        self._active = False
        session, self._session = self._session, None
        if session is not None:
            session.abort.set()
            if self._cap is not None:
                self._cap.record(max(1, round(time.monotonic() - session.started)))
        if self._mic is not None:
            self._mic.stop()
        if not quiet:
            if failed:
                self.failed.emit(failed)
        self.ended.emit()
