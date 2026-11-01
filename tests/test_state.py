from clawd.state import STATUS_LINE, next_state, status_line


def ev(kind, **kw):
    return {"kind": kind, **kw}


def test_turn_start_goes_thinking():
    assert next_state("idle", ev("turn.start")) == "thinking"


def test_tool_call_goes_working():
    assert next_state("thinking", ev("tool.call", tool="Bash")) == "working"


def test_tool_done_goes_back_to_thinking():
    assert next_state("working", ev("tool.done", tool="Bash")) == "thinking"


def test_status_line_names_the_running_tool():
    assert status_line("working", "Bash") == "running Bash"
    assert status_line("idle") == STATUS_LINE["idle"]


def test_waiting_timeout_after_permission_goes_waiting_only_from_working():
    assert next_state("working", ev("waiting.timeout")) == "waiting"
    # the tool finished within the debounce window: no waiting flash
    assert next_state("thinking", ev("waiting.timeout")) == "thinking"


def test_turn_complete_answer_goes_done_then_idle_on_timeout():
    assert next_state("thinking", ev("turn.complete", reason="answer")) == "done"
    assert next_state("done", ev("done.timeout")) == "idle"


def test_turn_complete_error_or_refusal_goes_error_and_aborted_goes_idle():
    assert next_state("thinking", ev("turn.complete", reason="error")) == "error"
    assert next_state("thinking", ev("turn.complete", reason="refusal")) == "error"
    assert next_state("working", ev("turn.complete", reason="aborted")) == "idle"


def test_app_error_goes_error_and_error_timeout_goes_idle():
    assert next_state("idle", ev("app.error")) == "error"
    assert next_state("error", ev("error.timeout")) == "idle"


def test_mic_click_starts_listening_from_idle_and_stop_returns_idle():
    assert next_state("idle", ev("mic.start")) == "listening"
    assert next_state("listening", ev("mic.stop")) == "idle"


def test_listening_ignored_while_waiting():
    assert next_state("waiting", ev("mic.start")) == "waiting"


def test_speaking_starts_and_ends():
    assert next_state("done", ev("speak.start")) == "speaking"
    assert next_state("speaking", ev("speak.end")) == "idle"


def test_unknown_event_keeps_state():
    assert next_state("working", ev("something.else")) == "working"


def test_permission_alone_does_not_change_state():
    assert next_state("working", ev("permission")) == "working"


def test_listening_never_overrides_a_running_turn():
    for busy in ("thinking", "working", "waiting"):
        assert next_state(busy, ev("mic.start")) == busy
        assert next_state(busy, ev("mic.stop")) == busy
    assert next_state("done", ev("mic.start")) == "listening"
