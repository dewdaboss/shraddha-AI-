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

CONFIG_SCHEMA_VERSION = 3

SAMPLE_RATES = (8_000, 16_000, 22_050, 44_100, 48_000)
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
ASR_ENGINES = ("auto", "sherpa", "vosk", "none")
TTS_ENGINES = ("auto", "onecore", "piper", "none")
THEMES = ("system", "dark", "light")
WAKE_MODES = ("push_to_talk", "phrase", "off")
#: ``none`` = fully local. ``gemini`` = cloud (needs key + consent). ``local`` = Phase 6.
LLM_PROVIDERS = ("none", "gemini", "local")


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
    device: str | None = None

    def validate(self) -> None:
        _require(
            self.sample_rate in SAMPLE_RATES, f"audio.sample_rate must be one of {SAMPLE_RATES}"
        )
        _check_int(self.channels, "audio.channels", 1, 2)
        _check_int(self.frame_ms, "audio.frame_ms", 10, 100)

    @property
    def frame_samples(self) -> int:
        """Samples per processing frame (e.g. 320 for 20 ms at 16 kHz)."""
        return self.sample_rate * self.frame_ms // 1000


@dataclass(slots=True)
class AsrConfig:
    """Speech recognition and microphone capture (Hindi by default).

    The VAD numbers are the difference between "usable" and "transcribes the fan":
    ``vad_threshold`` is an RMS gate, ``min_speech_ms`` rejects clicks, and
    ``silence_ms`` decides how long a pause ends an utterance.
    """

    engine: str = "auto"
    model_dir: str | None = None
    language: str = "hi"
    num_threads: int = 2
    device: str | None = None
    sample_rate: int = 16_000
    vad_threshold: float = 0.02
    min_speech_ms: int = 250
    silence_ms: int = 700
    max_utterance_ms: int = 15_000
    idle_unload_s: int = 120

    def validate(self) -> None:
        _check_choice(self.engine, ASR_ENGINES, "asr.engine")
        _check_int(self.num_threads, "asr.num_threads", 1, 16)
        _require(bool(self.language), "asr.language must not be empty")
        _require(
            self.sample_rate in SAMPLE_RATES,
            f"asr.sample_rate must be one of {SAMPLE_RATES}, got {self.sample_rate}",
        )
        _require(0.0 <= self.vad_threshold <= 1.0, "asr.vad_threshold must be within 0..1")
        _check_int(self.min_speech_ms, "asr.min_speech_ms", 50, 2_000)
        _check_int(self.silence_ms, "asr.silence_ms", 100, 5_000)
        _check_int(self.max_utterance_ms, "asr.max_utterance_ms", 1_000, 60_000)
        _check_int(self.idle_unload_s, "asr.idle_unload_s", 0, 3_600)
        _require(
            self.min_speech_ms < self.max_utterance_ms,
            "asr.min_speech_ms must be smaller than asr.max_utterance_ms",
        )


@dataclass(slots=True)
class WakeConfig:
    """Wake word ("Hey Shraddha") behaviour.

    ``push_to_talk`` loads no model until you ask; ``phrase`` keeps the small model
    warm between utterances and unloads it after ``idle_unload_s``.
    """

    mode: str = "push_to_talk"
    phrases: tuple[str, ...] = ("hey shraddha", "श्रद्धा", "shraddha", "o shraddha")
    fuzzy_distance: int = 2
    idle_unload_s: int = 60

    def validate(self) -> None:
        _check_choice(self.mode, WAKE_MODES, "wake.mode")
        _check_int(self.fuzzy_distance, "wake.fuzzy_distance", 0, 4)
        _check_int(self.idle_unload_s, "wake.idle_unload_s", 0, 3_600)
        phrases = tuple(str(p).strip() for p in self.phrases if str(p).strip())
        _require(bool(phrases), "wake.phrases must contain at least one phrase")
        self.phrases = phrases


@dataclass(slots=True)
class CommandsConfig:
    """Voice command routing and safety rails."""

    enabled: bool = True
    allow_power_actions: bool = False
    confirm_sensitive: bool = True
    announce_actions: bool = True

    def validate(self) -> None:
        for flag in ("enabled", "allow_power_actions", "confirm_sensitive", "announce_actions"):
            _require(
                isinstance(getattr(self, flag), bool), f"commands.{flag} must be true or false"
            )


