import io
import json

import pytest
from PySide6.QtCore import QObject, Signal

from clawd.app import build
from tests.helpers import make_sockpath, post


@pytest.fixture
def rt(qtbot, tmp_path):
    quits = []
    out = io.StringIO()
    runtime = build(
        make_sockpath(),
        out=out,
        state_path=tmp_path / "state.json",
        on_quit=lambda: quits.append(1),
        watch_parent=False,
    )
    runtime.quits, runtime.out = quits, out
    qtbot.addWidget(runtime.window)
    yield runtime
    runtime.server.stop()


def test_event_over_socket_updates_the_window(rt, qtbot):
    post(rt.path, {"kind": "tool.call", "tool": "Bash", "target": "npm test"})
    qtbot.waitUntil(lambda: rt.window.ticker_line() == "RUNS npm test", timeout=3000)
    assert rt.window.badge_text() == "WORKING"


def test_mute_event_from_plugin_updates_the_button(rt, qtbot):
    post(rt.path, {"kind": "mute"})
    qtbot.waitUntil(lambda: rt.window.mute_button.isChecked(), timeout=3000)
    assert rt.controller.muted is True


def test_mute_button_updates_the_controller_without_looping(rt):
    rt.window.mute_button.click()
    assert rt.controller.muted is True
    rt.window.mute_button.click()
    assert rt.controller.muted is False


def test_quit_event_calls_on_quit(rt, qtbot):
    post(rt.path, {"kind": "quit"})
    qtbot.waitUntil(lambda: bool(rt.quits), timeout=3000)


def test_close_button_tells_the_plugin_and_quits(rt):
    rt.window.close_button.click()
    assert json.loads(rt.out.getvalue().strip()) == {"type": "closed"}
    assert rt.quits


def test_second_build_on_a_live_socket_raises(rt, tmp_path):
    from clawd.ipc import AlreadyRunning

    with pytest.raises(AlreadyRunning):
        build(rt.path, out=io.StringIO(), state_path=tmp_path / "s2.json", on_quit=lambda: None, watch_parent=False)


def test_project_name_reaches_the_header_and_the_session(qtbot, tmp_path):
    import io

    runtime = build(
        make_sockpath(), out=io.StringIO(), state_path=tmp_path / "p.json", on_quit=lambda: None,
        watch_parent=False, project="gigs-api",
    )
    qtbot.addWidget(runtime.window)
    try:
        assert runtime.window.project_text() == "CLAWD / gigs-api"
        assert runtime.controller.session.project == "gigs-api"
    finally:
        runtime.server.stop()


def test_a_finished_turn_shows_its_result_in_the_bubble(rt, qtbot):
    post(rt.path, {"kind": "turn.start"})
    post(rt.path, {"kind": "tool.call", "tool": "Edit", "target": "/a/gigs.ts"})
    post(rt.path, {"kind": "turn.complete", "reason": "answer", "text": "Added GET /gigs. The 6 new tests pass."})
    qtbot.waitUntil(lambda: rt.window.body_text() == "Added GET /gigs. The 6 new tests pass.", timeout=3000)
    assert rt.window.headline_text() == ""
    assert "1 file changed" in rt.window.stats_line()


class FakeVoice(QObject):
    speech_started = Signal()
    speech_ended = Signal()
    notice = Signal(str)

    def __init__(self):
        super().__init__()
        self.log = []

    def on_turn_complete(self, reply):
        self.log.append(("complete", reply))

    def on_turn_start(self):
        self.log.append(("start",))

    def set_muted(self, muted):
        self.log.append(("muted", muted))

    def stop(self):
        self.log.append(("stop",))


@pytest.fixture
def vrt(qtbot, tmp_path):
    voice = FakeVoice()
    seen = {}

    def factory(is_muted):
        seen["is_muted"] = is_muted
        return voice

    runtime = build(
        make_sockpath(), out=io.StringIO(), state_path=tmp_path / "v.json", on_quit=lambda: None,
        watch_parent=False, voice_factory=factory,
    )
    qtbot.addWidget(runtime.window)
    runtime.voice, runtime.seen = voice, seen
    yield runtime
    runtime.server.stop()


def test_voice_hears_turn_start_and_the_final_reply(vrt, qtbot):
    post(vrt.path, {"kind": "turn.start"})
    qtbot.waitUntil(lambda: ("start",) in vrt.voice.log, timeout=3000)
    post(vrt.path, {"kind": "turn.complete", "reason": "answer", "text": "Added GET /gigs."})
    qtbot.waitUntil(lambda: ("complete", "Added GET /gigs.") in vrt.voice.log, timeout=3000)


def test_an_aborted_or_failed_turn_is_not_spoken(vrt, qtbot):
    post(vrt.path, {"kind": "turn.complete", "reason": "error", "text": "x"})
    qtbot.wait(150)
    assert not any(entry[0] == "complete" for entry in vrt.voice.log)


def test_mute_reaches_the_voice_and_the_voice_knows_the_mute_state(vrt, qtbot):
    vrt.window.mute_button.click()
    assert ("muted", True) in vrt.voice.log
    assert vrt.seen["is_muted"]() is True


def test_voice_results_flow_back_into_the_bubble(vrt, qtbot):
    vrt.voice.notice.emit("VOICE: key not set yet")
    assert vrt.window.ticker_line() == "VOICE: key not set yet"
    vrt.voice.speech_started.emit()
    assert vrt.window.badge_text() == "SPEAKING"
    vrt.voice.speech_ended.emit()
    assert vrt.window.badge_text() in ("IDLE", "DONE")  # DONE until its hold timer ends


def test_closing_the_window_stops_the_voice(vrt):
    vrt.window.close_button.click()
    assert ("stop",) in vrt.voice.log


