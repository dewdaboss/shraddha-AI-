"""Compatibility seam for callers that only need a recogniser object.

Phase 2 delivered real recognition in :mod:`shraddha.speech.engines`; this module keeps
the small Phase 1 interface (`start()` / `stop()` → one transcript) working on top of it,
so nothing that used the old seam has to change.

New code should prefer :class:`shraddha.speech.service.VoiceService`, which streams, runs
the VAD and owns the idle-unload policy.

Rules preserved from Phase 1:

* no ASR import at module import time (a model costs 100+ MB, an engine wheel costs more);
* an engine that cannot run never pretends to: it reports why, in Hindi.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from shraddha.logging_setup import get_logger
from shraddha.speech.engines import create_recognizer as create_engine

log = get_logger("asr")

NO_ENGINE_MESSAGE = (
    "हिन्दी आवाज़ से सुनना अभी तैयार नहीं है। मॉडल डाउनलोड कीजिए: "
    "python scripts/fetch_models.py --set asr-light"
)


@runtime_checkable
class SpeechRecognizer(Protocol):
    """Microphone → Hindi text, one utterance at a time."""

    name: str

    @property
    def is_available(self) -> bool:
        """True when a model is present and the engine imported successfully."""

    @property
    def unavailable_reason(self) -> str:
        """Human-readable explanation shown in the UI when ``is_available`` is False."""

    def start(self) -> bool:
        """Begin listening. Returns False if the engine could not start."""

    def stop(self) -> str:
        """Stop listening and return the final transcript (possibly empty)."""

    def close(self) -> None:
        """Release the model and any child process."""


class UnavailableRecognizer:
    """Returned when no engine can run; an honest no-op rather than a fake."""

    name = "none"
    _REASON = NO_ENGINE_MESSAGE

    @property
    def is_available(self) -> bool:
        return False

    @property
    def unavailable_reason(self) -> str:
        return self._REASON

    def start(self) -> bool:
        log.debug("recogniser unavailable: %s", self._REASON)
        return False

    def stop(self) -> str:
        return ""

    def close(self) -> None:
        return None


class EngineRecognizer:
    """Adapts an :class:`~shraddha.speech.engines.base.OfflineRecognizer` to this seam.

    Audio capture is not part of this adapter; the caller feeds PCM into
    :meth:`feed` and receives a transcript once the utterance is complete.
    """

    def __init__(self, engine, models_dir: Path | None = None) -> None:
        self._engine = engine
        self._models_dir = models_dir
        self.name = engine.name

    @property
    def is_available(self) -> bool:
        return True

    @property
    def unavailable_reason(self) -> str:
        return ""

    def start(self) -> bool:
        self._engine.load()
        return True

    def stop(self) -> str:
        return ""

    def transcribe(self, pcm: bytes, sample_rate: int = 16_000) -> str:
        return self._engine.transcribe(pcm, sample_rate).text

    def close(self) -> None:
        self._engine.close()


def create_recognizer(matcher=None, models_dir: Path | None = None) -> SpeechRecognizer:
    """Build the best available engine, or an unavailable placeholder.

    ``matcher`` is accepted for backwards compatibility with the Phase 1 signature and is
    no longer used: matching moved to :mod:`shraddha.speech.wake`.
    """
    engine = create_engine(engine="auto", model_dir=models_dir)
    if engine is None:
        return UnavailableRecognizer()
    available, reason = engine.availability()
    if not available:
        log.debug("engine %s unavailable: %s", engine.name, reason)
        return UnavailableRecognizer()
    return EngineRecognizer(engine, models_dir)
