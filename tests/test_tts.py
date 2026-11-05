"""Tests for TTS engine detection and selection policy.

These run on Linux too: the Windows registry lookups short-circuit to an empty result,
which is exactly the degradation path a Windows machine with no Hindi voice takes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from shraddha.speech import tts


def test_voice_hindi_detection() -> None:
    hindi = tts.Voice(
        token="MSTTS_V110_hiIN_HemantM", name="Microsoft Hemant", language="hi-IN", engine="onecore"
    )
    english = tts.Voice(
        token="MSTTS_V110_enUS_ZiraM", name="Microsoft Zira", language="en-US", engine="onecore"
    )
    assert hindi.is_hindi
    assert not english.is_hindi


def test_voice_string_is_human_readable() -> None:
    voice = tts.Voice(token="t", name="Hemant", language="hi-IN", engine="onecore")
    assert str(voice) == "Hemant [hi-IN] (onecore)"


@pytest.mark.skipif(sys.platform == "win32", reason="asserts the non-Windows degradation path")
def test_no_voices_off_windows() -> None:
    assert tts.list_windows_voices() == ()
    assert tts.hindi_voices() == ()


def test_hindi_voices_filter_and_prefer_onecore() -> None:
    pool = (
        tts.Voice("sapi_hi", "Legacy Hemant", "hi-IN", "sapi"),
        tts.Voice("one_hi", "Hemant", "hi-IN", "onecore"),
        tts.Voice("one_en", "Zira", "en-US", "onecore"),
    )
    voices = tts.hindi_voices(pool)
    assert [v.token for v in voices] == ["one_hi", "sapi_hi"]


def test_piper_model_discovery(tmp_path: Path) -> None:
    models = tmp_path / "models"
    (models / "piper" / "hi").mkdir(parents=True)
    assert tts.piper_model_path(None, models) is None

    model = models / "piper" / "hi" / "hi_IN-priyamvada-medium.onnx"
    model.write_bytes(b"")
    assert tts.piper_model_path(None, models) == model
    assert tts.piper_model_path(str(model), models) == model
    assert tts.piper_model_path(str(tmp_path / "missing.onnx"), models) is None


def test_available_engines_reports_both(tmp_path: Path) -> None:
    engines = tts.available_engines(tmp_path)
    assert set(engines) == {"onecore", "piper"}
    assert engines["piper"] is False


@pytest.mark.parametrize(
    ("configured", "engines", "expected"),
    [
        ("auto", {"onecore": True, "piper": True}, "onecore"),  # zero-cost wins
        ("auto", {"onecore": False, "piper": True}, "piper"),  # fall back to neural
        ("auto", {"onecore": False, "piper": False}, "none"),  # degrade to text
        ("piper", {"onecore": True, "piper": True}, "piper"),  # explicit choice honoured
        ("piper", {"onecore": True, "piper": False}, "none"),  # explicit but missing
        ("onecore", {"onecore": False, "piper": True}, "none"),
        ("none", {"onecore": True, "piper": True}, "none"),  # user disabled speech
    ],
)
def test_select_engine_policy(configured: str, engines: dict[str, bool], expected: str) -> None:
    assert tts.select_engine(configured, engines) == expected


def test_engine_descriptions_mention_licence_risk() -> None:
    assert "non-commercial" in tts.describe_engine("piper")
    assert "Windows" in tts.describe_engine("onecore")