def test_controller_and_server_die_with_the_window(rt):
    # timers inside them must never fire into a deleted window
    assert rt.controller.parent() is rt.window
    assert rt.server.parent() is rt.window


class FakeCall(QObject):
    transcript = Signal(str, bool)
    pending = Signal(object, float)
    submit = Signal(str)
    notice = Signal(str)
    live_changed = Signal(bool)
    speech_changed = Signal(bool)
    barge_in = Signal()
    auto_muted = Signal()

    def __init__(self):
        super().__init__()
        self.log = []

    def set_live(self, on):
        self.log.append(("live", on))

    def send_pressed(self):
        self.log.append("send")

    def cancel_pressed(self):
        self.log.append("cancel_pressed")

    def edited(self, text):
        self.log.append(("edited", text))

    def set_waiting(self, waiting):
        self.log.append(("waiting", waiting))

    def cancel_all(self):
        self.log.append("cancel_all")

    def note_clawd_speaking(self):
        self.log.append("clawd_speaking")


@pytest.fixture
def crt(qtbot, tmp_path):
    call, voice = FakeCall(), FakeVoice()
    out = io.StringIO()
    runtime = build(
        make_sockpath(), out=out, state_path=tmp_path / "c.json", on_quit=lambda: None, watch_parent=False,
        voice_factory=lambda is_muted: voice,
        call_factory=lambda is_muted, is_waiting: call,
    )
    qtbot.addWidget(runtime.window)
    runtime.call, runtime.voice, runtime.out = call, voice, out
    yield runtime
    runtime.server.stop()


def test_the_call_starts_live_when_clawd_opens(crt):
    assert crt.call.log[0] == ("live", True)


def test_clicking_clawd_toggles_mute_and_the_call(crt):
    crt.window.clicked.emit()
    assert crt.controller.muted is True and ("live", False) in crt.call.log
    assert crt.window.mute_button.isChecked()
    crt.window.clicked.emit()
    assert crt.controller.muted is False and crt.call.log[-1] == ("live", True)


def test_the_mute_button_and_the_slash_command_also_end_and_resume_the_call(crt, qtbot):
    crt.window.mute_button.click()
    assert ("live", False) in crt.call.log
    post(crt.path, {"kind": "unmute"})
    qtbot.waitUntil(lambda: crt.call.log[-1] == ("live", True), timeout=3000)


def test_the_panel_buttons_drive_the_call(crt):
    crt.window.send_button.click()
    crt.window.cancel_button.click()
    crt.window.edited.emit("new text")
    assert crt.call.log[-3:] == ["send", "cancel_pressed", ("edited", "new text")]


def test_live_transcript_and_the_pending_countdown_show_in_the_panel(crt):
    crt.window.show()
    crt.call.transcript.emit("list the", False)
    assert crt.window.transcript_text() == "list the"
    crt.call.pending.emit("list the files", 1.0)
    assert crt.window.pending_row.isVisible() and crt.window.pending_edit.text() == "list the files"
    crt.call.pending.emit(None, 0.0)
    assert not crt.window.pending_row.isVisible()


def test_an_approved_request_is_sent_to_the_plugin_as_one_json_line(crt):
    crt.call.submit.emit("list the files")
    assert json.loads(crt.out.getvalue().strip().splitlines()[-1]) == {"type": "submit", "text": "list the files"}


def test_hearing_speech_shows_listening_but_never_overrides_a_running_turn(crt):
    crt.call.speech_changed.emit(True)
    assert crt.window.badge_text() == "LISTENING"
    crt.call.speech_changed.emit(False)
    assert crt.window.badge_text() == "IDLE"
    crt.controller.handle({"kind": "tool.call", "tool": "Bash", "target": "ls"})
    crt.call.speech_changed.emit(True)
    assert crt.window.badge_text() == "WORKING"  # Claude is busy: the badge keeps saying so
    crt.call.speech_changed.emit(False)
    assert crt.window.badge_text() == "WORKING"


def test_barge_in_stops_clawds_voice_and_clawds_voice_resets_the_silence_timer(crt):
    crt.call.barge_in.emit()
    assert ("stop",) in crt.voice.log
    crt.voice.speech_started.emit()
    crt.voice.speech_ended.emit()
    assert crt.call.log.count("clawd_speaking") == 2


def test_the_call_muting_itself_mutes_the_whole_app(crt):
    crt.call.auto_muted.emit()
    assert crt.controller.muted is True and crt.window.mute_button.isChecked()
    assert ("muted", True) in crt.voice.log


def test_a_voice_problem_shows_as_a_notice(crt):
    crt.call.notice.emit("VOICE: No microphone found")
    assert crt.window.ticker_line() == "VOICE: No microphone found"


def test_live_state_shows_in_the_tag(crt):
    crt.call.live_changed.emit(True)
    assert crt.window.live_text() == "LIVE"
    crt.call.live_changed.emit(False)
    assert crt.window.live_text() == "MUTED"


def test_waiting_for_a_permission_pauses_the_call_and_closing_cancels_it(crt):
    crt.controller.handle({"kind": "tool.call", "tool": "Bash", "target": "rm -rf x"})
    crt.controller.handle({"kind": "notification", "type": "permission_prompt"})
    assert ("waiting", True) in crt.call.log
    crt.controller.handle({"kind": "tool.done", "tool": "Bash"})
    assert ("waiting", False) in crt.call.log
    crt.window.close_button.click()
    assert "cancel_all" in crt.call.log


def test_make_call_builds_without_opening_the_mic_or_network():
    from clawd.call import Call, make_call

    assert isinstance(make_call(lambda: False, lambda: False), Call)
