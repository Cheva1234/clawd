from clawd.confirm import PendingRequest


def make(text="list the files", seconds=0.12):
    req = PendingRequest(text, seconds=seconds, interval_ms=10)
    sent, cancelled, ticks = [], [], []
    req.sent.connect(sent.append)
    req.cancelled.connect(lambda: cancelled.append(1))
    req.tick.connect(ticks.append)
    return req, sent, cancelled, ticks


def test_sends_exactly_once_after_the_countdown(qtbot):
    req, sent, _, ticks = make()
    req.start()
    qtbot.waitUntil(lambda: sent == ["list the files"], timeout=2000)
    qtbot.wait(100)
    assert sent == ["list the files"]
    assert ticks and ticks == sorted(ticks, reverse=True) and ticks[-1] <= 0.02


def test_a_cancelled_request_never_reaches_the_session(qtbot):
    req, sent, cancelled, _ = make()
    req.start()
    qtbot.wait(40)
    req.cancel()
    qtbot.wait(250)
    assert sent == [] and cancelled == [1]


def test_cancel_after_send_is_a_no_op_and_send_after_cancel_does_nothing(qtbot):
    req, sent, cancelled, _ = make()
    req.start()
    req.send_now()
    req.cancel()
    assert sent == ["list the files"] and cancelled == []
    req2, sent2, cancelled2, _ = make()
    req2.start()
    req2.cancel()
    req2.send_now()
    assert sent2 == [] and cancelled2 == [1]


def test_send_now_sends_immediately_and_only_once(qtbot):
    req, sent, _, _ = make(seconds=5)
    req.start()
    req.send_now()
    req.send_now()
    qtbot.wait(60)
    assert sent == ["list the files"]


def test_edit_restarts_the_countdown_and_sends_the_edited_text(qtbot):
    req, sent, _, _ = make(seconds=0.2)
    req.start()
    qtbot.wait(120)
    req.edit("list all the files")
    qtbot.wait(120)
    assert sent == []  # restarted: the original deadline passed, the new one has not
    qtbot.waitUntil(lambda: sent == ["list all the files"], timeout=2000)


def test_pause_holds_the_countdown_and_resume_continues(qtbot):
    req, sent, _, _ = make(seconds=0.1)
    req.start()
    req.pause()
    qtbot.wait(250)
    assert sent == []
    req.resume()
    qtbot.waitUntil(lambda: sent == ["list the files"], timeout=2000)


def test_blank_text_is_never_sent(qtbot):
    req, sent, cancelled, _ = make(text="   ")
    req.start()
    qtbot.wait(200)
    assert sent == [] and cancelled == [1]