@dataclass(slots=True)
class TtsConfig:
    """Speech synthesis. ``auto`` prefers Windows voices, then Piper."""

    engine: str = "auto"
    voice: str | None = None
    rate: int = 0
    volume: int = 100
    piper_model: str | None = None
    speak_replies: bool = True

    def validate(self) -> None:
        _check_choice(self.engine, TTS_ENGINES, "tts.engine")
        _check_int(self.rate, "tts.rate", -10, 10)
        _check_int(self.volume, "tts.volume", 0, 100)
        _require(isinstance(self.speak_replies, bool), "tts.speak_replies must be true or false")


@dataclass(slots=True)
class UiConfig:
    """Tray / overlay behaviour. Hotkey only by default: costs no CPU."""

    hotkey: str = "ctrl+alt+s"
    language: str = "hi"
    theme: str = "system"
    overlay: bool = True
    start_minimised: bool = False
    always_on_top: bool = True

    def validate(self) -> None:
        _check_choice(self.theme, THEMES, "ui.theme")
        _require(bool(self.hotkey.strip()), "ui.hotkey must not be empty")
        _require(bool(self.language), "ui.language must not be empty")


@dataclass(slots=True)
class LlmConfig:
    """The assistant's "thinking" layer.

    A fresh install is completely offline: ``provider = "none"``, ``enabled = False`` and
    ``allow_cloud = False``. Cloud answers require **all three** of a provider, a key and
    explicit consent (:attr:`allow_cloud`), so nothing can be uploaded by accident.

    ``model_path``/``context_size``/``num_threads``/``idle_unload_s`` belong to the local
    llama.cpp provider (Phase 6) and are kept so a config written today still loads.
    """

    provider: str = "none"
    model: str = "gemini-flash-latest"
    fallback_model: str = "gemini-2.5-flash"
    enabled: bool = False
    #: The consent flag. Only a deliberate user action sets it (chat phrase or --ai-consent).
    allow_cloud: bool = False
    api_key_env: str = "GEMINI_API_KEY"
    timeout_s: int = 30
    max_output_tokens: int = 1_024
    temperature: float = 0.6
    history_turns: int = 8
    stream: bool = True

    # local provider (Phase 6) - unchanged, still loaded from older configs
    model_path: str | None = None
    context_size: int = 2_048
    num_threads: int = 2
    idle_unload_s: int = 60

    def validate(self) -> None:
        _check_choice(self.provider, LLM_PROVIDERS, "llm.provider")
        _require(bool(str(self.model).strip()), "llm.model must not be empty")
        _require(
            self.fallback_model is None or isinstance(self.fallback_model, str),
            "llm.fallback_model must be a string or null",
        )
        _require(bool(str(self.api_key_env).strip()), "llm.api_key_env must not be empty")
        _check_int(self.timeout_s, "llm.timeout_s", 5, 120)
        _check_int(self.max_output_tokens, "llm.max_output_tokens", 64, 8_192)
        _check_int(self.history_turns, "llm.history_turns", 0, 50)
        _require(
            0.0 <= float(self.temperature) <= 2.0, "llm.temperature must be between 0 and 2"
        )
        _check_int(self.context_size, "llm.context_size", 512, 32_768)
        _check_int(self.num_threads, "llm.num_threads", 1, 16)
        _check_int(self.idle_unload_s, "llm.idle_unload_s", 0, 3_600)

    @property
    def cloud_configured(self) -> bool:
        """Provider, master switch *and* consent agree.

        The API key is checked separately (:func:`shraddha.ai.key_report`) because it is
        never part of the configuration file.
        """
        return self.provider == "gemini" and self.enabled and self.allow_cloud


_SECTIONS: dict[str, type] = {
    "audio": AudioConfig,
    "asr": AsrConfig,
    "wake": WakeConfig,
    "commands": CommandsConfig,
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
    wake: WakeConfig = field(default_factory=WakeConfig)
    commands: CommandsConfig = field(default_factory=CommandsConfig)
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
