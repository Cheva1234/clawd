"""What we know about the Claude Code session, counted from its events (no GUI, no timers)."""
from dataclasses import dataclass, field

EDIT_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}


@dataclass
class Session:
    project: str = ""
    tool: str | None = None
    target: str | None = None
    actions: int = 0
    files: set[str] = field(default_factory=set)
    turn_started: float | None = None
    turn_seconds: float | None = None
    last_event: float = 0.0
    state_since: float = 0.0
    reply: str = ""
    outcome: str | None = None  # how the last turn ended: answer, error, refusal, aborted
    notice: str | None = None  # a one-line message for the ticker (for example a voice problem)

    def on_event(self, event: dict, now: float) -> None:
        kind = event.get("kind")
        self.last_event = now
        if kind == "turn.start":
            self.actions, self.files = 0, set()
            self.turn_started, self.turn_seconds = now, None
            self.tool = self.target = None
            self.reply, self.outcome, self.notice = "", None, None
        elif kind == "tool.call":
            self.actions += 1
            self.tool, self.target = event.get("tool"), event.get("target")
            if self.tool in EDIT_TOOLS and self.target:
                self.files.add(self.target)
        elif kind == "turn.complete":
            self.reply = event.get("text") or ""
            self.outcome = event.get("reason")
            if self.turn_started is not None:
                self.turn_seconds = now - self.turn_started

    def set_state_since(self, now: float) -> None:
        self.state_since = now
