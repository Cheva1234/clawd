"""Turns raw session events into Clawd's state, with the timers the state machine cannot have."""
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from clawd.session import Session
from clawd.state import Event, State, next_state
from clawd.view import View, build_view


class Controller(QObject):
    state_changed = Signal(str, object)  # state, tool name or None
    muted_changed = Signal(bool)
    quit_requested = Signal()
    view_changed = Signal(object)  # a View: what the panel should show

    def __init__(
        self,
        waiting_debounce: float = 1.0,
        done_hold: float = 2.5,
        error_hold: float = 3.0,
        now: Callable[[], float] = time.monotonic,
        tick_ms: int = 1000,
    ):
        super().__init__()
        self._now = now
        self.session = Session()
        self.view: View = build_view("idle", self.session, now())
        self._tick = QTimer(self)
        self._tick.setInterval(tick_ms)
        self._tick.timeout.connect(self.tick)
        self.state: State = "idle"
        self.tool: str | None = None
        self.muted = False
        self._waiting = self._timer(waiting_debounce, "waiting.timeout")
        self._done = self._timer(done_hold, "done.timeout")
        self._error = self._timer(error_hold, "error.timeout")

    def _timer(self, seconds: float, kind: str) -> QTimer:
        t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(max(1, int(seconds * 1000)))
        t.timeout.connect(lambda: self._apply({"kind": kind}))
        return t

    def handle(self, event: Event | dict) -> None:
        kind = event.get("kind")
        if kind == "mute" or kind == "unmute":
            self.muted = kind == "mute"
            self.muted_changed.emit(self.muted)
            return
        if kind == "quit":
            self.quit_requested.emit()
            return
        if kind == "notice":
            self.set_notice(event.get("text"))
            return
        self.session.on_event(event, self._now())
        if kind == "turn.start":
            self._tick.start()
        elif kind == "turn.complete":
            self._tick.stop()
        if kind == "permission":
            # fires on every tool call, even ones that run without asking: only a tool
            # still not finished after the debounce counts as waiting for the user
            self._waiting.start()
            self.refresh()
            return
        if kind == "notification":
            if event.get("type") == "permission_prompt":
                self._waiting.stop()
                self._apply({"kind": "waiting.timeout"})
            self.refresh()
            return
        if kind in ("tool.done", "turn.start", "turn.complete"):
            self._waiting.stop()
        self._apply(event)  # type: ignore[arg-type]
        self.refresh()

    def _apply(self, event: Event) -> None:
        new = next_state(self.state, event)
        tool = event.get("tool") if event["kind"] == "tool.call" else (self.tool if new == "working" else None)
        if new == self.state and tool == self.tool:
            return
        if new != self.state:
            self.session.set_state_since(self._now())
        self.state, self.tool = new, tool
        if new == "done":
            self._done.start()
        elif new == "error":
            self._error.start()
        self.state_changed.emit(new, tool)
        self.refresh()

    # --- the panel's view -------------------------------------------------
    def refresh(self) -> None:
        view = build_view(self.state, self.session, self._now())
        if view != self.view:
            self.view = view
            self.view_changed.emit(view)

    def tick(self) -> None:
        self.refresh()

    def tick_active(self) -> bool:
        return self._tick.isActive()

    def set_project(self, name: str) -> None:
        self.session.project = name

    def set_notice(self, text: str | None) -> None:
        self.session.notice = text
        self.refresh()
