"""Tests for the Phase 1 reply engine: Hindi, Hinglish, honesty about the fallback."""

from __future__ import annotations

from datetime import datetime

import pytest

from shraddha.assistant import (
    FALLBACK_TEXT,
    HELP_TEXT,
    KIND_ASSISTANT,
    Assistant,
    Reply,
    normalise,
)

FIXED = datetime(2026, 11, 5, 9, 30)  # a Thursday


@pytest.fixture()
def assistant() -> Assistant:
    return Assistant(language="hi", now=lambda: FIXED)


def test_reply_kind_is_assistant(assistant: Assistant) -> None:
    assert assistant.respond("नमस्ते").kind == KIND_ASSISTANT


@pytest.mark.parametrize("text", ["नमस्ते", "namaste", "Hello", "नमस्कार!"])
def test_greeting(assistant: Assistant, text: str) -> None:
    reply = assistant.respond(text)
    assert reply.intent == "greeting"
    assert "श्रद्धा" in reply.text


@pytest.mark.parametrize("text", ["समय क्या है?", "kitne baje hain", "time", "अभी कितने बजे हैं"])
def test_time_uses_the_injected_clock(assistant: Assistant, text: str) -> None:
    reply = assistant.respond(text)
    assert reply.intent == "time"
    assert "09:30" in reply.text


@pytest.mark.parametrize("text", ["आज कौन सी तारीख़ है?", "aaj ki tarikh", "date"])
def test_date_is_hindi(assistant: Assistant, text: str) -> None:
    reply = assistant.respond(text)
    assert reply.intent == "date"
    assert "गुरुवार" in reply.text  # 2026-11-05 is a Thursday
    assert "नवंबर" in reply.text
    assert "5" in reply.text and "2026" in reply.text


def test_nukta_variants_match_the_same_intent(assistant: Assistant) -> None:
    with_nukta = assistant.respond("तारीख़")
    without = assistant.respond("तारीख")
    assert with_nukta.intent == without.intent == "date"


def test_help_lists_what_works(assistant: Assistant) -> None:
    reply = assistant.respond("मदद")
    assert reply.intent == "help"
    assert reply.text == HELP_TEXT
    assert "Phase 2" in reply.text


@pytest.mark.parametrize("text", ["तुम कौन हो?", "who are you", "tum kaun ho"])
def test_identity_explains_local_only(assistant: Assistant, text: str) -> None:
    reply = assistant.respond(text)
    assert reply.intent == "identity"
    assert "ऑफ़लाइन" in reply.text
    assert "API" in reply.text


def test_thanks(assistant: Assistant) -> None:
    assert assistant.respond("धन्यवाद").intent == "thanks"


def test_unknown_question_is_an_honest_fallback(assistant: Assistant) -> None:
    reply = assistant.respond("भारत की राजधानी क्या है?")
    assert reply.intent == "fallback"
    assert reply.is_fallback
    assert reply.text == FALLBACK_TEXT
    assert "Phase 6" in reply.text, "the fallback must say what is actually missing"


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_empty_input_asks_for_input(assistant: Assistant, text: str) -> None:
    reply = assistant.respond(text)
    assert reply.intent == "empty"
    assert reply.text


def test_respond_never_raises(assistant: Assistant) -> None:
    for odd in ["<script>alert(1)</script>", "🙏", "x" * 5000, "\x00"]:
        assert isinstance(assistant.respond(odd), Reply)


def test_normalise_strips_punctuation_and_case() -> None:
    assert normalise("  समय क्या है? ") == "समय क्या है"
    assert normalise("TIME!") == "time"


def test_match_intent_prefers_specific_over_greeting() -> None:
    # "hello, time kya hai" contains both a greeting and a time request.
    assert Assistant.match_intent(normalise("hello time kya hai")) == "time"


def test_default_clock_is_used_when_not_injected() -> None:
    reply = Assistant().respond("समय")
    assert reply.intent == "time"
    assert ":" in reply.text
