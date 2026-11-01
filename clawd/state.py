"""Pure state machine: session/app events -> Clawd's animation state."""
from typing import Literal, NotRequired, TypedDict

State = Literal[
    "idle", "listening", "thinking", "working", "waiting", "speaking", "error", "done"
]


class Event(TypedDict):
    kind: str
    tool: NotRequired[str]
    reason: NotRequired[str]
    text: NotRequired[str]


STATUS_LINE: dict[State, str] = {
    "idle": "idle",
    "listening": "listening…",
    "thinking": "thinking…",
    "working": "working…",
    "waiting": "waiting for you",
    "speaking": "speaking…",
    "error": "something went wrong",
    "done": "done",
}


def status_line(state: State, tool: str | None = None) -> str:
    if state == "working" and tool:
        return f"running {tool}"
    return STATUS_LINE[state]


def next_state(current: State, event: Event) -> State:
    kind = event["kind"]
    if kind == "turn.start":
        return "thinking"
    if kind == "tool.call":
        return "working"
    if kind == "tool.done":
        return "thinking"
    if kind == "waiting.timeout":
        return "waiting" if current == "working" else current
    if kind == "turn.complete":
        reason = event.get("reason")
        if reason == "answer":
            return "done"
        if reason in ("error", "refusal"):
            return "error"
        return "idle"
    if kind == "done.timeout":
        return "idle" if current == "done" else current
    if kind == "app.error":
        return "error"
    if kind == "error.timeout":
        return "idle" if current == "error" else current
    if kind == "mic.start":
        return current if current in ("thinking", "working", "waiting") else "listening"
    if kind == "mic.stop":
        return "idle" if current == "listening" else current
    if kind == "speak.start":
        return "speaking"
    if kind == "speak.end":
        return "idle" if current == "speaking" else current
    return current
