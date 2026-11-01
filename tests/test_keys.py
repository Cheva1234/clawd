import os

import pytest

from clawd.keys import KeyFileError, load_key


def write(path, text, mode=0o600):
    path.write_text(text)
    os.chmod(path, mode)
    return path


def test_load_key_returns_the_stripped_key(tmp_path):
    assert load_key(write(tmp_path / "k", "sk_abc123\n")) == "sk_abc123"


def test_load_key_rejects_a_group_or_world_readable_file(tmp_path):
    p = write(tmp_path / "k", "sk_abc123", 0o640)
    with pytest.raises(KeyFileError, match="0600"):
        load_key(p)


def test_missing_file_and_placeholder_and_empty_are_errors(tmp_path):
    with pytest.raises(KeyFileError, match="missing"):
        load_key(tmp_path / "nope")
    with pytest.raises(KeyFileError, match="not set"):
        load_key(write(tmp_path / "ph", "REPLACE_ME_WITH_YOUR_ELEVENLABS_BURNER_KEY\n"))
    with pytest.raises(KeyFileError, match="empty"):
        load_key(write(tmp_path / "e", "  \n"))


def test_key_text_never_appears_in_any_error(tmp_path):
    p = write(tmp_path / "k", "sk_supersecretvalue", 0o644)
    with pytest.raises(KeyFileError) as exc:
        load_key(p)
    assert "supersecretvalue" not in str(exc.value) and "supersecretvalue" not in repr(exc.value)
