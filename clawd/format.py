"""Small, pure text helpers for the panel: ticker, stats line, thinking counter, fallback summary."""
import re
from datetime import datetime, timedelta, timezone, tzinfo

_VERBS = {
    "Edit": "EDITS",
    "MultiEdit": "EDITS",
    "NotebookEdit": "EDITS",
    "Write": "WRITES",
    "Read": "READS",
    "Bash": "RUNS",
    "Grep": "SEARCHES",
    "Glob": "FINDS",
    "WebFetch": "FETCHES",
    "WebSearch": "SEARCHES WEB",
    "Task": "DELEGATES",
    "Agent": "DELEGATES",
}
_FILE_TOOLS = {"Edit", "MultiEdit", "NotebookEdit", "Write", "Read"}
_TARGET_MAX = 32
SPOKEN_MAX = 300
FULL_ANSWER_NOTE = "The full answer is in the terminal."


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def short_target(tool: str, target: str | None, limit: int = _TARGET_MAX) -> str:
    """One short line naming what a tool call works on (a file's name, a command, a pattern)."""
    text = (target or "").strip().split("\n")[0].strip()
    if tool in _FILE_TOOLS:
        text = text.rsplit("/", 1)[-1]
    return _clip(text, limit)


def ticker_text(tool: str, target: str | None) -> str:
    verb = _VERBS.get(tool, tool.upper())
    text = short_target(tool, target)
    return f"{verb} {text}" if text else verb


def duration_text(seconds: float) -> str:
    whole = round(seconds)
    if whole < 60:
        return f"{whole} s"
    minutes, rest = divmod(whole, 60)
    return f"{minutes}m {rest:02d}s"


def stats_text(actions: int, files: int, seconds: float | None) -> str | None:
    parts = []
    if actions:
        parts.append(f"{actions} action{'s' if actions != 1 else ''}")
    if files:
        parts.append(f"{files} file{'s' if files != 1 else ''} changed")
    if seconds is not None:
        parts.append(duration_text(seconds))
    return " · ".join(parts) if parts else None


def thinking_text(seconds: float) -> str:
    return f"THINKING… {int(seconds)} s"


def plain_text(text: str) -> str:
    """Claude's reply as plain words: markdown, code blocks and list markers removed, one line."""
    plain = re.sub(r"```.*?```", " ", text, flags=re.S)
    plain = re.sub(r"`([^`]*)`", r"\1", plain)
    plain = re.sub(r"(\*\*|__)(.*?)\1", r"\2", plain)
    plain = re.sub(r"^\s*#+\s*", "", plain, flags=re.M)
    plain = re.sub(r"^\s*[-*+]\s+", "", plain, flags=re.M)
    return re.sub(r"\s+", " ", plain).strip()


def spoken_text(reply: str, limit: int = SPOKEN_MAX) -> str:
    """What Clawd shows and says: the reply's own words, never a rewrite.

    Short replies whole; longer ones the first whole sentences that fit, then a pointer to the terminal.
    """
    plain = plain_text(reply)
    if len(plain) <= limit:
        return plain
    kept = ""
    for sentence in re.split(r"(?<=[.!?])\s+", plain):
        candidate = f"{kept} {sentence}".strip()
        if len(candidate) > limit:
            break
        kept = candidate
    if not kept:  # the very first sentence is longer than the limit: cut it at a word
        kept = plain[: limit - 1].rsplit(" ", 1)[0] + "…"
    return f"{kept} {FULL_ANSWER_NOTE}"


_WINDOWS = {"five_hour": "5h", "seven_day": "week", "spend_limit": "spend"}


_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")  # not strftime: Qt switches the locale (Thai, say)


def _clock_text(moment: datetime) -> str:
    hour = moment.hour % 12 or 12
    minutes = f":{moment.minute:02d}" if moment.minute else ""
    return f"{_WEEKDAYS[moment.weekday()]} {hour}{minutes} {'am' if moment.hour < 12 else 'pm'}"


def _reset_text(resets_at: object, wall: datetime, tz: tzinfo | None) -> str:
    if not isinstance(resets_at, str):
        return ""
    try:
        moment = datetime.fromisoformat(resets_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    left = moment - wall
    if left <= timedelta(0):
        return ""
    minutes = int(left.total_seconds() // 60)
    if minutes < 60:
        return f"in {minutes}m"
    if left < timedelta(hours=24):
        hours, rest = divmod(minutes, 60)
        return f"in {hours}h {rest}m" if rest else f"in {hours}h"
    return _clock_text(moment.astimezone(tz))


def usage_text(limits: object, wall: datetime | None = None, tz: tzinfo | None = None) -> tuple[str, str] | None:
    """`Claude 5h 34% · week 82% · resets Mon 1 pm` and how worried to look: ok, warn (80%) or high (95%)."""
    wall = wall or datetime.now(timezone.utc)
    parts: list[str] = []
    busiest: tuple[float, object] | None = None
    for item in limits if isinstance(limits, list) else []:
        if not isinstance(item, dict):
            continue
        label, percent = _WINDOWS.get(item.get("kind", "")), item.get("percentUsed")
        if label is None or not isinstance(percent, (int, float)) or isinstance(percent, bool):
            continue
        parts.append(f"{label} {percent:.0f}%")
        if busiest is None or percent > busiest[0]:
            busiest = (percent, item.get("resetsAt"))
    if busiest is None:
        return None
    text = "Claude " + " · ".join(parts)
    reset = _reset_text(busiest[1], wall, tz)
    if reset:
        text += f" · resets {reset}"
    return text, "high" if busiest[0] >= 95 else "warn" if busiest[0] >= 80 else "ok"
