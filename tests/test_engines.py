"""Engine discovery: which recogniser exists, which model is present, what to say when neither is.

These tests never load a neural model. They check the *contract*: an engine that cannot
run must say so with an actionable Hindi sentence, and model discovery must be
deterministic on a directory layout.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from shraddha.speech.engines import (
    ENGINE_NAMES,
    AsrError,
    SherpaRecognizer,
    Transcript,
    VoskRecognizer,
    create_recognizer,
    engine_report,
    sherpa_engine,
    vosk_engine,
)
from shraddha.speech.engines.base import BaseRecognizer, module_available
from shraddha.speech.engines.vosk_engine import pcm_to_float


@pytest.fixture()
def models(tmp_path: Path) -> Path:
    root = tmp_path / "models"
    root.mkdir()
    return root


# ----------------------------------------------------------------- discovery
def test_none_means_no_recogniser_at_all() -> None:
    assert create_recognizer("none") is None


def dont_use(*_args, **_kwargs):  # pragma: no cover - sentinel
    raise AssertionError("must not be called")


def test_engine_report_covers_every_engine(models: Path) -> None:
    report = engine_report(models)
    assert set(report) == set(ENGINE_NAMES)
    for name, info in report.items():
        assert set(info) == {"package", "ready", "message"}
        assert info["ready"] is False, f"{name} cannot be ready without a model"
        assert info["message"], f"{name} must explain why it is not ready"


def test_an_unknown_engine_name_falls_back_to_auto(models: Path) -> None:
    # No engine is installed in the test environment, so both paths end at ``None``.
    assert create_recognizer("whisper", model_dir=models) is None


def test_module_availability_is_a_bool() -> None:
    assert isinstance(module_available("vosk"), bool)
    assert module_available("definitely_not_a_module_xyz") is False


# -------------------------------------------------------------- vosk models
def test_vosk_finds_an_extracted_model(models: Path) -> None:
    assert vosk_engine.find_model_dir(models) is None

    model = models / "vosk-model-small-hi-0.22"
    (model / "am").mkdir(parents=True)
    (model / "am" / "final.mdl").write_bytes(b"\x00")

    assert vosk_engine.find_model_dir(models) == model


def test_vosk_prefers_the_small_model(models: Path) -> None:
    for name in ("vosk-model-hi-0.22", "vosk-model-small-hi-0.22"):
        (models / name / "am").mkdir(parents=True)
        (models / name / "am" / "final.mdl").write_bytes(b"\x00")

    found = vosk_engine.find_model_dir(models)
    assert found is not None
    assert found.name == "vosk-model-small-hi-0.22"


def test_vosk_ignores_a_directory_without_model_files(models: Path) -> None:
    (models / "vosk-model-small-hi-0.22").mkdir()
    assert vosk_engine.find_model_dir(models) is None


def test_vosk_recognizer_can_be_pointed_straight_at_a_model(models: Path) -> None:
    recognizer = VoskRecognizer(model_dir=models / "vosk-model-small-hi-0.22")
    assert recognizer.name == "vosk"
    assert recognizer.is_loaded is False


def test_vosk_refuses_to_load_without_a_model(models: Path) -> None:
    recognizer = VoskRecognizer(model_dir=models)
    with pytest.raises(AsrError) as excinfo:
        recognizer.load()
    code = excinfo.value.code
    assert code in {"unavailable", "import_failed"}
    assert excinfo.value.user_message()


# ------------------------------------------------------------- sherpa models
def test_sherpa_needs_both_the_model_and_the_tokens(models: Path) -> None:
    hi = models / "hi"
    hi.mkdir()
    (hi / "model.int8.onnx").write_bytes(b"\x00")
    assert sherpa_engine.find_model(models) is None

    (hi / "tokens.txt").write_text("a 1\n", encoding="utf-8")
    found = sherpa_engine.find_model(models)
    assert found is not None
    assert found[0].name == "model.int8.onnx"


def test_sherpa_finds_an_indicconformer_folder(models: Path) -> None:
    directory = models / "indicconformer-hi"
    directory.mkdir()
    (directory / "model.onnx").write_bytes(b"\x00")
    (directory / "tokens.txt").write_text("a 1\n", encoding="utf-8")

    found = sherpa_engine.find_model(models)
    assert found is not None
    assert found[0].parent.name == "indicconformer-hi"


def test_sherpa_reports_what_to_download(models: Path) -> None:
    available, reason = SherpaRecognizer(model_dir=models).availability()
    if not module_available("sherpa_onnx"):
        assert available is False
        assert "sherpa" in reason
    else:  # pragma: no cover - only when the extra is installed
        assert available is False
        assert "fetch_models.py" in reason


# ----------------------------------------------------------------- utilities
def test_pcm_is_converted_to_normalised_floats() -> None:
    pcm = struct.pack("<3h", 0, 16384, -32768)
    assert pcm_to_float(pcm) == pytest.approx([0.0, 0.5, -1.0])


def test_pcm_conversion_ignores_a_trailing_odd_byte() -> None:
    assert pcm_to_float(b"\x00\x00\x01") == [0.0]


def test_a_transcript_knows_when_it_is_empty() -> None:
    assert Transcript(text="  ", engine="vosk").is_empty is True
    assert Transcript(text="क्रोम खोलो", engine="vosk").is_empty is False


def test_asr_error_carries_an_actionable_hint() -> None:
    error = AsrError("मॉडल नहीं मिला", hint="python scripts/fetch_models.py", code="unavailable")
    assert "मॉडल नहीं मिला" in error.user_message()
    assert "fetch_models.py" in error.user_message()
    assert AsrError("बस").user_message() == "बस"


class _StubRecognizer(BaseRecognizer):
    name = "stub"
    dependency = "definitely_not_a_module_xyz"

    def availability(self) -> tuple[bool, str]:
        return True, ""

    def find_model(self) -> Path | None:
        return None

    def _do_load(self) -> None:
        self.loaded_by_hook = True

    def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        return Transcript(text="", engine=self.name)


def test_a_recognizer_can_be_unloaded_and_reloaded() -> None:
    stub = _StubRecognizer()
    assert stub.is_loaded is False
    stub.load()
    assert stub.is_loaded is True
    assert stub.loaded_by_hook is True, "load() delegates the real work to _do_load()"
    stub.load()  # idempotent
    stub.unload()
    assert stub.is_loaded is False
    stub.close()
    assert stub.is_loaded is False


def test_an_unavailable_engine_never_loads() -> None:
    class Unavailable(_StubRecognizer):
        def availability(self) -> tuple[bool, str]:
            return False, "मॉडल नहीं है"

    with pytest.raises(AsrError):
        Unavailable().load()
