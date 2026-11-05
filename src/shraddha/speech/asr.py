"""Speech recognition seam for Phase 2.

Nothing here recognises speech yet. What it *does* provide is the interface the UI
already talks to, so Phase 2 can drop in sherpa-onnx / Vosk without touching the
overlay, the tray or the assistant wiring.

Design rules for the Phase 2 implementation:

* never import the ASR engine at module import time (it costs ~150 MB);
* load the model on first ``start()``, release it on ``stop()``;
* run recognition in a child process so the memory can actually be reclaimed.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from shraddha.logging_setup import get_logger

log = get_logger("asr")


@runtime_checkable
class SpeechRecognizer(Protocol):
    """Streaming microphone → Hindi text."""

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
    """Placeholder used until Phase 2 lands.

    It is intentionally an honest no-op: the microphone button keeps working as a UI
    control, but the assistant never pretends to have heard something.
    """

    name = "none"
    _REASON = "हिन्दी आवाज़ से सुनना अभी उपलब्ध नहीं है (Phase 2)। अभी कृपया टाइप करके लिखिए।"

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


def create_recognizer() -> SpeechRecognizer:
    """Factory used by the UI. Phase 2 returns a real engine here."""
    return UnavailableRecognizer()
