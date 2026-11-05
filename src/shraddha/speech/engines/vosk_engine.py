"""Vosk engine: the lightest credible Hindi ASR (Apache-2.0, ~42 MB model).

Why Vosk survives the evaluation:

* the small Hindi model is 42 MB and runs in roughly 100-200 MB of RSS on a CPU core;
* no PyTorch, no ONNX Runtime, no GPU - one ``pip install vosk`` wheel;
* it accepts a **grammar**, so the same model can be restricted to a handful of wake
  phrases and stop hallucinating full sentences while nobody is talking.

Trade-off: accuracy is below sherpa-onnx/Whisper on accented or noisy speech. This is
the engine for 4 GB machines and for the always-listening wake path.
"""

from __future__ import annotations

import json
from array import array
from pathlib import Path

from shraddha.logging_setup import get_logger
from shraddha.speech.engines.base import AsrError, BaseRecognizer, Transcript

log = get_logger("asr.vosk")

MODEL_GLOBS = ("vosk-model-small-hi*", "vosk-model-hi*")


def looks_like_model(directory: Path) -> bool:
    """True for an extracted Vosk model (``*.mdl`` at the root or in ``am/``)."""
    if any(directory.glob("*.mdl")):
        return True
    return (directory / "am" / "final.mdl").is_file()


def find_model_dir(models_dir: Path) -> Path | None:
    """Locate an extracted Vosk Hindi model directory, preferring the small one."""
    root = Path(models_dir)
    if not root.exists():
        return None
    for pattern in MODEL_GLOBS:
        for candidate in sorted(root.glob(pattern)):
            if candidate.is_dir() and looks_like_model(candidate):
                return candidate
    return None


class VoskRecognizer(BaseRecognizer):
    """Wraps ``vosk.KaldiRecognizer`` for one utterance at a time."""

    name = "vosk"
    dependency = "vosk"

    def __init__(
        self,
        model_dir: Path | None = None,
        sample_rate: int = 16_000,
        grammar: list[str] | None = None,
    ) -> None:
        super().__init__(model_dir)
        self.sample_rate = sample_rate
        self.grammar = grammar
        self._model = None
        self._recognizer = None

    # ------------------------------------------------------------------ models
    def find_model(self) -> Path | None:
        if self.model_dir is None:
            return None
        if looks_like_model(self.model_dir):
            return self.model_dir
        return find_model_dir(self.model_dir)

    def availability(self) -> tuple[bool, str]:
        if not self.dependency_installed:
            return False, "vosk इंजन स्थापित नहीं है - pip install -e '.[asr-vosk]'"
        model = self.find_model()
        if model is None:
            return False, (
                "हिन्दी Vosk मॉडल नहीं मिला - python scripts/fetch_models.py --set asr-light"
            )
        return True, ""

    # ------------------------------------------------------------------- load
    def _do_load(self) -> None:
        try:
            import vosk
        except ImportError as exc:  # pragma: no cover - guarded by availability()
            raise AsrError("vosk आयात नहीं हो सका।", hint=str(exc), code="import_failed") from exc

        model_path = self.find_model()
        if model_path is None:  # pragma: no cover - availability() guarantees a model
            raise AsrError("हिन्दी Vosk मॉडल नहीं मिला।", hint="model missing", code="unavailable")
        try:
            vosk.SetLogLevel(-1)  # Kaldi is extremely chatty on stderr
            self._model = vosk.Model(str(model_path))
            self._recognizer = (
                vosk.KaldiRecognizer(self._model, self.sample_rate, json.dumps(self.grammar))
                if self.grammar
                else vosk.KaldiRecognizer(self._model, self.sample_rate)
            )
        except Exception as exc:
            self._release()
            raise AsrError("मॉडल लोड नहीं हो सका।", hint=f"{exc}", code="load_failed") from exc

        log.info("vosk model loaded from %s (grammar=%s)", model_path, bool(self.grammar))

    def _release(self) -> None:
        self._recognizer = None
        self._model = None

    # -------------------------------------------------------------- recognise
    def transcribe(self, pcm: bytes, sample_rate: int = 16_000) -> Transcript:
        if not self._loaded or self._recognizer is None:
            raise AsrError("मॉडल लोड नहीं है।", hint="call load() first", code="not_loaded")
        if not pcm:
            return Transcript(text="", engine=self.name)

        try:
            self._recognizer.Reset()
            accepted = self._recognizer.AcceptWaveform(self._resample_if_needed(pcm, sample_rate))
            payload = self._recognizer.Result() if accepted else self._recognizer.FinalResult()
            text = str(json.loads(payload).get("text", "")).strip()
        except Exception as exc:
            raise AsrError("पहचान में त्रुटि हुई।", hint=str(exc), code="decode_failed") from exc

        return Transcript(
            text=text,
            engine=self.name,
            duration_s=len(pcm) / 2 / max(1, sample_rate),
            confidence=None,
        )

    @staticmethod
    def _resample_if_needed(pcm: bytes, sample_rate: int) -> bytes:
        """Vosk models are 16 kHz; refuse anything else rather than decode garbage."""
        if sample_rate == 16_000:
            return pcm
        raise AsrError(
            "नमूना दर असमर्थित है।",
            hint=f"vosk expects 16000 Hz, got {sample_rate} Hz",
            code="bad_sample_rate",
        )


def pcm_to_float(pcm: bytes) -> list[float]:
    """Helper shared by engines that want normalised floats."""
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    return [value / 32768.0 for value in samples]
