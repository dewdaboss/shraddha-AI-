"""sherpa-onnx engine: better Hindi accuracy, still small and CPU-only.

Uses NeMo-CTC Hindi models (IndicConformer int8, CC-BY-4.0) through the Apache-2.0
``sherpa-onnx`` runtime, which pulls in ONNX Runtime but **not** PyTorch.

Why it is not the default: ONNX Runtime adds ~60-90 MB of resident memory even before
the model loads, which matters on a 4 GB machine. It is the recommended engine once a
model is installed and the machine has 8 GB.
"""

from __future__ import annotations

from pathlib import Path

from shraddha.logging_setup import get_logger
from shraddha.speech.engines.base import AsrError, BaseRecognizer, Transcript

log = get_logger("asr.sherpa")

MODEL_FILE_CANDIDATES = ("model.int8.onnx", "model.onnx", "model.fp16.onnx")
TOKENS_FILE = "tokens.txt"


def find_model(models_dir: Path) -> tuple[Path, Path] | None:
    """Locate ``(model.onnx, tokens.txt)`` for any Hindi NeMo-CTC export.

    Search order is explicit so a user can drop a model anywhere sensible:
    ``<models>/hi/model.int8.onnx`` first, then any ``indicconformer*/`` folder.
    """
    root = Path(models_dir)
    if not root.exists():
        return None

    candidates: list[Path] = [root / "hi", root]
    candidates.extend(sorted(p for p in root.glob("indicconformer*") if p.is_dir()))
    candidates.extend(sorted(p for p in root.glob("sherpa-onnx-*hi*") if p.is_dir()))

    for directory in candidates:
        if not directory.is_dir():
            continue
        model = next(
            (directory / name for name in MODEL_FILE_CANDIDATES if (directory / name).is_file()),
            None,
        )
        tokens = directory / TOKENS_FILE
        if model is not None and tokens.is_file():
            return model, tokens
    return None


class SherpaRecognizer(BaseRecognizer):
    """Wraps ``sherpa_onnx.OfflineRecognizer`` (NeMo CTC)."""

    name = "sherpa"
    dependency = "sherpa_onnx"

    def __init__(
        self,
        model_dir: Path | None = None,
        sample_rate: int = 16_000,
        num_threads: int = 2,
    ) -> None:
        super().__init__(model_dir)
        self.sample_rate = sample_rate
        self.num_threads = max(1, num_threads)
        self._recognizer = None

    # ------------------------------------------------------------------ models
    def find_model(self) -> tuple[Path, Path] | None:
        if self.model_dir is None:
            return None
        found = find_model(self.model_dir)
        if found:
            return found
        return find_model(self.model_dir.parent)

    def availability(self) -> tuple[bool, str]:
        if not self.dependency_installed:
            return False, "sherpa-onnx इंजन स्थापित नहीं है - pip install -e '.[asr]'"
        if self.find_model() is None:
            return False, (
                "हिन्दी IndicConformer मॉडल नहीं मिला - python scripts/fetch_models.py --set asr-main"
            )
        return True, ""

    # -------------------------------------------------------------------- load
    def _do_load(self) -> None:
        try:
            import sherpa_onnx
        except ImportError as exc:  # pragma: no cover - guarded by availability()
            raise AsrError(
                "sherpa-onnx आयात नहीं हो सका।", hint=str(exc), code="import_failed"
            ) from exc

        found = self.find_model()
        if found is None:  # pragma: no cover - availability() guarantees a model
            raise AsrError("इंडिक कन्फॉर्मर मॉडल नहीं मिला।", hint="model missing", code="unavailable")
        model_path, tokens_path = found
        try:
            self._recognizer = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
                model=str(model_path),
                tokens=str(tokens_path),
                num_threads=self.num_threads,
                decoding_method="greedy_search",
                debug=False,
                provider="cpu",
            )
        except Exception as exc:
            self._release()
            raise AsrError("मॉडल लोड नहीं हो सका।", hint=str(exc), code="load_failed") from exc

        log.info("sherpa model loaded from %s (%s threads)", model_path, self.num_threads)

    def _release(self) -> None:
        self._recognizer = None

    # --------------------------------------------------------------- recognise
    def transcribe(self, pcm: bytes, sample_rate: int = 16_000) -> Transcript:
        if not self._loaded or self._recognizer is None:
            raise AsrError("मॉडल लोड नहीं है।", hint="call load() first", code="not_loaded")
        if not pcm:
            return Transcript(text="", engine=self.name)

        from shraddha.speech.engines.vosk_engine import pcm_to_float  # shared helper

        try:
            stream = self._recognizer.create_stream()
            stream.accept_waveform(sample_rate, pcm_to_float(pcm))
            self._recognizer.decode_stream(stream)
            text = str(stream.result.text).strip()
        except Exception as exc:
            raise AsrError("पहचान में त्रुटि हुई।", hint=str(exc), code="decode_failed") from exc

        return Transcript(
            text=text,
            engine=self.name,
            duration_s=len(pcm) / 2 / max(1, sample_rate),
        )
