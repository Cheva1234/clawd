from clawd.credits import DailyCap


def test_allows_until_the_cap_and_blocks_after(tmp_path):
    cap = DailyCap(tmp_path / "c.json", max_chars=100, today=lambda: "2026-11-01")
    assert cap.allow(60)
    cap.record(60)
    assert cap.used() == 60
    assert cap.allow(40) and not cap.allow(41)


def test_resets_on_the_next_day(tmp_path):
    day = ["2026-11-01"]
    cap = DailyCap(tmp_path / "c.json", max_chars=100, today=lambda: day[0])
    cap.record(100)
    assert not cap.allow(1)
    day[0] = "2026-11-02"
    assert cap.used() == 0 and cap.allow(100)


def test_usage_survives_a_restart(tmp_path):
    DailyCap(tmp_path / "c.json", 100, today=lambda: "d").record(30)
    assert DailyCap(tmp_path / "c.json", 100, today=lambda: "d").used() == 30


def test_corrupt_file_counts_as_zero_and_never_raises(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("not json")
    cap = DailyCap(p, 100, today=lambda: "d")
    assert cap.used() == 0
    cap.record(5)
    assert cap.used() == 5
