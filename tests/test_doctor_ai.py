"""Phase 3 - what the doctor reports about cloud AI (never a secret, never a request)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shraddha.config import AppConfig
from shraddha.doctor import run_doctor


@pytest.fixture(autouse=True)
def _no_credentials_and_no_sdk_probe(monkeypatch: pytest.MonkeyPatch):
    """Keep the report deterministic: no real key, no assumed SDK install."""
    import shraddha.ai.keys as keys
    import shraddha.ai.service as service_module

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(keys, "read_credential", lambda: None)
    monkeypatch.setattr(service_module, "module_available", lambda _name: True)
    yield


def test_a_fresh_install_reports_cloud_ai_off(app_home: Path) -> None:
    report = run_doctor()

    assert report.ai["provider"] == "none"
    assert report.ai["status"] == "off"
    assert report.ai["key_present"] is False
    assert report.ai["consent"] is False
    assert "cloud ai (optional)" in report.to_text()


def test_the_json_report_contains_the_ai_block(app_home: Path) -> None:
    payload = json.loads(json.dumps(run_doctor().as_dict(), ensure_ascii=False))
    assert "ai" in payload
    assert payload["ai"]["model"] == "gemini-flash-latest"


def test_a_configured_key_is_reported_masked(app_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaABCDEFGHIJKLMNOPQRSTUVWXYZ1234")
    config = AppConfig()
    config.llm.provider = "gemini"
    config.llm.enabled = True
    config.llm.allow_cloud = True

    report = run_doctor(config=config)
    text = report.to_text()

    assert report.ai["key_present"] is True
    assert report.ai["status"] == "ready"
    assert "1234" in text
    assert "AIzaABCDEFGHIJKLMNOPQRSTUVWXYZ1234" not in text


def test_a_key_without_consent_is_reported_as_such(app_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaABCDEFGHIJKLMNOPQRSTUVWXYZ1234")
    config = AppConfig()
    config.llm.provider = "gemini"
    config.llm.enabled = True
    config.llm.allow_cloud = False

    report = run_doctor(config=config)

    assert report.ai["status"] == "consent_required"
    assert any("consent was not granted" in warning for warning in report.warnings)


def test_missing_key_is_a_warning_once_ai_is_on(app_home: Path) -> None:
    config = AppConfig()
    config.llm.provider = "gemini"
    config.llm.enabled = True
    config.llm.allow_cloud = True

    report = run_doctor(config=config)

    assert report.ai["status"] == "no_key"
    assert any("no API key was found" in warning for warning in report.warnings)


def test_disabled_ai_produces_no_warnings(app_home: Path) -> None:
    report = run_doctor()
    assert not any("cloud AI is enabled" in warning for warning in report.warnings)


def test_the_doctor_never_calls_the_network(app_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A doctor run must stay instant and offline even with a key configured."""
    import socket

    def explode(*_args, **_kwargs):
        raise AssertionError("the doctor must not open a socket")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaABCDEFGHIJKLMNOPQRSTUVWXYZ1234")
    config = AppConfig()
    config.llm.provider = "gemini"
    config.llm.enabled = True
    config.llm.allow_cloud = True

    report = run_doctor(config=config)

    assert report.ai["status"] == "ready"
