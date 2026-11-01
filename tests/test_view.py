from clawd.session import Session
from clawd.view import View, build_view


def ev(kind, **kw):
    return {"kind": kind, **kw}


def worked(now=100.0):
    """A session two actions into a turn that started at t=88."""
    s = Session()
    s.on_event(ev("turn.start"), 88.0)
    s.on_event(ev("tool.call", tool="Bash", target="npm test"), 90.0)
    s.on_event(ev("tool.done", tool="Bash"), 91.0)
    s.on_event(ev("tool.call", tool="Edit", target="/home/x/src/gigs.ts"), 95.0)
    return s


def test_session_counts_actions_and_distinct_edited_files_per_turn():
    s = Session()
    s.on_event(ev("turn.start"), 0.0)
    for target in ("/a/gigs.ts", "/a/gigs.ts", "/a/other.ts"):
        s.on_event(ev("tool.call", tool="Edit", target=target), 1.0)
    s.on_event(ev("tool.call", tool="Bash", target="ls"), 2.0)
    s.on_event(ev("tool.call", tool="Read", target="/a/x.ts"), 3.0)
    assert s.actions == 5
    assert s.files == {"/a/gigs.ts", "/a/other.ts"}


def test_a_new_turn_resets_the_counters():
    s = worked()
    s.on_event(ev("turn.complete", reason="answer", text="ok"), 100.0)
    s.on_event(ev("turn.start"), 120.0)
    assert (s.actions, s.files, s.turn_started) == (0, set(), 120.0)


def test_working_view_shows_ticker_and_live_stats():
    v = build_view("working", worked(), 100.0)
    assert v == View(
        badge="WORKING",
        accent="orange",
        ticker="EDITS gigs.ts",
        stats="2 actions · 1 file changed · 12 s",
    )


def test_thinking_view_is_quiet_until_15_seconds_then_counts():
    s = worked()
    s.on_event(ev("tool.done", tool="Edit"), 96.0)
    short = build_view("thinking", s, 100.0)
    assert short.badge == "THINKING" and short.accent == "violet" and short.ticker is None
    long = build_view("thinking", s, 96.0 + 45.7)
    assert long.ticker == "THINKING… 45 s"


def test_waiting_view_names_what_claude_wants_and_how_long():
    s = worked()
    s.set_state_since(92.0)
    v = build_view("waiting", s, 100.0)
    assert v.badge == "NEEDS YOU" and v.accent == "yellow"
    assert v.headline == "Permission needed"
    assert v.body == "Claude wants to use Edit: gigs.ts"
    assert v.stats == "waiting 8 s · answer in the terminal"


def test_done_view_has_headline_body_and_final_stats():
    s = worked()
    s.on_event(ev("turn.complete", reason="answer", text="Added GET /gigs with cursor pagination. The 6 new tests pass."), 90.0)
    v = build_view("done", s, 200.0)
    assert (v.badge, v.accent, v.headline) == ("DONE", "green", None)  # no invented headline
    assert v.body == "Added GET /gigs with cursor pagination. The 6 new tests pass."
    assert v.stats == "2 actions · 1 file changed · 2 s"
    assert v.ticker is None


def test_error_view():
    s = worked()
    s.on_event(ev("turn.complete", reason="error"), 100.0)
    v = build_view("error", s, 101.0)
    assert (v.badge, v.accent, v.headline) == ("FAILED", "red", "That failed")


def test_idle_listening_and_speaking_badges():
    s = Session()
    assert build_view("idle", s, 0.0) == View(badge="IDLE", accent="dim")
    assert build_view("listening", s, 0.0).badge == "LISTENING"
    assert build_view("speaking", s, 0.0).accent == "blue"


def test_project_name_is_kept_on_the_session():
    s = Session(project="gigs-api")
    assert s.project == "gigs-api"


def finished():
    s = worked()
    s.on_event(ev("turn.complete", reason="answer", text="Added GET /gigs with cursor pagination."), 90.0)
    return s


def test_idle_after_a_finished_turn_keeps_showing_the_last_result():
    v = build_view("idle", finished(), 500.0)
    assert (v.badge, v.accent) == ("IDLE", "dim")
    assert v.headline is None
    assert v.body == "Added GET /gigs with cursor pagination."
    assert v.stats == "2 actions · 1 file changed · 2 s"


def test_idle_after_an_error_keeps_the_failure():
    s = worked()
    s.on_event(ev("turn.complete", reason="error"), 100.0)
    assert build_view("idle", s, 500.0).headline == "That failed"


def test_idle_after_an_abort_is_bare():
    s = worked()
    s.on_event(ev("turn.complete", reason="aborted"), 100.0)
    assert build_view("idle", s, 500.0) == View(badge="IDLE", accent="dim")


def test_speaking_shows_the_summary_being_read():
    v = build_view("speaking", finished(), 500.0)
    assert (v.badge, v.accent) == ("SPEAKING", "blue")
    assert v.body == "Added GET /gigs with cursor pagination."


def test_a_new_turn_clears_the_old_result_from_idle_views():
    s = finished()
    s.on_event(ev("turn.start"), 600.0)
    assert build_view("idle", s, 601.0) == View(badge="IDLE", accent="dim")


def test_a_voice_notice_replaces_the_ticker_until_the_next_turn():
    s = finished()
    s.notice = "VOICE: daily voice limit reached"
    assert build_view("idle", s, 500.0).ticker == "VOICE: daily voice limit reached"
    s.on_event(ev("turn.start"), 600.0)
    assert build_view("thinking", s, 601.0).ticker is None


def test_usage_limits_show_on_every_state_and_default_to_nothing():
    s = Session()
    assert build_view("idle", s, 0.0).usage is None
    s.on_event(ev("usage", limits=[{"kind": "five_hour", "percentUsed": 34, "resetsAt": None}, {"kind": "seven_day", "percentUsed": 82, "resetsAt": None}]), 1.0)
    for state in ("idle", "working", "done"):
        v = build_view(state, s, 2.0)
        assert v.usage == "Claude 5h 34% · week 82%" and v.usage_level == "warn"


def test_a_usage_reading_does_not_reset_the_quiet_timer():
    s = worked()
    s.on_event(ev("tool.done", tool="Edit"), 96.0)
    s.on_event(ev("usage", limits=[]), 130.0)
    assert build_view("thinking", s, 141.7).ticker == "THINKING… 45 s"  # still counted from the last real event
