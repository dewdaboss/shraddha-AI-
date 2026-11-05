"""Shared pytest fixtures.

Every test runs against a throwaway ``SHRADDHA_HOME``. Qt tests additionally get a
single, session-wide ``QApplication`` - creating more than one crashes Qt.
"""

from __future__ import annotations

import os
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


def _select_headless_qt_platform() -> None:
    """Pick a Qt platform plugin that works without a display.

    Must run *before* Qt is imported. Windows and macOS are left alone - they always
    have a real platform, and their behaviour is what we actually ship.
    """
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "minimal")


@pytest.fixture(scope="session")
def qapp():
    """A single QApplication for the whole session, or skip if Qt is unusable."""
    _select_headless_qt_platform()
    widgets = pytest.importorskip(
        "PySide6.QtWidgets",
        reason="PySide6 (the 'ui' extra) is not installed or cannot load its Qt libraries",
        exc_type=ImportError,
    )
    app = widgets.QApplication.instance() or widgets.QApplication([])
    yield app
