"""Tests for the doctor report: it must never raise, and must always advise."""

from __future__ import annotations

import sys
from pathlib import Path

from shraddha.config import AppConfig
from shraddha.doctor import OPTIONAL_EXTRAS, DoctorReport, run_doctor
from shraddha.paths import get_paths


def test_doctor_runs_clean_in_a_temp_home(app_home: Path) -> None:
    report = run_doctor()
    assert report.python.startswith("3.")
    assert report.cpu_count >= 1
    assert report.writable is True
    assert report.config_ok is True


def test_doctor_populates_every_section(app_home: Path) -> None:
    report = run_doctor()
    payload = report.as_dict()
    assert set(payload["extras"]) == set(OPTIONAL_EXTRAS)
    assert set(payload["models"]) == {
        "vosk small-hi (~42 MB)",
        "indicconformer hi int8 (~130 MB)",
        "piper hi_IN voice (~64 MB)",
        "local LLM (.gguf)",
    }
    assert payload["selected_engine"] in {"onecore", "piper", "none"}


def test_doctor_text_report_is_readable(app_home: Path) -> None:
    text = run_doctor().to_text()
    assert "SHRADDHA AI - environment report" in text
    assert "hindi voice output" in text
    assert "ram" in text


def test_doctor_warns_when_components_are_missing(app_home: Path) -> None:
    warnings = " ".join(run_doctor().warnings)
    assert "microphone" in warnings
    assert "speech model" in warnings


def test_doctor_reports_the_voice_stack(app_home: Path) -> None:
    report = run_doctor()
    assert set(report.asr_engines) == {"vosk", "sherpa"}
    for info in report.asr_engines.values():
        assert info["ready"] is False, "no model is installed in the test environment"
        assert info["message"]
    assert report.wake_mode == "push_to_talk"
    assert "available" in report.microphone


def test_doctor_advises_llm_ram(app_home: Path) -> None:
    config = AppConfig()
    config.llm.enabled = True
    config.llm.provider = "local"  # the RAM warning is about the local llama.cpp model
    report = run_doctor(config=config)
    if report.ram_total_gb is not None and report.ram_total_gb < 8:
        assert any("local LLM" in warning for warning in report.warnings)


def test_doctor_survives_a_broken_config(app_home: Path) -> None:
    paths = get_paths()
    paths.ensure()
    paths.config_file.write_text("{broken", encoding="utf-8")

    report = run_doctor(paths)
    assert report.config_ok is False
    assert any("configuration problem" in warning for warning in report.warnings)
    assert report.selected_engine in {"onecore", "piper", "none"}


def test_doctor_creates_no_files_when_not_initialised(app_home: Path) -> None:
    run_doctor()
    assert not get_paths().config_file.exists(), "the doctor must not mutate configuration"


def test_report_is_serialisable(app_home: Path) -> None:
    import json

    payload = DoctorReport().as_dict()
    assert json.loads(json.dumps(payload))["version"]


def test_off_windows_reports_platform_warning(app_home: Path) -> None:
    report = run_doctor()
    if sys.platform != "win32":
        assert any("not running on Windows" in warning for warning in report.warnings)
