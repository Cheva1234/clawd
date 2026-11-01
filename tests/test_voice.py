from PySide6.QtCore import QObject, Signal

from clawd.format import spoken_text
from clawd.voice import VoiceOut


class FakeSpeaker(QObject):
    started = Signal()
    finished = Signal()
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.spoken, self.stops = [], 0

    def speak(self, text):
        self.spoken.append(text)

    def stop(self):
        self.stops += 1


def make(muted=False):
    speaker = FakeSpeaker()
    voice = VoiceOut(speaker)
    voice.set_muted(muted)
    speaker.stops = 0
    return voice, speaker


def test_a_finished_reply_is_spoken_immediately_in_its_own_words():
    voice, speaker = make()
    reply = "Yes, I read you. I can only see text, though."
    voice.on_turn_complete(reply)
    assert speaker.spoken == [spoken_text(reply)] == [reply]  # no model call, no delay, no rewrite


def test_a_long_reply_is_cut_to_whole_first_sentences_with_the_note():
    voice, speaker = make()
    voice.on_turn_complete(" ".join(f"Sentence number {i} is here and says a few things." for i in range(30)))
    assert speaker.spoken[0].endswith("The full answer is in the terminal.") and len(speaker.spoken[0]) < 340


def test_muted_says_nothing():
    voice, speaker = make(muted=True)
    voice.on_turn_complete("Anything at all.")
    assert speaker.spoken == []


def test_empty_or_code_only_replies_say_nothing():
    voice, speaker = make()
    voice.on_turn_complete("   ")
    voice.on_turn_complete("```\nonly code\n```")
    assert speaker.spoken == []


def test_a_new_turn_and_muting_cut_the_current_speech():
    voice, speaker = make()
    voice.on_turn_start()
    assert speaker.stops == 1
    voice.set_muted(True)
    assert speaker.stops == 2


def test_speaker_signals_are_forwarded(qtbot):
    voice, speaker = make()
    with qtbot.waitSignal(voice.speech_started):
        speaker.started.emit()
    with qtbot.waitSignal(voice.speech_ended):
        speaker.finished.emit()
    with qtbot.waitSignal(voice.notice) as sig:
        speaker.failed.emit("ElevenLabs rejected the key (401)")
    assert sig.args == ["VOICE: ElevenLabs rejected the key (401)"]
