"""Wake-word matching: the name in the middle of a Hindi sentence, or not at all.

No audio model is involved - the matcher runs on the transcript of a short burst, so it
is deterministic and cheap. Both scripts are covered because the same user may say
"Chrome kholo" with a Devanagari or a Latin wake word.
"""

from __future__ import annotations

import pytest

from shraddha.speech.wake import (
    WakeWordMatcher,
    contains_stop_phrase,
    edit_distance,
    normalise,
)


@pytest.fixture()
def matcher() -> WakeWordMatcher:
    return WakeWordMatcher(["hey shraddha", "श्रद्धा", "shraddha", "o shraddha"], fuzzy_distance=2)


# ------------------------------------------------------------------- primitives
def test_normalise_folds_case_and_punctuation() -> None:
    assert normalise("श्रद्धा, Chrome खोलो।") == "श्रद्धा chrome खोलो"
    assert normalise("  Hey   SHRADDHA!!  ") == "hey shraddha"


def test_normalise_handles_empty_input() -> None:
    assert normalise("") == ""
    assert normalise(None) == ""  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("shraddha", "shraddha", 0),
        ("shradha", "shraddha", 1),
        ("sraddha", "shraddha", 1),
        ("shrddha", "shraddha", 1),
        ("xx", "shraddha", 3),  # bounded: never larger than max_distance + 1
    ],
)
def test_edit_distance(left: str, right: str, expected: int) -> None:
    assert edit_distance(left, right, 2) == expected


# ------------------------------------------------------------------ wake matching
def test_name_alone_matches_without_a_command(matcher: WakeWordMatcher) -> None:
    match = matcher.detect("श्रद्धा")
    assert match.matched is True
    assert match.has_command is False


def test_name_plus_command_returns_the_trailing_command(matcher: WakeWordMatcher) -> None:
    match = matcher.detect("श्रद्धा, Chrome खोलो।")
    assert match.matched is True
    assert match.has_command is True
    assert "chrome" in match.command.lower()
    assert "श्रद्धा" not in match.command


def test_two_word_wake_phrase_is_accepted(matcher: WakeWordMatcher) -> None:
    match = matcher.detect("hey shraddha, notepad kholo")
    assert match.matched is True
    assert match.command == "notepad kholo"


def test_fillers_before_the_name_are_dropped(matcher: WakeWordMatcher) -> None:
    match = matcher.detect("arre suno shraddha calculator kholo")
    assert match.command == "calculator kholo"


@pytest.mark.parametrize("said", ["shradha", "sraddha", "shardha", "shrddha"])
def test_mispronunciations_still_wake_her(matcher: WakeWordMatcher, said: str) -> None:
    assert matcher.matches(f"{said} chrome kholo") is True


@pytest.mark.parametrize("said", ["श्रद्दा", "श्रद्घा"])
def test_devanagari_mispronunciations_also_wake_her(matcher: WakeWordMatcher, said: str) -> None:
    assert matcher.matches(f"{said} क्रोम खोलो") is True


def test_ordinary_speech_does_not_wake_her(matcher: WakeWordMatcher) -> None:
    assert matcher.detect("chrome kholo").matched is False
    assert matcher.detect("भारत की राजधानी क्या है?").matched is False


def test_a_word_containing_the_name_does_not_wake_her(matcher: WakeWordMatcher) -> None:
    assert matcher.detect("shraddhachrome kholo").matched is False


def test_known_spellings_survive_even_without_fuzzy_matching() -> None:
    strict = WakeWordMatcher(["shraddha"], fuzzy_distance=0)
    assert strict.matches("shraddha") is True
    assert strict.matches("shradha") is True, "a known ASR spelling, not a fuzzy guess"
    assert strict.matches("shraddhaa") is False, "only fuzzy matching accepts this"


def test_fuzzy_matching_widens_the_net() -> None:
    assert WakeWordMatcher(["shraddha"], fuzzy_distance=2).matches("shraddhaa") is True


def test_custom_phrases_are_honoured() -> None:
    custom = WakeWordMatcher(["computercore"], fuzzy_distance=0)
    assert custom.matches("computercore") is True
    assert custom.matches("shraddha") is False, "renaming her must stop the old name waking her"
    assert custom.detect("computercore chrome kholo").command == "chrome kholo"


# ------------------------------------------------------------------- stop phrase
@pytest.mark.parametrize(
    "phrase",
    [
        "मेरी बात सुनना बंद करो",
        "श्रद्धा, मेरी बात सुनना बंद करो।",
        "सुनना बन्द करो",
        "stop listening",
        "sunna band karo",
        "mute",
        "म्यूट करो",
    ],
)
def test_stop_phrases_are_recognised(phrase: str) -> None:
    assert contains_stop_phrase(phrase) is True


@pytest.mark.parametrize(
    "phrase",
    ["chrome kholo", "आज की तारीख बताओ", "कंप्यूटर बंद करो", "नमस्ते"],
)
def test_ordinary_sentences_are_not_stop_phrases(phrase: str) -> None:
    assert contains_stop_phrase(phrase) is False
