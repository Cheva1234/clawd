import json

from clawd.config import Config, load_config


def test_defaults_when_no_file(tmp_path):
    cfg = load_config(tmp_path / "none.json")
    assert cfg == Config()
    assert cfg.voice_id == "JBFqnCBsd6RMkjVDRZzb"  # a standard ElevenLabs voice (George): works with any account
    assert cfg.model_id == "eleven_flash_v2_5"
    assert cfg.daily_chars == 8000 and cfg.daily_listen_seconds == 1800 and cfg.countdown_secs == 1.5
    assert not hasattr(cfg, "summary_mode")


def test_file_overrides_known_keys_and_ignores_the_rest(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"voice_id": "abc", "daily_chars": 500, "junk": 1}))
    cfg = load_config(p)
    assert (cfg.voice_id, cfg.daily_chars) == ("abc", 500)


def test_bad_types_and_corrupt_json_fall_back_to_defaults(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"daily_chars": "lots", "summary_mode": "weird", "voice_id": ""}))
    assert load_config(p) == Config()
    p.write_text("{nope")
    assert load_config(p) == Config()


def test_listening_cap_default_and_override(tmp_path):
    assert Config().daily_listen_seconds == 1800
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"daily_listen_seconds": 90}))
    assert load_config(p).daily_listen_seconds == 90
    p.write_text(json.dumps({"daily_listen_seconds": -5}))
    assert load_config(p).daily_listen_seconds == 1800


def test_countdown_seconds_setting(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"countdown_secs": 2.5}))
    assert load_config(p).countdown_secs == 2.5
    for bad in ("soon", -1, 0, 99, True):
        p.write_text(json.dumps({"countdown_secs": bad}))
        assert load_config(p).countdown_secs == 1.5
