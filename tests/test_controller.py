import pytest

from clawd.controller import Controller


def ev(kind, **kw):
    return {"kind": kind, **kw}


@pytest.fixture
def ctl(qtbot):
    # tiny holds so timer-driven transitions finish quickly in tests
    return Controller(waiting_debounce=0.03, done_hold=0.03, error_hold=0.03)


def states(ctl):
    seen = []
    ctl.state_changed.connect(lambda s, t: seen.append((s, t)))
    return seen


def test_tool_call_emits_working_with_tool(ctl):
    seen = states(ctl)
    ctl.handle(ev("turn.start"))
    ctl.handle(ev("tool.call", tool="Bash"))
    assert seen == [("thinking", None), ("working", "Bash")]


def test_permission_without_tool_done_goes_waiting_after_debounce(ctl, qtbot):
    ctl.handle(ev("tool.call", tool="Bash"))
    ctl.handle(ev("permission"))
    qtbot.waitUntil(lambda: ctl.state == "waiting", timeout=1000)


def test_permission_then_quick_tool_done_never_waits(ctl, qtbot):
    seen = states(ctl)
    ctl.handle(ev("tool.call", tool="Bash"))
    ctl.handle(ev("permission"))
    ctl.handle(ev("tool.done", tool="Bash"))
    qtbot.wait(120)
    assert "waiting" not in [s for s, _ in seen]


def test_notification_permission_prompt_waits_immediately(ctl):
    ctl.handle(ev("tool.call", tool="Bash"))
    ctl.handle(ev("notification", type="permission_prompt"))
    assert ctl.state == "waiting"


def test_other_notifications_do_not_change_state(ctl):
    ctl.handle(ev("tool.call", tool="Bash"))
    ctl.handle(ev("notification", type="idle_prompt"))
    assert ctl.state == "working"


def test_done_returns_to_idle_after_the_hold(ctl, qtbot):
    ctl.handle(ev("turn.start"))
    ctl.handle(ev("turn.complete", reason="answer"))
    assert ctl.state == "done"
    qtbot.waitUntil(lambda: ctl.state == "idle", timeout=1000)


def test_error_returns_to_idle_after_the_hold(ctl, qtbot):
    ctl.handle(ev("turn.start"))
    ctl.handle(ev("turn.complete", reason="error"))
    assert ctl.state == "error"
    qtbot.waitUntil(lambda: ctl.state == "idle", timeout=1000)


def test_new_turn_during_done_hold_is_not_knocked_back_to_idle(ctl, qtbot):
    ctl.handle(ev("turn.complete", reason="answer"))
    ctl.handle(ev("turn.start"))
    qtbot.wait(120)
    assert ctl.state == "thinking"


def test_mute_and_unmute_events(ctl):
    flips = []
    ctl.muted_changed.connect(flips.append)
    ctl.handle(ev("mute"))
    assert ctl.muted is True
    ctl.handle(ev("unmute"))
    assert ctl.muted is False
    assert flips == [True, False]


def test_quit_event_requests_quit(ctl, qtbot):
    with qtbot.waitSignal(ctl.quit_requested):
        ctl.handle(ev("quit"))


def test_unknown_event_does_not_emit(ctl):
    seen = states(ctl)
    ctl.handle(ev("something.else"))
    assert seen == []


def test_view_changes_follow_events(ctl):
    views = []
    ctl.view_changed.connect(views.append)
    ctl.handle(ev("turn.start"))
    ctl.handle(ev("tool.call", tool="Edit", target="/a/gigs.ts"))
    assert views[-1].badge == "WORKING" and views[-1].ticker == "EDITS gigs.ts"
    ctl.handle(ev("tool.call", tool="Edit", target="/a/other.ts"))
    assert views[-1].ticker == "EDITS other.ts"  # same state and tool, new target


def test_done_view_uses_the_replys_own_words(ctl):
    views = []
    ctl.view_changed.connect(views.append)
    ctl.handle(ev("turn.start"))
    ctl.handle(ev("turn.complete", reason="answer", text="Added GET /gigs. Tests pass."))
    assert views[-1].badge == "DONE" and views[-1].body == "Added GET /gigs. Tests pass."
    assert views[-1].headline is None


def test_idle_after_the_done_hold_still_shows_the_result(ctl, qtbot):
    ctl.handle(ev("turn.start"))
    ctl.handle(ev("turn.complete", reason="answer", text="Added GET /gigs."))
    qtbot.waitUntil(lambda: ctl.state == "idle", timeout=1000)
    assert ctl.view.badge == "IDLE" and ctl.view.body == "Added GET /gigs."


def test_tick_refreshes_the_thinking_counter_and_runs_only_during_a_turn(qtbot):
    clock = [0.0]
    ctl = Controller(now=lambda: clock[0], tick_ms=10_000)
    assert not ctl.tick_active()
    ctl.handle(ev("turn.start"))
    assert ctl.tick_active()
    clock[0] = 20.0
    ctl.tick()
    assert ctl.view.ticker == "THINKING… 20 s"
    ctl.handle(ev("turn.complete", reason="answer", text="ok"))
    assert not ctl.tick_active()


def test_project_name_reaches_the_session(ctl):
    ctl.set_project("gigs-api")
    assert ctl.session.project == "gigs-api"


def test_set_notice_shows_in_the_view_and_a_new_turn_clears_it(ctl):
    views = []
    ctl.view_changed.connect(views.append)
    ctl.set_notice("VOICE: key not set yet")
    assert views[-1].ticker == "VOICE: key not set yet"
    ctl.handle(ev("turn.start"))
    assert views[-1].ticker is None


def test_a_notice_event_from_the_plugin_shows_in_the_view(ctl):
    ctl.handle(ev("notice", text="VOICE: not sent, Claude is waiting for you"))
    assert ctl.view.ticker == "VOICE: not sent, Claude is waiting for you"
