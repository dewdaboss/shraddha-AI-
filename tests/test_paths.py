"""Tests for path resolution and the directory layout."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from shraddha.paths import ENV_HOME, ENV_MODELS, Paths, get_paths


def test_env_override_redirects_everything(app_home: Path) -> None:
    paths = get_paths()
    assert paths.home == app_home
    assert paths.models == app_home / "models"
    assert paths.logs == app_home / "logs"
    assert paths.config_file == app_home / "config.json"
    assert paths.db_file == app_home / "shraddha.db"


def test_models_can_live_elsewhere(app_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    external = app_home / "big-disk" / "models"
    monkeypatch.setenv(ENV_MODELS, str(external))
    assert get_paths().models == external


def test_ensure_creates_directories_idempotently(app_home: Path) -> None:
    paths = get_paths()
    paths.ensure().ensure()
    for directory in (paths.home, paths.models, paths.logs, paths.cache):
        assert directory.is_dir()


def test_as_dict_exposes_user_facing_locations(app_home: Path) -> None:
    payload = get_paths().as_dict()
    assert set(payload) == {"home", "models", "cache", "logs", "config", "database"}
    assert all(isinstance(value, str) for value in payload.values())


def test_default_home_without_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_HOME, raising=False)
    monkeypatch.delenv(ENV_MODELS, raising=False)
    home = get_paths().home
    if sys.platform == "win32":
        assert home.name == "Shraddha"
    else:
        assert home.name in {"shraddha", "Shraddha"}


def test_paths_is_immutable(app_home: Path) -> None:
    paths = Paths(home=app_home, models=app_home / "m", cache=app_home / "c", logs=app_home / "l")
    with pytest.raises(AttributeError):
        paths.home = app_home.parent  # type: ignore[misc]
