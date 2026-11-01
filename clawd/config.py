"""User settings with safe defaults. No secrets here: the key lives in its own 0600 file."""
import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "cheva-clawd" / "config.json"


@dataclass(frozen=True)
class Config:
    voice_id: str = "JBFqnCBsd6RMkjVDRZzb"  # George, a standard ElevenLabs voice: works with any account
    model_id: str = "eleven_flash_v2_5"
    daily_chars: int = 8000
    daily_listen_seconds: int = 1800
    countdown_secs: float = 1.5  # how long a heard request waits, with Cancel, before it is sent


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return Config()
    except (OSError, ValueError):
        return Config()
    base = Config()
    voice = data.get("voice_id")
    model = data.get("model_id")
    chars = data.get("daily_chars")
    secs = data.get("daily_listen_seconds")
    countdown = data.get("countdown_secs")
    return Config(
        voice_id=voice if isinstance(voice, str) and voice else base.voice_id,
        model_id=model if isinstance(model, str) and model else base.model_id,
        daily_chars=chars if isinstance(chars, int) and not isinstance(chars, bool) and chars > 0 else base.daily_chars,
        countdown_secs=(
            float(countdown)
            if isinstance(countdown, (int, float)) and not isinstance(countdown, bool) and 0 < countdown <= 10
            else base.countdown_secs
        ),
        daily_listen_seconds=secs if isinstance(secs, int) and not isinstance(secs, bool) and secs > 0 else base.daily_listen_seconds,
    )
