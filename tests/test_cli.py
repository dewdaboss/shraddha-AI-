"""Tests for the CLI surface: argument parsing, --init, --doctor, --json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shraddha.cli import EXIT_OK, build_parser, main
from shraddha.paths import get_paths


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert "Shraddha AI" in capsys.readouterr().out


def test_no_arguments_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == EXIT_OK
    assert "usage: shraddha" in capsys.readouterr().out


def test_parser_accepts_documented_flags() -> None:
    args = build_parser().parse_args(["--doctor", "--json"])
    assert args.doctor is True
    assert args.json is True


def test_init_creates_config_and_database(
    app_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--init"]) == EXIT_OK
    paths = get_paths()
    assert paths.config_file.is_file()
    assert paths.db_file.is_file()
    output = capsys.readouterr().out
    assert "config created" in output
    assert "schema v1" in output


def test_init_is_safe_to_repeat(app_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--init"])
    paths = get_paths()
    original = paths.config_file.read_text(encoding="utf-8")
    capsys.readouterr()

    assert main(["--init"]) == EXIT_OK
    assert "kept as is" in capsys.readouterr().out
    assert paths.config_file.read_text(encoding="utf-8") == original


def test_doctor_json_output_is_valid(app_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--doctor", "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"]
    assert "warnings" in payload


def test_doctor_text_output(app_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--doctor"]) == EXIT_OK
    assert "environment report" in capsys.readouterr().out


def test_doctor_exits_nonzero_on_broken_config(
    app_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = get_paths()
    paths.ensure()
    paths.config_file.write_text("nonsense", encoding="utf-8")
    assert main(["--doctor"]) == 1
    capsys.readouterr()
