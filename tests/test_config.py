"""Tests for the configuration model: defaults, round-trip, validation, bad input."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shraddha.config import AppConfig, ConfigError


def test_defaults_are_valid_and_hindi_first() -> None:
    config = AppConfig().validate()
    assert config.asr.language == "hi"
    assert config.ui.language == "hi"
    assert config.audio.sample_rate == 16_000
    assert config.llm.enabled is False, "the LLM must be opt-in: it is the RAM hog"
    assert config.tts.engine == "auto"


def test_frame_samples_matches_sample_rate() -> None:
    config = AppConfig()
    assert config.audio.frame_samples == 320  # 16 kHz * 20 ms


def test_round_trip_through_file(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    original = AppConfig()
    original.tts.voice = "Hemant"
    original.ui.hotkey = "ctrl+shift+space"
    original.save(target)

    restored = AppConfig.load(target)
    assert restored.to_dict() == original.to_dict()
    assert restored.tts.voice == "Hemant"
    assert restored.ui.hotkey == "ctrl+shift+space"


def test_saved_file_is_readable_utf8_json(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    AppConfig().save(target)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["asr"]["language"] == "hi"


def test_missing_file_returns_defaults(tmp_path: Path) -> None:
    config = AppConfig.load(tmp_path / "does-not-exist.json")
    assert config.log_level == "INFO"


def test_unknown_keys_are_ignored_for_forward_compatibility() -> None:
    config = AppConfig.from_dict(
        {"asr": {"language": "hi", "future_option": 5}, "brand_new_section": {"x": 1}}
    )
    assert config.asr.language == "hi"


def test_bad_json_raises_config_error(tmp_path: Path) -> None:
    target = tmp_path / "broken.json"
    target.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        AppConfig.load(target)


@pytest.mark.parametrize(
    "payload",
    [
        {"audio": {"sample_rate": 12_345}},
        {"audio": {"channels": 9}},
        {"asr": {"engine": "google-cloud"}},
        {"tts": {"volume": 500}},
        {"llm": {"num_threads": 0}},
        {"log_level": "LOUD"},
        {"ui": {"hotkey": "   "}},
    ],
)
def test_invalid_values_are_rejected(payload: dict) -> None:
    with pytest.raises(ConfigError):
        AppConfig.from_dict(payload)


def test_overrides_do_not_mutate_original() -> None:
    original = AppConfig()
    changed = original.with_overrides(log_level="DEBUG")
    assert changed.log_level == "DEBUG"
    assert original.log_level == "INFO"


def test_save_is_atomic_and_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    AppConfig().save(target)
    AppConfig().save(target)
    assert target.exists()
    assert [p.name for p in target.parent.iterdir()] == ["config.json"]
