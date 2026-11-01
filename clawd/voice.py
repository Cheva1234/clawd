"""Speaks Claude's own words after a reply, honouring mute and new turns."""
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from clawd.config import Config, load_config
from clawd.credits import DailyCap
from clawd.format import spoken_text
from clawd.tts import Speaker

USAGE_PATH = Path.home() / ".config" / "cheva-clawd" / "voice-usage.json"


class VoiceOut(QObject):
    speech_started = Signal()
    speech_ended = Signal()
    notice = Signal(str)

    def __init__(self, speaker: Any):
        super().__init__()
        self._speaker = speaker
        self._muted = False
        speaker.started.connect(self.speech_started)
        speaker.finished.connect(self.speech_ended)
        speaker.failed.connect(lambda message: self.notice.emit(f"VOICE: {message}"))

    def on_turn_complete(self, reply: str) -> None:
        text = spoken_text(reply)
        if self._muted or not text:
            return  # muted or nothing worth saying: no call, no spend
        self._speaker.speak(text)

    def on_turn_start(self) -> None:
        self._speaker.stop()

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        if muted:
            self._speaker.stop()

    def stop(self) -> None:
        self._speaker.stop()


def make_voice(is_muted: Callable[[], bool], config: Config | None = None) -> VoiceOut:
    """The real thing: ElevenLabs speech with a daily character cap."""
    config = config or load_config()
    cap = DailyCap(USAGE_PATH, config.daily_chars)
    return VoiceOut(Speaker(config, cap, enabled=lambda: not is_muted()))
