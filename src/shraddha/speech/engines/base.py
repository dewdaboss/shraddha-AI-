"""Shared contract for offline ASR engines.

The two shipped engines differ in almost everything except this interface, which is why
:class:`~shraddha.speech.service.VoiceService` never mentions a vendor.

Rules every engine must follow:

* the heavy import happens in :meth:`load`, never at module import;
* :meth:`unload` must actually release memory (that is the whole point of the split);
* a missing model is an :class:`AsrError` with a message the UI can show verbatim.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from shraddha.logging_setup import get_logger

log = get_logger("asr")


class AsrError(RuntimeError):
    """A recognition failure with a user-facing explanation."""

    def __init__(self, message: str, *, hint: str = "", code: str = "asr_error") -> None:
        super().__init__(message)
        self.hint = hint
        self.code = code

    def user_message(self) -> str:
        return f"{self}\n({self.hint})" if self.hint else str(self)


@dataclass(frozen=True, slots=True)
class Transcript:
    """One recognition result."""

    text: str
    engine: str
    duration_s: float = 0.0
    confidence: float | None = None

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


@runtime_checkable
class OfflineRecognizer(Protocol):
    """Transcribe one complete utterance (PCM int16, mono)."""

    name: str

    @property
    def is_loaded(self) -> bool:
        """True while the model occupies memory."""

    def load(self) -> None:
        """Load the model. Raises :class:`AsrError` when that is impossible."""

    def unload(self) -> None:
        """Release the model and its memory."""

    def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        """Recognise one utterance. Raises :class:`AsrError` on failure."""

    def close(self) -> None:
        """Unload and release everything (engine shutdown)."""


def module_available(module_name: str) -> bool:
    """True when a module can be imported, without importing it."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


class BaseRecognizer:
    """Common behaviour: model discovery, load/unload bookkeeping, safe cleanup."""

    name = "base"
    dependency: str = ""

    def __init__(self, model_dir: Path | None = None) -> None:
        self.model_dir = Path(model_dir) if model_dir else None
        self._loaded = False

    # ------------------------------------------------------------------- state
    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def dependency_installed(self) -> bool:
        return module_available(self.dependency) if self.dependency else True

    def unload(self) -> None:
        self._release()
        self._loaded = False
        log.info("%s model unloaded", self.name)

    def close(self) -> None:
        self.unload()

    def load(self) -> None:
        """Load the model, translating any failure into an actionable ``AsrError``."""
        if self._loaded:
            return
        available, reason = self.availability()
        if not available:
            raise AsrError("वाक् पहचान इंजन उपलब्ध नहीं है।", hint=reason, code="unavailable")
        self._do_load()
        self._loaded = True

    # ---------------------------------------------------------------- to override
    def availability(self) -> tuple[bool, str]:
        raise NotImplementedError

    def find_model(self) -> Path | None:
        raise NotImplementedError

    def _release(self) -> None:
        """Drop references so the model can be garbage collected."""

    def _do_load(self) -> None:
        raise NotImplementedError
