"""Hindi text-to-speech engines.

Two engines, both free, both fully offline:

* ``onecore`` - the voices that ship with Windows (Hindi: Hemant / Kalpana). Zero
  download, zero extra RAM, licensed with the OS, commercially safe.
* ``piper``   - neural VITS voices (``hi_IN-pratham``, ``hi_IN-priyamvada``, ``hi_IN-rohan``),
  roughly 63 MB each, far more natural. **Non-commercial licence** - see
  THIRD-PARTY-NOTICES.md before using in a paid product.

The detection half (:func:`available_engines`, :func:`hindi_voices`) was built in Phase 0
and stays dependency-free: Windows voices are read straight from the registry with
:mod:`winreg`, so ``--doctor`` works without pywin32 or COM. Phase 2 added the synthesis
half at the bottom of the file (:class:`WindowsSapiTts`, :class:`PiperTts`,
:class:`NullTts`, :func:`speak_safely`).
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from shraddha.logging_setup import get_logger

log = get_logger("tts")

#: Engine identifiers used in ``config.json`` and in the UI.
ONE_CORE = "onecore"
PIPER = "piper"
NONE = "none"

_TOKEN_PATTERN = re.compile(r"_(?P<lang>[a-z]{2})(?P<region>[A-Z]{2})_")

# Registry locations that hold installed voice tokens. Order matters: OneCore entries
# are what modern Windows apps (and SAPI through the OneCore bridge) actually expose.
_REGISTRY_PATHS: tuple[tuple[int, str], ...] = (
    (0x80000002, r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens"),  # HKLM
    (0x80000001, r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens"),  # HKCU
    (0x80000002, r"SOFTWARE\Microsoft\Speech\Voices\Tokens"),  # HKLM (legacy SAPI5)
    (0x80000001, r"SOFTWARE\Microsoft\Speech\Voices\Tokens"),  # HKCU (legacy SAPI5)
)


@dataclass(frozen=True, slots=True)
class Voice:
    """An installed speech voice."""

    token: str
    name: str
    language: str
    engine: str

    @property
    def is_hindi(self) -> bool:
        return self.language.lower().startswith("hi")

    def __str__(self) -> str:
        return f"{self.name} [{self.language}] ({self.engine})"


class TtsUnavailable(RuntimeError):
    """Raised when no usable speech engine exists on this machine."""


@runtime_checkable
class TtsEngine(Protocol):
    """Contract every speech engine implements; Phase 2 provides the first two."""

    name: str

    def speak(self, text: str) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


def is_windows() -> bool:
    return sys.platform == "win32"


# --------------------------------------------------------------------------- voices
def list_windows_voices() -> tuple[Voice, ...]:
    """Enumerate installed Windows voices without pywin32 or COM.

    Returns an empty tuple on non-Windows platforms and whenever the registry cannot
    be read - callers treat that as "no voices", never as a fatal error.
    """
    if not is_windows():
        return ()

    import winreg  # Windows-only stdlib module; imported lazily on purpose.

    seen: dict[str, Voice] = {}
    for hive, subkey in _REGISTRY_PATHS:
        engine = ONE_CORE if "OneCore" in subkey else "sapi"
        try:
            with winreg.OpenKey(hive, subkey) as root:
                index = 0
                while True:
                    try:
                        token_name = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    voice = _read_token(winreg, hive, f"{subkey}\\{token_name}", token_name, engine)
                    if voice is not None and voice.token not in seen:
                        seen[voice.token] = voice
        except OSError:
            continue
    return tuple(seen.values())


def _read_token(winreg, hive: int, path: str, token_name: str, engine: str) -> Voice | None:
    try:
        with winreg.OpenKey(hive, path) as key:
            display, _ = winreg.QueryValueEx(key, "")
            name = str(display).strip() or token_name
    except OSError:
        return None

    language = ""
    try:
        with winreg.OpenKey(hive, f"{path}\\Attributes") as attributes:
            language, _ = winreg.QueryValueEx(attributes, "Language")
            language = str(language).strip()
    except OSError:
        match = _TOKEN_PATTERN.search(token_name)
        if match:
            language = f"{match.group('lang')}-{match.group('region')}"

    return Voice(token=token_name, name=name, language=language or "unknown", engine=engine)


def hindi_voices(voices: tuple[Voice, ...] | None = None) -> tuple[Voice, ...]:
    """Filter to Hindi voices, preferring OneCore entries over legacy SAPI duplicates."""
    pool = list_windows_voices() if voices is None else list(voices)
    hindi = [v for v in pool if v.is_hindi]
    hindi.sort(key=lambda v: (v.engine != ONE_CORE, v.name))
    return tuple(hindi)


# -------------------------------------------------------------------------- piper
def piper_model_path(configured: str | None, models_dir: Path) -> Path | None:
    """Resolve the Piper ``.onnx`` model, or ``None`` when it is not installed."""
    if configured:
        candidate = Path(configured).expanduser()
        return candidate if candidate.is_file() else None
    search = sorted(models_dir.glob("**/hi_IN-*.onnx"))
    return search[0] if search else None


def available_engines(models_dir: Path, configured_piper: str | None = None) -> dict[str, bool]:
    """Report which speech engines could run right now."""
    return {
        ONE_CORE: bool(hindi_voices()),
        PIPER: piper_model_path(configured_piper, models_dir) is not None,
    }


# ------------------------------------------------------------------------- policy
def select_engine(configured: str, engines: dict[str, bool]) -> str:
    """Pick the engine to use, honouring an explicit choice when it is usable.

    ``auto`` prefers the zero-cost Windows voice, and falls back to Piper. An explicit
    choice that cannot run returns :data:`NONE` so the caller can degrade to text
    instead of failing at the first sentence.
    """
    if configured == NONE:
        return NONE
    if configured in (ONE_CORE, PIPER):
        return configured if engines.get(configured) else NONE
    if engines.get(ONE_CORE):
        return ONE_CORE
    if engines.get(PIPER):
        return PIPER
    return NONE


def describe_engine(engine: str) -> str:
    """Short human-facing explanation shown in the settings UI and doctor report."""
    return {
        ONE_CORE: "Windows built-in voice (free, instant, commercially usable)",
        PIPER: "Piper neural voice (~63 MB, most natural, non-commercial licence)",
        NONE: "no speech engine available",
    }.get(engine, engine)


# =============================================================================
# Phase 2: synthesis
# =============================================================================
#
# Detection lives above; this section actually makes sound. Both engines are optional
# and both are guarded: a missing COM component, a missing model or a missing player
# degrades to a spoken-nothing-but-logged warning, never to a crash mid-sentence.
#
# Everything that can be tested without audio hardware is factored out:
#   * `voice_options()` and `next_voice()` - pure list/recycling logic;
#   * `PipelineTts` - a recorder used by tests;
#   * the engine classes only contain the thin OS call itself.


class NullTts:
    """No-op engine: the assistant answers in text only."""

    name = NONE

    @property
    def is_available(self) -> bool:
        return False

    def speak(self, text: str) -> bool:
        log.info("speech disabled, reply stays textual: %.40s", text)
        return False

    def stop(self) -> None:
        return None

    def close(self) -> None:
        return None


class WindowsSapiTts:
    """Windows voices through SAPI5 (pywin32 COM).

    Covers any voice Windows exposes to SAPI, including Hindi voices once the Hindi
    speech feature is installed. Async so the UI never blocks on a sentence.
    """

    name = ONE_CORE
    SVF_ASYNC = 1
    SVF_PURGE = 2

    def __init__(self, voice: str | None = None, rate: int = 0, volume: int = 100) -> None:
        self._voice = voice
        self._rate = max(-10, min(10, rate))
        self._volume = max(0, min(100, volume))
        self._speaker = None

    @property
    def is_available(self) -> bool:
        if not is_windows():
            return False
        try:
            import win32com.client  # noqa: F401 - optional dependency
        except ImportError:
            return False
        return True

    def _ensure(self) -> bool:
        if self._speaker is not None:
            return True
        if not self.is_available:
            return False
        import win32com.client

        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Rate = self._rate
            speaker.Volume = self._volume
            if self._voice:
                for token in speaker.GetVoices():
                    if self._voice.lower() in str(token.GetDescription()).lower():
                        speaker.Voice = token
                        break
            self._speaker = speaker
            return True
        except Exception as exc:  # COM can fail for a dozen reasons
            log.warning("SAPI could not start: %s", exc)
            return False

    def speak(self, text: str) -> bool:
        if not text.strip() or not self._ensure():
            return False
        try:
            self._speaker.Speak(text, self.SVF_ASYNC | self.SVF_PURGE)
            return True
        except Exception as exc:
            log.warning("SAPI speak failed: %s", exc)
            return False

    def stop(self) -> None:
        if self._speaker is None:
            return
        with contextlib.suppress(Exception):
            self._speaker.Speak("", self.SVF_PURGE | self.SVF_ASYNC)

    def close(self) -> None:
        self.stop()
        self._speaker = None


class PiperTts:
    """Neural Hindi voice via Piper (VITS on ONNX Runtime).

    The model is a ~63 MB ``.onnx`` file; synthesis writes a temporary WAV that is then
    played with ``winsound`` (Windows, zero dependencies) or ``sounddevice``.
    """

    name = PIPER

    def __init__(self, model_path: Path, player=None) -> None:
        self._model_path = Path(model_path)
        self._voice = None
        self._player = player
        self._temp_files: list[Path] = []

    @property
    def is_available(self) -> bool:
        if not self._model_path.is_file():
            return False
        try:
            import piper  # noqa: F401 - optional dependency
        except ImportError:
            return False
        return True

    def _ensure(self) -> bool:
        if self._voice is not None:
            return True
        try:
            from piper import PiperVoice
        except ImportError:
            return False
        try:
            self._voice = PiperVoice.load(str(self._model_path))
            return True
        except Exception as exc:
            log.warning("piper model could not load: %s", exc)
            return False

    def speak(self, text: str) -> bool:
        if not text.strip() or not self._ensure():
            return False
        try:
            handle, name = tempfile.mkstemp(suffix=".wav", prefix="shraddha-")
            os.close(handle)
            path = Path(name)
            self._temp_files.append(path)
            with path.open("wb") as sink:
                self._voice.synthesize(text, sink)
            self._play(path)
            return True
        except Exception as exc:  # synthesis or playback
            log.warning("piper speak failed: %s", exc)
            return False

    def _play(self, path: Path) -> None:
        if self._player is not None:
            self._player(str(path))
            return
        if sys.platform == "win32":
            import winsound

            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            return
        opener = "afplay" if sys.platform == "darwin" else "aplay"
        subprocess.Popen([opener, str(path)], shell=False, close_fds=True)

    def stop(self) -> None:
        if sys.platform == "win32":
            with contextlib.suppress(Exception):
                import winsound

                winsound.PlaySound(None, winsound.SND_PURGE)

    def close(self) -> None:
        self.stop()
        self._voice = None
        for path in self._temp_files:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
        self._temp_files.clear()


class RecordingTts:
    """Deterministic engine for tests: records what would have been spoken."""

    name = "recording"
    is_available = True

    def __init__(self, succeed: bool = True) -> None:
        self.spoken: list[str] = []
        self.succeed = succeed
        self.stopped = 0

    def speak(self, text: str) -> bool:
        if self.succeed:
            self.spoken.append(text)
        return self.succeed

    def stop(self) -> None:
        self.stopped += 1

    def close(self) -> None:
        return None


def voice_options(configured_piper: str | None, models_dir: Path) -> list[str]:
    """Every voice the user could pick, best-first: Windows voices, then Piper models."""
    options = [voice.name for voice in hindi_voices()]
    model = piper_model_path(configured_piper, models_dir)
    if model is not None:
        options.append(model.stem)
    return options


def next_voice(current: str | None, options: list[str]) -> str | None:
    """Cycle through available voices, wrapping around; ``None`` when empty."""
    if not options:
        return None
    if current is None or current not in options:
        return options[0]
    index = (options.index(current) + 1) % len(options)
    return options[index]


def create_engine(
    engine: str,
    voice: str | None = None,
    rate: int = 0,
    volume: int = 100,
    configured_piper: str | None = None,
    models_dir: Path | None = None,
) -> object:
    """Build the best engine that can actually run on this machine."""
    root = Path(models_dir) if models_dir else Path.cwd()
    engines = available_engines(root, configured_piper)
    chosen = select_engine(engine, engines)

    if chosen == ONE_CORE:
        sapi = WindowsSapiTts(voice=voice, rate=rate, volume=volume)
        if sapi.is_available:
            return sapi
    if chosen == PIPER:
        model = piper_model_path(configured_piper, root)
        if model is not None:
            piper = PiperTts(model)
            if piper.is_available:
                return piper
    return NullTts()


def speak_safely(engine: object, text: str) -> bool:
    """Speak without ever letting a TTS failure reach the UI loop."""
    if not text.strip():
        return False
    method = getattr(engine, "speak", None)
    if method is None:
        return False
    try:
        return bool(method(text))
    except Exception as exc:  # a driver can die between sentences
        log.warning("speech engine raised: %s", exc)
        return False
