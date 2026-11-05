"""The compatibility seam: `shraddha.speech.asr` on top of the real engines."""

from __future__ import annotations

import pytest

from shraddha.speech.asr import SpeechRecognizer, UnavailableRecognizer, create_recognizer


def test_placeholder_reports_unavailable() -> None:
    recogniser = UnavailableRecognizer()
    assert recogniser.is_available is False
    assert recogniser.start() is False
    assert recogniser.stop() == ""
    recogniser.close()


def test_reason_is_hindi_and_actionable() -> None:
    reason = UnavailableRecognizer().unavailable_reason
    assert "fetch_models.py" in reason, "the message must say how to fix it"
    assert any("\u0900" <= char <= "\u097f" for char in reason), "reason must be in Devanagari"


def test_factory_returns_the_protocol() -> None:
    recogniser = create_recognizer()
    assert isinstance(recogniser, SpeechRecognizer)
    # No engine is installed in the test environment, so the honest placeholder is used.
    assert recogniser.name == "none"
    assert recogniser.is_available is False


def test_factory_never_returns_an_unusable_engine() -> None:
    recogniser = create_recognizer(models_dir=None)
    if recogniser.is_available:
        assert recogniser.unavailable_reason == ""
    else:
        assert "fetch_models.py" in recogniser.unavailable_reason


def test_protocol_requires_the_whole_contract() -> None:
    class Partial:
        name = "partial"

        @property
        def is_available(self) -> bool:
            return True

    assert not isinstance(Partial(), SpeechRecognizer)


@pytest.mark.parametrize("method", ["start", "stop", "close"])
def test_placeholder_survives_repeated_calls(method: str) -> None:
    recogniser = UnavailableRecognizer()
    getattr(recogniser, method)()
    getattr(recogniser, method)()
