"""Phase 3 - the CLI switches that make cloud AI opt-in and debuggable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shraddha.ai.base import AiError
from shraddha.cli import AI_CHECK_PROMPT, EXIT_ERROR, EXIT_OK, build_parser, main
from shraddha.config import AppConfig
from shraddha.paths import get_paths


def config_file() -> Path:
    return get_paths().config_file


# ------------------------------------------------------------------- the flags
def test_the_parser_exposes_every_ai_switch() -> None:
    parser = build_parser()
    args = parser.parse_args(["--ai-status", "--ai-consent", "--ai-off", "--set-api-key", "--ai-check"])
    assert args.ai_status is True
    assert args.ai_consent is True
    assert args.ai_off is True
    assert args.set_api_key is True
    assert args.ai_check == AI_CHECK_PROMPT


def test_ai_check_takes_an_optional_prompt() -> None:
    args = build_parser().parse_args(["--ai-check", "नमस्ते"])
    assert args.ai_check == "नमस्ते"


def test_no_flags_still_prints_help(app_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == EXIT_OK
    assert "usage" in capsys.readouterr().out.lower()


# ------------------------------------------------------------------ ai-status
def test_status_of_a_fresh_install_says_off(app_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--ai-status"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "provider   none" in out
    assert "status     off" in out
    assert "MISSING" in out


def test_status_json_is_machine_readable(app_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--ai-status", "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["provider"] == "none"
    assert payload["status"] == "off"
    assert payload["present"] is False
    assert "masked" in payload


def test_status_reflects_a_configured_key(
    app_home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaABCDEFGHIJKLMNOPQRSTUVWXYZ1234")
    assert main(["--ai-status", "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["present"] is True
    assert payload["source"] == "env:GEMINI_API_KEY"
    assert payload["masked"].endswith("1234")
    assert "AIzaAB" not in payload["masked"]


# ------------------------------------------------------------------- consent
def test_consent_then_off_round_trip(app_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--ai-consent"]) == EXIT_OK
    first = capsys.readouterr().out
    assert "ON" in first

    saved = AppConfig.load(config_file())
    assert saved.llm.enabled is True
    assert saved.llm.allow_cloud is True
    assert saved.llm.provider == "gemini"

    assert main(["--ai-off"]) == EXIT_OK
    assert "OFF" in capsys.readouterr().out
    saved = AppConfig.load(config_file())
    assert saved.llm.enabled is False
    assert saved.llm.allow_cloud is False


def test_consent_keeps_an_existing_provider(app_home: Path) -> None:
    config = AppConfig()
    config.llm.provider = "gemini"
    config.llm.model = "custom-model"
    config.save(config_file())

    main(["--ai-consent"])

    assert AppConfig.load(config_file()).llm.model == "custom-model"


# ---------------------------------------------------------------- set-api-key
def test_set_api_key_explains_the_environment_variable_on_unsupported_systems(
    app_home: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shraddha.ai.keys as keys

    monkeypatch.setattr(keys, "credential_support", lambda: (False, "not on this platform"))

    assert main(["--set-api-key"]) == EXIT_ERROR
    err = capsys.readouterr().err
    assert "GEMINI_API_KEY" in err


def test_set_api_key_stores_and_masks(
    app_home: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shraddha.ai.keys as keys
    import shraddha.cli as cli

    stored: list[str] = []
    monkeypatch.setattr(keys, "credential_support", lambda: (True, ""))
    monkeypatch.setattr(keys, "write_credential", stored.append)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt="": "AIzaSUPERSECRETVALUE9999")

    assert main(["--set-api-key"]) == EXIT_OK
    out = capsys.readouterr().out
    assert stored == ["AIzaSUPERSECRETVALUE9999"]
    assert "…9999" in out
    assert "AIzaSUPERSECRETVALUE9999" not in out


def test_set_api_key_rejects_an_empty_secret(
    app_home: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shraddha.ai.keys as keys
    import shraddha.cli as cli

    monkeypatch.setattr(keys, "credential_support", lambda: (True, ""))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt="": "   ")

    assert main(["--set-api-key"]) == EXIT_ERROR
    assert "nothing changed" in capsys.readouterr().err


def test_set_api_key_handles_ctrl_c(
    app_home: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shraddha.ai.keys as keys
    import shraddha.cli as cli

    def interrupt(_prompt: str = "") -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(keys, "credential_support", lambda: (True, ""))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(cli.getpass, "getpass", interrupt)

    assert main(["--set-api-key"]) == EXIT_ERROR
    assert "cancelled" in capsys.readouterr().err


# ------------------------------------------------------------------- ai-check
class FakeService:
    def __init__(self, answer: str = "मैं श्रद्धा हूँ।", error: Exception | None = None) -> None:
        self.answer = answer
        self.error = error
        self.closed = False
        self.asked: list[str] = []
        self._provider = type("P", (), {"active_model": "gemini-2.5-flash"})()

    def ask_text(self, text: str) -> str:
        self.asked.append(text)
        if self.error is not None:
            raise self.error
        return self.answer

    def close(self) -> None:
        self.closed = True


def patch_service(monkeypatch: pytest.MonkeyPatch, service: FakeService) -> None:
    import shraddha.ai as ai_package

    monkeypatch.setattr(ai_package, "make_service", lambda _llm, **_kw: service)


def test_ai_check_prints_the_answer(
    app_home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    service = FakeService("नमस्ते, मैं श्रद्धा हूँ।")
    patch_service(monkeypatch, service)

    assert main(["--ai-check", "कौन हो?"]) == EXIT_OK

    out = capsys.readouterr().out
    assert "नमस्ते, मैं श्रद्धा हूँ।" in out
    assert service.asked == ["कौन हो?"]
    assert service.closed is True


def test_ai_check_mentions_the_fallback_model(
    app_home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_service(monkeypatch, FakeService())
    assert main(["--ai-check"]) == EXIT_OK
    assert "fallback model gemini-2.5-flash" in capsys.readouterr().out


def test_ai_check_reports_an_error_and_the_hint(
    app_home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    error = AiError("इंटरनेट नहीं है।", code="network", hint="कनेक्शन जाँचिए")
    patch_service(monkeypatch, FakeService(error=error))

    assert main(["--ai-check"]) == EXIT_ERROR

    err = capsys.readouterr().err
    assert "failed [network]" in err
    assert "कनेक्शन" in err


def test_ai_check_points_at_ai_status_for_configuration_problems(
    app_home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_service(monkeypatch, FakeService(error=AiError("कोई कुंजी नहीं", code="no_key")))

    assert main(["--ai-check"]) == EXIT_ERROR

    assert "--ai-status" in capsys.readouterr().err
