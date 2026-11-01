from clawd.format import FULL_ANSWER_NOTE, duration_text, spoken_text, stats_text, thinking_text, ticker_text


def test_ticker_uses_a_verb_and_the_file_name_only():
    assert ticker_text("Edit", "/home/x/src/gigs.ts") == "EDITS gigs.ts"
    assert ticker_text("Bash", "npm test") == "RUNS npm test"
    assert ticker_text("Grep", "paginate") == "SEARCHES paginate"
    assert ticker_text("Write", "docs/notes.md") == "WRITES notes.md"


def test_ticker_without_a_target_or_with_an_unknown_tool():
    assert ticker_text("Bash", None) == "RUNS"
    assert ticker_text("Frobnicate", None) == "FROBNICATE"
    assert ticker_text("Frobnicate", "x") == "FROBNICATE x"


def test_ticker_truncates_long_targets_and_keeps_one_line():
    out = ticker_text("Bash", "echo " + "a" * 100)
    assert len(out) <= len("RUNS ") + 32
    assert out.endswith("…")
    assert "\n" not in ticker_text("Bash", "line one\nline two")


def test_duration_text():
    assert duration_text(0.4) == "0 s"
    assert duration_text(2.2) == "2 s"
    assert duration_text(59.4) == "59 s"
    assert duration_text(134) == "2m 14s"
    assert duration_text(3600) == "60m 00s"


def test_stats_text_pluralises_and_skips_empty_parts():
    assert stats_text(4, 2, 2) == "4 actions · 2 files changed · 2 s"
    assert stats_text(1, 1, 134) == "1 action · 1 file changed · 2m 14s"
    assert stats_text(3, 0, 9) == "3 actions · 9 s"
    assert stats_text(0, 0, 5) == "5 s"
    assert stats_text(0, 0, None) is None


def test_thinking_text():
    assert thinking_text(45.7) == "THINKING… 45 s"


def test_spoken_text_short_reply_is_kept_whole_word_for_word():
    reply = "Yes, I read you. I can only see text, though. Your message came through."
    assert spoken_text(reply) == reply


def test_spoken_text_long_reply_keeps_whole_first_sentences_then_the_note():
    sentences = [f"This is sentence number {i} and it has a fair bit of text in it." for i in range(12)]
    out = spoken_text(" ".join(sentences))
    assert out.endswith(FULL_ANSWER_NOTE)
    kept = out[: -len(FULL_ANSWER_NOTE)].strip()
    assert len(kept) <= 300 and kept.endswith(".")
    assert " ".join(sentences).startswith(kept)  # the reply's own words, from its start


def test_spoken_text_single_huge_sentence_is_cut_at_a_word_then_the_note():
    out = spoken_text("word " * 200)
    kept = out[: -len(FULL_ANSWER_NOTE)].strip()
    assert kept.endswith("…") and len(kept) <= 300 and out.endswith(FULL_ANSWER_NOTE)


def test_spoken_text_strips_markdown_and_code():
    assert spoken_text("# Result\n\n**Fixed** the `cursor` bug.\n\n```py\nprint('x')\n```\n") == "Result Fixed the cursor bug."


def test_spoken_text_of_empty_or_code_only_reply_is_blank():
    assert spoken_text("") == "" and spoken_text("   ") == ""
    assert spoken_text("```\nonly code\n```") == ""
