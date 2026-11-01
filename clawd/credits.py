"""A daily cap on spoken characters, so a chatty session can never run up the ElevenLabs bill."""
import json
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path


class DailyCap:
    def __init__(self, path: Path, max_chars: int, today: Callable[[], str] = lambda: date.today().isoformat()):
        self._path = path
        self._max = max_chars
        self._today = today

    def used(self) -> int:
        try:
            data = json.loads(self._path.read_text())
            if data.get("date") == self._today() and isinstance(data.get("used"), int):
                return max(0, data["used"])
        except (OSError, ValueError, AttributeError):
            pass
        return 0

    def allow(self, n: int) -> bool:
        return self.used() + n <= self._max

    def record(self, n: int) -> None:
        data = {"date": self._today(), "used": self.used() + n}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, self._path)
        except OSError:
            pass  # the cap is best effort; a full disk must not break the pet
