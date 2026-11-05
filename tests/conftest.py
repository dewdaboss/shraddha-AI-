"""Shared pytest fixtures. Every test runs against a throwaway SHRADDHA_HOME."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture()
def app_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect all application paths into a temporary directory."""
    home = tmp_path / "shraddha-home"
    monkeypatch.setenv("SHRADDHA_HOME", str(home))
    monkeypatch.delenv("SHRADDHA_MODELS", raising=False)
    yield home
    for leftover in home.rglob("*"):
        if leftover.is_file():
            leftover.chmod(0o600)
