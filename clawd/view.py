"""Pure: (state, session facts, time) -> what the panel shows."""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Literal

from clawd.format import short_target, spoken_text, stats_text, thinking_text, ticker_text, usage_text
from clawd.session import Session
from clawd.state import State

Accent = Literal["orange", "green", "yellow", "violet", "red", "dim", "blue"]
QUIET_AFTER = 15.0  # seconds without an event before "THINKING… N s" appears

_BADGE: dict[State, tuple[str, Accent]] = {
    "idle": ("IDLE", "dim"),
    "listening": ("LISTENING", "green"),
    "thinking": ("THINKING", "violet"),
    "working": ("WORKING", "orange"),
    "waiting": ("NEEDS YOU", "yellow"),
    "speaking": ("SPEAKING", "blue"),
    "error": ("FAILED", "red"),
    "done": ("DONE", "green"),
}


@dataclass(frozen=True)
class View:
    badge: str
    accent: Accent
    ticker: str | None = None
    headline: str | None = None
    body: str | None = None
    stats: str | None = None
    usage: str | None = None  # Claude's usage limits, one line
    usage_level: str | None = None  # ok, warn or high


def _live_stats(s: Session, now: float) -> str | None:
    seconds = None if s.turn_started is None else now - s.turn_started
    return stats_text(s.actions, len(s.files), seconds)


def _result(s: Session) -> tuple[str | None, str | None, str | None] | None:
    """The outcome of the last finished turn, kept on screen after the 'done' moment passes."""
    stats = stats_text(s.actions, len(s.files), s.turn_seconds)
    if s.outcome == "answer":
        return None, spoken_text(s.reply) or None, stats  # Claude's own words, no headline
    if s.outcome in ("error", "refusal"):
        return "That failed", "The turn ended with an error.", stats
    return None


def build_view(state: State, s: Session, now: float, wall: datetime | None = None) -> View:
    view = _build(state, s, now)
    usage = usage_text(s.limits, wall or datetime.now(timezone.utc))
    if usage:
        view = replace(view, usage=usage[0], usage_level=usage[1])
    if s.notice and state != "working":
        return replace(view, ticker=s.notice)
    return view


def _build(state: State, s: Session, now: float) -> View:
    badge, accent = _BADGE[state]
    if state == "working":
        return View(badge, accent, ticker=ticker_text(s.tool or "", s.target), stats=_live_stats(s, now))
    if state == "thinking":
        quiet = now - s.last_event
        ticker = thinking_text(quiet) if quiet >= QUIET_AFTER else None
        return View(badge, accent, ticker=ticker, stats=_live_stats(s, now))
    if state == "waiting":
        what = f"Claude wants to use {s.tool or 'a tool'}"
        target = short_target(s.tool or "", s.target, 60)
        return View(
            badge,
            accent,
            headline="Permission needed",
            body=f"{what}: {target}" if target else what,
            stats=f"waiting {int(now - s.state_since)} s · answer in the terminal",
        )
    result = _result(s)
    if result is None:
        return View(badge, accent)
    headline, body, stats = result
    return View(badge, accent, headline=headline, body=body, stats=stats)
