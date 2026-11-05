"""Hindi text-to-speech engines.

Two engines, both free, both fully offline:

* ``onecore`` - the voices that ship with Windows (Hindi: Hemant / Kalpana). Zero
  download, zero extra RAM, licensed with the OS, commercially safe.
* ``piper``   - neural VITS voices (``hi_IN-pratham``, ``hi_IN-priyamvada``, ``hi_IN-rohan``),
  roughly 63 MB each, far more natural. **Non-commercial licence** - see
  THIRD-PARTY-NOTICES.md before using in a paid product.

This module only *detects* what is available in Phase 0; actual synthesis lands in
Phase 3. Detection is deliberately dependency-free: Windows voices are read straight
from the registry with :mod:`winreg`, so ``--doctor`` works without pywin32 or COM.
"""

from __future__ import annotations

import re
import sys
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
    """Contract every speech engine implements (Phase 3 fills in synthesis)."""

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
