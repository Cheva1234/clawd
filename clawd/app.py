"""Wires the pieces together: socket -> controller -> window, window -> plugin."""
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from clawd.controller import Controller
from clawd.ipc import EventServer, ParentWatchdog, emit_command
from clawd.window import ClawdWindow


@dataclass
class Runtime:
    path: str
    window: ClawdWindow
    controller: Controller
    server: EventServer
    watchdog: ParentWatchdog | None


def build(
    socket_path: str,
    out: TextIO | None = None,
    state_path: Path | None = None,
    on_quit: Callable[[], None] | None = None,
    watch_parent: bool = True,
    project: str = "",
    voice_factory: Callable[[Callable[[], bool]], Any] | None = None,
    call_factory: Callable[[Callable[[], bool], Callable[[], bool]], Any] | None = None,
) -> Runtime:
    """Create and connect everything. Raises `AlreadyRunning` if another Clawd owns the socket."""
    quit_app = on_quit or (lambda: None)
    out = out or sys.stdout

    server = EventServer()
    server.start(socket_path)  # first, so a second instance fails before drawing anything

    window = ClawdWindow(state_path=state_path)
    controller = Controller()
    controller.setParent(window)  # its timers must not outlive the window
    server.setParent(window)
    controller.set_project(project)
    window.set_project(project)

    server.event.connect(controller.handle)
    controller.state_changed.connect(lambda state, tool: window.set_state(state, tool))
    controller.view_changed.connect(window.apply_view)
    controller.muted_changed.connect(window.set_muted)
    controller.quit_requested.connect(quit_app)
    window.mute_toggled.connect(lambda muted: controller.handle({"kind": "mute" if muted else "unmute"}))

    def on_closed() -> None:
        emit_command({"type": "closed"}, out)
        quit_app()

    voice = voice_factory(lambda: controller.muted) if voice_factory else None
    if voice is not None:
        voice.speech_started.connect(lambda: controller.handle({"kind": "speak.start"}))
        voice.speech_ended.connect(lambda: controller.handle({"kind": "speak.end"}))
        voice.notice.connect(controller.set_notice)
        controller.muted_changed.connect(voice.set_muted)
        window.closed.connect(voice.stop)

        def on_event(event: dict) -> None:
            kind = event.get("kind")
            if kind == "turn.start":
                voice.on_turn_start()
            elif kind == "turn.complete" and event.get("reason") == "answer":
                voice.on_turn_complete(event.get("text") or "")

        server.event.connect(on_event)

    call = None
    if call_factory:
        call = call_factory(lambda: controller.muted, lambda: controller.state == "waiting")
        call.setParent(window)
        # clicking Clawd is the mute switch: unmuted = the call is live, muted = hung up
        window.clicked.connect(lambda: controller.handle({"kind": "unmute" if controller.muted else "mute"}))
        window.send_pressed.connect(call.send_pressed)
        window.cancel_pressed.connect(call.cancel_pressed)
        window.edited.connect(call.edited)
        call.transcript.connect(window.set_transcript)
        call.pending.connect(lambda text, left: window.set_pending(text, left))
        call.submit.connect(lambda text: emit_command({"type": "submit", "text": text}, out))
        call.notice.connect(controller.set_notice)
        call.live_changed.connect(window.set_live)
        call.speech_changed.connect(lambda on: controller.handle({"kind": "mic.start" if on else "mic.stop"}))
        call.auto_muted.connect(lambda: controller.handle({"kind": "mute"}))
        if voice is not None:
            call.barge_in.connect(voice.stop)  # talking over Clawd stops Clawd, never Claude's work
            voice.speech_started.connect(call.note_clawd_speaking)
            voice.speech_ended.connect(call.note_clawd_speaking)
        controller.muted_changed.connect(lambda muted: call.set_live(not muted))
        controller.state_changed.connect(lambda state, tool: call.set_waiting(state == "waiting"))
        window.closed.connect(call.cancel_all)

    window.closed.connect(on_closed)

    watchdog = None
    if watch_parent:
        watchdog = ParentWatchdog()
        watchdog.parent_gone.connect(quit_app)
        watchdog.start()
    if call is not None:
        call.set_live(not controller.muted)  # unmuted = the call is live from the moment Clawd opens
    return Runtime(socket_path, window, controller, server, watchdog)
