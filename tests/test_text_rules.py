import pytest

from hark.text import cleaner, vocabulary, voice_commands


@pytest.mark.parametrize("spoken,expected", [
    # Cases from OpenDictate's voice_commands.rs tests
    ("hello comma world", "hello, world"),
    ("Hello, comma, how are you", "Hello, how are you"),
    ("thanks add a comma see you soon", "thanks, see you soon"),
    ("Send it Monday. Sorry, remove that. Send it Tuesday.", "Send it Tuesday."),
    ("Hi team. Ship it today scratch that tomorrow", "Hi team. Tomorrow"),
    ("Please remove that file", "Please remove that file"),
    ("I love the Oxford comma", "I love the Oxford comma"),
    ("ping at the rate KV about it", "ping @KV about it"),
    ("growing at the rate of 5 percent", "growing at the rate of 5 percent"),
    # Line breaks, requested punctuation, guards
    ("Dear John comma new line thanks for the update period",
     "Dear John,\nThanks for the update."),
    ("first point new paragraph second point", "first point\n\nSecond point"),
    ("is that right question mark yes it is", "is that right? Yes it is"),
    ("the period ended", "the period ended"),
    ("We need a new line of products", "We need a new line of products"),
    ("note insert a colon buy milk", "note: buy milk"),
    ("scratch that", ""),
])
def test_voice_commands(spoken, expected):
    assert voice_commands.apply(spoken) == expected


@pytest.mark.parametrize("spoken,expected", [
    ("So, um, I think we should go um.", "So I think we should go."),
    ("Um, so we should leave", "So we should leave"),
    ("we should, uh, go", "we should go"),
    ("I I think the the plan works", "I think the plan works"),
    ("I think I think we're fine", "I think we're fine"),
    ("I was, you know, tired", "I was tired"),
    ("Do you know?", "Do you know?"),
    ("If you know, tell me", "If you know, tell me"),
    ("it is 5 mm wide", "it is 5 mm wide"),
    ("bye bye then", "bye bye then"),
    ("one one two", "one one two"),
    ("go go.", "go."),
    ("Hmm.", ""),
])
def test_cleaner(spoken, expected):
    assert cleaner.clean(spoken) == expected


def test_vocabulary_replacements_and_hints():
    entries = [{"from": "hark ai", "to": "Hark.ai"}, {"from": "kubernetes", "to": "Kubernetes"},
               {"from": "dir", "to": r"C:\dir"}]
    text = "I use hark  AI on kubernetes, not harkaid, in dir"
    assert vocabulary.apply(text, entries) == r"I use Hark.ai on Kubernetes, not harkaid, in C:\dir"
    assert vocabulary.terms(entries) == ["Hark.ai", "Kubernetes", r"C:\dir"]
