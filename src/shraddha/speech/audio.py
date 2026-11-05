"""Microphone capture through PortAudio (optional ``sounddevice`` dependency).

Everything here is defensive on purpose: a desktop assistant that cannot open the
microphone must say *why* in words a user can act on, not raise a traceback. Every
failure becomes a :class:`MicrophoneError` with a Hindi message plus an English hint
that names the missing package or the OS-level cause.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType
from typing import Any

from shraddha.logging_setup import get_logger

log = get_logger("audio")

NO_MIC_HINDI = "माइक्रोफ़ोन उपलब्ध नहीं है।"


class MicrophoneError(RuntimeError):
    """Raised when the microphone cannot be opened. Carries a user-facing message."""

    def __init__(self, message: str, *, hint: str = "", code: str = "unavailable") -> None:
        super().__init__(message)
        self.hint = hint
        self.code = code

    def user_message(self) -> str:
        return f"{self}\n({self.hint})" if self.hint else str(self)


@dataclass(frozen=True, slots=True)
class InputDevice:
    index: int
    name: str
    channels: int
    is_default: bool

    def __str__(self) -> str:
        marker = " (default)" if self.is_default else ""
        return f"{self.name}{marker}"


def _load_sounddevice() -> tuple[ModuleType | None, str | None]:
    """Import ``sounddevice`` lazily, translating every failure into a reason."""
    if sys.platform == "win32" and sys.version_info >= (3, 13):
        log.debug("sounddevice on Python 3.13+ may lack a wheel; checking anyway")
    try:
        import sounddevice
    except ImportError:
        return None, ("microphone support is not installed - run: pip install -e '.[audio]'")
    except OSError as exc:  # PortAudio shared library missing
        return None, f"PortAudio library not found ({exc}) - reinstall the 'audio' extra"
    return sounddevice, None


def availability() -> tuple[bool, str]:
    """Can we capture audio right now? ``(ok, reason)``."""
    module, error = _load_sounddevice()
    if module is None:
        return False, error or "unknown audio problem"
    try:
        devices = module.query_devices()
    except Exception as exc:  # PortAudio can fail at query time too
        return False, f"cannot query audio devices ({exc})"
    if not any(int(entry.get("max_input_channels", 0)) > 0 for entry in devices):
        return False, "no microphone was found on this computer"
    return True, ""


def list_input_devices() -> list[InputDevice]:
    """Input devices, or an empty list when audio is unavailable."""
    module, error = _load_sounddevice()
    if module is None:
        log.debug("audio unavailable: %s", error)
        return []
    try:
        default_index = -1
        with contextlib.suppress(Exception):
            default_index = int(module.default.device[0])
        return [
            InputDevice(
                index=index,
                name=str(entry.get("name", f"input {index}")),
                channels=int(entry.get("max_input_channels", 0)),
                is_default=index == default_index,
            )
            for index, entry in enumerate(module.query_devices())
            if int(entry.get("max_input_channels", 0)) > 0
        ]
    except Exception as exc:
        log.warning("could not list input devices: %s", exc)
        return []


class AudioCapture:
    """16 kHz mono int16 capture with a frame callback.

    PortAudio performs the resampling from the device's native rate, which is why we
    request the rate the speech models want instead of resampling in Python.
    """

    def __init__(
        self,
        device: str | int | None = None,
        sample_rate: int = 16_000,
        frame_ms: int = 20,
    ) -> None:
        self.device = device
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self._stream: Any | None = None
        self._module: ModuleType | None = None
        self._callback: Callable[[bytes], None] | None = None

    @property
    def frame_samples(self) -> int:
        return self.sample_rate * self.frame_ms // 1000

    @property
    def is_running(self) -> bool:
        return self._stream is not None

    def start(self, callback: Callable[[bytes], None]) -> None:
        """Open the stream. Raises :class:`MicrophoneError` with a usable message."""
        if self.is_running:
            return
        module, error = _load_sounddevice()
        if module is None:
            raise MicrophoneError(
                f"{NO_MIC_HINDI} ऑडियो इंजन नहीं मिला।",
                hint=error or "",
                code="no_backend",
            )
        self._module = module
        self._callback = callback

        def _on_audio(indata: Any, frames: int, time_info: Any, status: Any) -> None:
            if status:
                log.debug("audio status flag: %s", status)
            try:
                if self._callback is not None:
                    self._callback(bytes(indata))
            except Exception:  # never propagate into PortAudio's thread
                log.exception("audio callback failed")

        try:
            stream = module.InputStream(
                samplerate=self.sample_rate,
                blocksize=self.frame_samples,
                device=self.device,
                channels=1,
                dtype="int16",
                callback=_on_audio,
            )
            stream.start()
        except Exception as exc:
            raise MicrophoneError(
                f"{NO_MIC_HINDI} माइक्रोफ़ोन खोला नहीं जा सका।",
                hint=(
                    f"{exc} — check Windows Settings > Privacy > Microphone, and that no "
                    "other app is holding the device"
                ),
                code="open_failed",
            ) from exc
        self._stream = stream
        log.info("microphone open at %s Hz (%s)", self.sample_rate, self.device or "default")

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        self._callback = None
        if stream is None:
            return
        with contextlib.suppress(Exception):
            stream.stop()
        with contextlib.suppress(Exception):
            stream.close()
        log.info("microphone closed")

    def __enter__(self) -> AudioCapture:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()
