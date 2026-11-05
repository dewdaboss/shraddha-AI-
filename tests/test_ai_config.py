"""Phase 3 - the AI half of the configuration model (schema v3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shraddha.config import CONFIG_SCHEMA_VERSION, LLM_PROVIDERS, AppConfig, ConfigError, LlmConfig


def test_the_schema_version_tracks_phase_3() -> None:
    assert CONFIG_SCHEMA_VERSION == 3
    assert AppConfig().to_dict()["schema_version"] == 3


def test_cloud_ai_is_off_by_default() -> None:
    llm = LlmConfig()
    assert llm.provider == "none"
    assert llm.enabled is False
    assert llm.allow_cloud is False
    assert llm.cloud_configured is False
    assert "gemini" in LLM_PROVIDERS


def test_safe_defaults_for_the_request_budget() -> None:
    llm = LlmConfig()
    assert llm.model == "gemini-flash-latest"
    assert llm.fallback_model == "gemini-2.5-flash"
    assert llm.api_key_env == "GEMINI_API_KEY"
    assert (llm.timeout_s, llm.max_output_tokens, llm.history_turns) == (30, 1024, 8)
    assert llm.stream is True
    assert 0.0 <= llm.temperature <= 2.0


def test_cloud_configured_needs_provider_switch_and_consent() -> None:
    assert LlmConfig(provider="gemini", enabled=True, allow_cloud=False).cloud_configured is False
    assert LlmConfig(provider="gemini", enabled=False, allow_cloud=True).cloud_configured is False
    assert LlmConfig(provider="local", enabled=True, allow_cloud=True).cloud_configured is False
    assert LlmConfig(provider="gemini", enabled=True, allow_cloud=True).cloud_configured is True


def test_validation_rejects_an_unknown_provider() -> None:
    with pytest.raises(ConfigError):
        LlmConfig(provider="openai").validate()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout_s": 1},
        {"timeout_s": 500},
        {"max_output_tokens": 1},
        {"max_output_tokens": 100_000},
        {"history_turns": 99},
        {"temperature": -0.5},
        {"temperature": 5.0},
        {"model": ""},
    ],
)
def test_validation_rejects_out_of_range_values(kwargs: dict[str, object]) -> None:
    llm = LlmConfig(**kwargs)
    with pytest.raises(ConfigError):
        llm.validate()


def test_validation_accepts_the_boundaries() -> None:
    LlmConfig(timeout_s=5, max_output_tokens=64, history_turns=0, temperature=0.0).validate()
    LlmConfig(timeout_s=120, max_output_tokens=8192, history_turns=50, temperature=2.0).validate()


def test_llm_settings_survive_a_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    config = AppConfig()
    config.llm.provider = "gemini"
    config.llm.enabled = True
    config.llm.allow_cloud = True
    config.llm.model = "gemini-test-model"
    config.llm.history_turns = 3
    config.save(target)

    restored = AppConfig.load(target)

    assert restored.llm.provider == "gemini"
    assert restored.llm.enabled is True
    assert restored.llm.allow_cloud is True
    assert restored.llm.model == "gemini-test-model"
    assert restored.llm.history_turns == 3
    assert "AIza" not in target.read_text(encoding="utf-8")


def test_unknown_llm_keys_are_ignored(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    payload = AppConfig().to_dict()
    payload["llm"]["provider"] = "gemini"
    payload["llm"]["something_new"] = True
    target.write_text(json.dumps(payload), encoding="utf-8")

    restored = AppConfig.load(target)

    assert restored.llm.provider == "gemini"


def test_the_default_config_file_mentions_no_secrets(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    AppConfig().save(target)
    text = target.read_text(encoding="utf-8")
    assert "AIza" not in text
    assert "allow_cloud" in text
