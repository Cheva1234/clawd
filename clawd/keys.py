"""Load the ElevenLabs burner key. The key is never logged, printed or put in an error message."""
import stat
from pathlib import Path

DEFAULT_KEY_PATH = Path.home() / ".config" / "cheva-clawd" / "secrets" / "elevenlabs.key"


class KeyFileError(Exception):
    """The key file is missing, unsafe or not filled in. The message never contains the key."""


def load_key(path: Path = DEFAULT_KEY_PATH) -> str:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        raise KeyFileError(f"key file missing: {path}") from None
    if mode & 0o077:
        raise KeyFileError(f"key file must be mode 0600 (found {oct(mode)}): {path}")
    try:
        key = path.read_text().strip()
    except OSError:
        raise KeyFileError(f"key file unreadable: {path}") from None
    if not key:
        raise KeyFileError(f"key file is empty: {path}")
    if key.startswith("REPLACE_ME"):
        raise KeyFileError(f"key not set yet: put your ElevenLabs key in {path}")
    return key
