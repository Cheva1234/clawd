"""Speaks short text through ElevenLabs, streaming PCM to the speakers. One utterance at a time."""
import threading
from collections.abc import Callable
from typing import Any

import httpx
from PySide6.QtCore import QObject, Signal

from clawd.config import Config
from clawd.credits import DailyCap
from clawd.keys import KeyFileError, load_key

API = "https://api.elevenlabs.io"
MAX_SPOKEN_CHARS = 400


def _http_message(status: int) -> str:
    if status in (401, 403):
        return f"ElevenLabs rejected the key ({status})"
    if status == 429:
        return "ElevenLabs rate limit reached (429)"
    return f"ElevenLabs error ({status})"


class Speaker(QObject):
    started = Signal()
    finished = Signal()
    failed = Signal(str)
    _chunk = Signal(int, bytes)
    _ok = Signal(int, int)
    _error = Signal(int, str)
    _done = Signal(int)

    def __init__(
        self,
        config: Config,
        cap: DailyCap,
        enabled: Callable[[], bool],
        client: httpx.Client | None = None,
        out_factory: Callable[[], Any] | None = None,
        key_loader: Callable[[], str] = load_key,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._config = config
        self._cap = cap
        self._enabled = enabled
        self._client = client or httpx.Client(timeout=httpx.Timeout(20.0, read=30.0))
        self._out_factory = out_factory or self._default_out
        self._key_loader = key_loader
        self._gen = 0
        self._out: Any = None
        self._speaking = False
        self._chunk.connect(self._on_chunk)
        self._ok.connect(self._on_ok)
        self._error.connect(self._on_error)
        self._done.connect(self._on_done)

    @staticmethod
    def _default_out() -> Any:
        from clawd.audio import QtAudioOut

        return QtAudioOut()

    # --- public ---------------------------------------------------------
    def speak(self, text: str) -> None:
        text = text.strip()[:MAX_SPOKEN_CHARS]
        if not text or not self._enabled():
            return  # closed, muted or nothing to say: no call, no spend
        try:
            key = self._key_loader()
        except KeyFileError as err:
            self.failed.emit(str(err))
            return
        if not self._cap.allow(len(text)):
            self.failed.emit("daily voice limit reached")
            return
        self.stop()  # cut whatever is still playing
        gen = self._gen
        out = self._out = self._out_factory()
        out.drained.connect(lambda g=gen: self._on_drained(g))
        threading.Thread(target=self._run, args=(gen, key, text), daemon=True).start()

    def stop(self) -> None:
        self._gen += 1
        out, self._out = self._out, None
        if out is not None:
            out.stop()
        if self._speaking:
            self._speaking = False
            self.finished.emit()

    # --- worker thread --------------------------------------------------
    def _run(self, gen: int, key: str, text: str) -> None:
        url = f"{API}/v1/text-to-speech/{self._config.voice_id}/stream"
        try:
            with self._client.stream(
                "POST",
                url,
                params={"output_format": "pcm_24000"},
                headers={"xi-api-key": key},
                json={"text": text, "model_id": self._config.model_id},
            ) as response:
                if response.status_code != 200:
                    self._error.emit(gen, _http_message(response.status_code))
                    return
                self._ok.emit(gen, len(text))
                for chunk in response.iter_bytes():
                    if gen != self._gen:
                        return
                    self._chunk.emit(gen, chunk)
            self._done.emit(gen)
        except httpx.HTTPError:
            self._error.emit(gen, "network error: cannot reach ElevenLabs")
        except Exception as err:  # never let a worker thread die silently
            self._error.emit(gen, f"voice error: {type(err).__name__}")

    # --- main thread ----------------------------------------------------
    def _on_ok(self, gen: int, n: int) -> None:
        if gen != self._gen or self._out is None:
            return
        self._cap.record(n)
        self._out.start()
        self._speaking = True
        self.started.emit()

    def _on_chunk(self, gen: int, data: bytes) -> None:
        if gen == self._gen and self._out is not None:
            self._out.write(data)

    def _on_error(self, gen: int, message: str) -> None:
        if gen != self._gen:
            return
        self.stop()
        self.failed.emit(message)

    def _on_done(self, gen: int) -> None:
        if gen == self._gen and self._out is not None:
            self._out.finish()

    def _on_drained(self, gen: int) -> None:
        if gen == self._gen and self._speaking:
            self._speaking = False
            self.finished.emit()
