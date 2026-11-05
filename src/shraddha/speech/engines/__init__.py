"""ASR engine registry.

Engine evaluation (see docs/VOICE.md for the full table):

| Engine | Model | Licence | Model size | Verdict |
|---|---|---|---|---|
| **Vosk** | `vosk-model-small-hi-0.22` | Apache-2.0 | 42 MB | default: lightest, 4 GB friendly |
| **sherpa-onnx** | IndicConformer Hindi int8 | CC-BY-4.0 | ~130 MB | opt-in: better accuracy, adds ONNX Runtime |
| whisper.cpp | Whisper small/base | MIT | 240-490 MB | rejected: heavier, slower on CPU |
| openWakeWord | custom "hey shraddha" | Apache-2.0 | ~2 MB | rejected: needs a training run, and a permanent always-on net |

``auto`` prefers Vosk because the project's first priority is resource use, not the last
percent of accuracy on a 4 GB laptop.
"""

from __future__ import annotations

from pathlib import Path

from shraddha.logging_setup import get_logger
from shraddha.speech.engines.base import AsrError, OfflineRecognizer, Transcript, module_available
from shraddha.speech.engines.sherpa_engine import SherpaRecognizer
from shraddha.speech.engines.vosk_engine import VoskRecognizer

log = get_logger("asr")

ENGINE_NAMES = ("vosk", "sherpa")

__all__ = [
    "ENGINE_NAMES",
    "AsrError",
    "OfflineRecognizer",
    "SherpaRecognizer",
    "Transcript",
    "VoskRecognizer",
    "create_recognizer",
    "engine_report",
]


def create_recognizer(
    engine: str = "auto",
    model_dir: Path | None = None,
    sample_rate: int = 16_000,
    num_threads: int = 2,
) -> OfflineRecognizer | None:
    """Build the best available recogniser, or ``None`` when no model is installed."""
    if engine == "none":
        return None

    order = ("vosk", "sherpa") if engine == "auto" else (engine,)
    if engine not in ("auto", "none") and engine not in ENGINE_NAMES:
        log.warning("unknown ASR engine %r, falling back to auto", engine)
        order = ("vosk", "sherpa")

    for name in order:
        recognizer = _build(name, model_dir, sample_rate, num_threads)
        if recognizer is None:
            continue
        available, reason = recognizer.availability()
        if available:
            log.info("using ASR engine %s", name)
            return recognizer
        log.debug("engine %s unavailable: %s", name, reason)

    log.info("no ASR engine available (install a model with scripts/fetch_models.py)")
    return None


def _build(
    name: str, model_dir: Path | None, sample_rate: int, num_threads: int
) -> VoskRecognizer | SherpaRecognizer | None:
    if name == "vosk":
        return VoskRecognizer(model_dir=model_dir, sample_rate=sample_rate)
    if name == "sherpa":
        return SherpaRecognizer(
            model_dir=model_dir, sample_rate=sample_rate, num_threads=num_threads
        )
    return None


def engine_report(models_dir: Path) -> dict[str, dict[str, object]]:
    """Per-engine status for ``--doctor``: installed, model present, message."""
    report: dict[str, dict[str, object]] = {}
    for name in ENGINE_NAMES:
        engine = _build(name, models_dir, 16_000, 2)
        if engine is None:  # pragma: no cover - defensive
            continue
        available, reason = engine.availability()
        report[name] = {
            "package": module_available(engine.dependency),
            "ready": available,
            "message": reason,
        }
    return report
