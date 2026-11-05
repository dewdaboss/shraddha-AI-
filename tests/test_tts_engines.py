"""Voice output: engine selection, voice cycling, and never crashing mid-sentence.

The actual synthesisers need Windows (SAPI) or a 63 MB model (Piper), so the tests cover
the parts that decide *what* would be spoken: the fallback policy, the voice list, and
the safety wrapper.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shraddha.speech import tts
from shraddha.speech.tts import (
    NONE,
    ONE_CORE,
    PIPER,
    NullTts,
    PiperTts,
    RecordingTts,
    WindowsSapiTts,
    create_engine,
    next_voice,
    piper_model_path,
    select_engine,
    speak_safely,
    voice_options,
)


# --------------------------------------------------------------------- engines
def test_the_null_engine_says_nothing_and_never_fails() -> None:
    engine = NullTts()
    assert engine.is_available is False
    assert engine.speak("नमस्ते") is False
    engine.stop()
    engine.close()


def test_the_recording_engine_captures_sentences() -> None:
    engine = RecordingTts()
    assert engine.speak("नमस्ते!") is True
    assert engine.spoken == ["नमस्ते!"]


def test_a_failing_engine_reports_false() -> None:
    assert RecordingTts(succeed=False).speak("कुछ") is False


@pytest.mark.skipif(tts.is_windows(), reason="guarded on non-Windows platforms")
def test_sapi_is_unavailable_off_windows() -> None:
    assert WindowsSapiTts().is_available is False
    assert WindowsSapiTts().speak("नमस्ते") is False


def test_piper_needs_its_model_file(tmp_path: Path) -> None:
    assert PiperTts(tmp_path / "missing.onnx").is_available is False
    assert PiperTts(tmp_path / "missing.onnx").speak("नमस्ते") is False


# ------------------------------------------------------------- engine selection
def test_an_explicit_unusable_engine_degrades_to_text() -> None:
    assert select_engine(ONE_CORE, {ONE_CORE: False, PIPER: False}) == NONE


def test_none_is_honoured() -> None:
    assert select_engine(NONE, {ONE_CORE: True, PIPER: True}) == NONE


def test_auto_prefers_the_free_windows_voice() -> None:
    assert select_engine("auto", {ONE_CORE: True, PIPER: True}) == ONE_CORE
    assert select_engine("auto", {ONE_CORE: False, PIPER: True}) == PIPER
    assert select_engine("auto", {}) == NONE


def test_create_engine_falls_back_to_silence(tmp_path: Path) -> None:
    engine = create_engine("auto", models_dir=tmp_path)
    if not tts.is_windows():
        assert isinstance(engine, NullTts)


def test_create_engine_accepts_piper_models_from_disk(tmp_path: Path) -> None:
    model = tmp_path / "hi_IN-priyamvada-medium.onnx"
    model.write_bytes(b"\x00")
    assert piper_model_path(None, tmp_path) == model
    assert piper_model_path(str(model), tmp_path) == model
    assert piper_model_path(str(tmp_path / "nope.onnx"), tmp_path) is None


# ------------------------------------------------------------------- voice list
def test_voice_options_lists_piper_models(tmp_path: Path) -> None:
    (tmp_path / "hi_IN-priyamvada-medium.onnx").write_bytes(b"\x00")
    options = voice_options(None, tmp_path)
    assert "hi_IN-priyamvada-medium" in options


def test_voice_options_is_empty_without_any_voice(tmp_path: Path) -> None:
    if not tts.is_windows():
        assert voice_options(None, tmp_path) == []


def test_next_voice_cycles_and_wraps() -> None:
    options = ["कल्पना", "हेमंत", "hi_IN-priyamvada-medium"]
    assert next_voice(None, options) == "कल्पना"
    assert next_voice("कल्पना", options) == "हेमंत"
    assert next_voice("हेमंत", options) == "hi_IN-priyamvada-medium"
    assert next_voice("hi_IN-priyamvada-medium", options) == "कल्पना"


def test_next_voice_survives_a_stale_selection() -> None:
    assert next_voice("gone", ["a", "b"]) == "a"
    assert next_voice("a", []) is None


# ----------------------------------------------------------------- speak safely
def test_speak_safely_uses_the_engine() -> None:
    engine = RecordingTts()
    assert speak_safely(engine, "नमस्ते") is True
    assert engine.spoken == ["नमस्ते"]


def test_speak_safely_ignores_blank_text() -> None:
    engine = RecordingTts()
    assert speak_safely(engine, "   ") is False
    assert engine.spoken == []


def test_speak_safely_swallows_engine_exceptions() -> None:
    class Exploding:
        def speak(self, text: str) -> bool:
            raise RuntimeError("COM apartment died")

    assert speak_safely(Exploding(), "नमस्ते") is False


def test_speak_safely_tolerates_objects_without_speak() -> None:
    assert speak_safely(object(), "नमस्ते") is False


def test_every_engine_name_has_a_description() -> None:
    for name in (ONE_CORE, PIPER, NONE):
        assert tts.describe_engine(name)
