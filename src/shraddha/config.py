"""Typed application configuration with forgiving loading and atomic saving.

Design choices:

* **Plain dataclasses, no pydantic.** The core must stay dependency-free and import
  in a few milliseconds at startup.
* **Forward compatible.** Unknown keys in an existing ``config.json`` are ignored
  instead of crashing, so an older build can read a newer file.
* **Never silently wrong.** Values out of range raise :class:`ConfigError` with the
  offending key, rather than being clamped behind the user's back.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

CONFIG_SCHEMA_VERSION = 1

SAMPLE_RATES = (8_000, 16_000, 22_050, 44_100, 48_000)
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
ASR_ENGINES = ("auto", "sherpa", "vosk", "none")
TTS_ENGINES = ("auto", "onecore", "piper", "none")
THEMES = ("system", "dark", "light")


class ConfigError(ValueError):
    """Raised when a configuration value is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


def _check_choice(value: Any, choices: tuple[str, ...], key: str) -> str:
    _require(isinstance(value, str), f"{key} must be a string, got {type(value).__name__}")
    _require(value in choices, f"{key} must be one of {choices}, got {value!r}")
    return value


def _check_int(value: Any, key: str, low: int, high: int) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool), f"{key} must be an integer")
    _require(low <= value <= high, f"{key} must be between {low} and {high}, got {value}")
    return value


@dataclass(slots=True)
class AudioConfig:
    """Microphone capture. 16 kHz mono is what every speech model here expects."""

    sample_rate: int = 16_000
    channels: int = 1
    frame_ms: int = 20
    vad_threshold: float = 0.5
    device: str | None = None

    def validate(self) -> None:
        _require(
            self.sample_rate in SAMPLE_RATES, f"audio.sample_rate must be one of {SAMPLE_RATES}"
        )
        _check_int(self.channels, "audio.channels", 1, 2)
        _check_int(self.frame_ms, "audio.frame_ms", 10, 100)
        _require(0.0 <= self.vad_threshold <= 1.0, "audio.vad_threshold must be within 0..1")

    @property
    def frame_samples(self) -> int:
        """Samples per processing frame (e.g. 320 for 20 ms at 16 kHz)."""
        return self.sample_rate * self.frame_ms // 1000


@dataclass(slots=True)
class AsrConfig:
    """Speech recognition (Hindi by default)."""

    engine: str = "auto"
    model_dir: str | None = None
    language: str = "hi"
    num_threads: int = 2

    def validate(self) -> None:
        _check_choice(self.engine, ASR_ENGINES, "asr.engine")
        _check_int(self.num_threads, "asr.num_threads", 1, 16)
        _require(bool(self.language), "asr.language must not be empty")


@dataclass(slots=True)
class TtsConfig:
    """Speech synthesis. ``auto`` prefers Windows voices, then Piper."""

    engine: str = "auto"
    voice: str | None = None
    rate: int = 0
    volume: int = 100
    piper_model: str | None = None

    def validate(self) -> None:
        _check_choice(self.engine, TTS_ENGINES, "tts.engine")
        _check_int(self.rate, "tts.rate", -10, 10)
        _check_int(self.volume, "tts.volume", 0, 100)


@dataclass(slots=True)
class UiConfig:
    """Tray / overlay behaviour. Hotkey only by default: costs no CPU."""

    hotkey: str = "ctrl+alt+s"
    language: str = "hi"
    theme: str = "system"
    overlay: bool = True
    start_minimised: bool = True

    def validate(self) -> None:
        _check_choice(self.theme, THEMES, "ui.theme")
        _require(bool(self.hotkey.strip()), "ui.hotkey must not be empty")
        _require(bool(self.language), "ui.language must not be empty")


@dataclass(slots=True)
class LlmConfig:
    """Optional local LLM (Phase 6). Disabled by default: it is the RAM hog."""

    enabled: bool = False
    model_path: str | None = None
    context_size: int = 2_048
    num_threads: int = 2
    idle_unload_s: int = 60

    def validate(self) -> None:
        _check_int(self.context_size, "llm.context_size", 512, 32_768)
        _check_int(self.num_threads, "llm.num_threads", 1, 16)
        _check_int(self.idle_unload_s, "llm.idle_unload_s", 0, 3_600)


_SECTIONS: dict[str, type] = {
    "audio": AudioConfig,
    "asr": AsrConfig,
    "tts": TtsConfig,
    "ui": UiConfig,
    "llm": LlmConfig,
}


@dataclass(slots=True)
class AppConfig:
    """Root configuration object."""

    schema_version: int = CONFIG_SCHEMA_VERSION
    log_level: str = "INFO"
    audio: AudioConfig = field(default_factory=AudioConfig)
    asr: AsrConfig = field(default_factory=AsrConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)

    # ---------------------------------------------------------------- validation
    def validate(self) -> AppConfig:
        _check_choice(self.log_level, LOG_LEVELS, "log_level")
        for name in _SECTIONS:
            getattr(self, name).validate()
        return self

    # ------------------------------------------------------------ (de)serialise
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        """Build a config from mapping data, ignoring unknown keys."""
        _require(isinstance(data, dict), "configuration root must be a JSON object")
        config = cls()
        if "log_level" in data:
            config.log_level = data["log_level"]
        if "schema_version" in data:
            config.schema_version = data["schema_version"]

        for name, section_cls in _SECTIONS.items():
            raw = data.get(name, {})
            _require(isinstance(raw, dict), f"{name} must be a JSON object")
            known = {f.name for f in fields(section_cls)}
            section = section_cls(**{k: v for k, v in raw.items() if k in known})
            setattr(config, name, section)

        return config.validate()

    def with_overrides(self, **overrides: Any) -> AppConfig:
        """Return a copy with top-level fields replaced (dot-free convenience)."""
        data = self.to_dict()
        data.update(overrides)
        return AppConfig.from_dict(data)

    # --------------------------------------------------------------------- I/O
    @classmethod
    def load(cls, path: Path) -> AppConfig:
        """Load from disk, or return defaults when the file does not exist."""
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"cannot read {path}: {exc}") from exc
        return cls.from_dict(raw)

    def save(self, path: Path) -> None:
        """Atomically write the configuration (never leaves a half-written file)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"
        descriptor, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".tmp")
        temp_path = Path(temp_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            temp_path.replace(path)
        except BaseException:
            with contextlib.suppress(OSError):
                temp_path.unlink()
            raise
