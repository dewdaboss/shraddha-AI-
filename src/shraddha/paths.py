"""Single source of truth for where SHRADDHA AI keeps its files.

Layout (Windows)::

    %LOCALAPPDATA%\\Shraddha\\
        config.json
        shraddha.db
        logs\\shraddha.log
        models\\...
        cache\\

On Linux/macOS (development and CI only) ``$XDG_DATA_HOME/shraddha`` is used instead.
Every path can be redirected with the ``SHRADDHA_HOME`` environment variable, which is
what the test-suite does so it never touches a real user profile.
"""

from __future__ import annotations

import contextlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ENV_HOME = "SHRADDHA_HOME"
ENV_MODELS = "SHRADDHA_MODELS"

_FALLBACK_FOLDER = "Shraddha"
_POSIX_FOLDER = "shraddha"


def home_dir() -> Path:
    """Return the application's data directory (not created here)."""
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / _FALLBACK_FOLDER
        return Path.home() / "AppData" / "Local" / _FALLBACK_FOLDER

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / _POSIX_FOLDER
    return Path.home() / ".local" / "share" / _POSIX_FOLDER


def models_dir() -> Path:
    """Where speech/LLM weights live. Never inside the repository."""
    override = os.environ.get(ENV_MODELS)
    if override:
        return Path(override).expanduser()
    return home_dir() / "models"


@dataclass(frozen=True, slots=True)
class Paths:
    """Resolved filesystem layout for one process."""

    home: Path
    models: Path
    cache: Path
    logs: Path

    @property
    def config_file(self) -> Path:
        return self.home / "config.json"

    @property
    def db_file(self) -> Path:
        return self.home / "shraddha.db"

    @property
    def log_file(self) -> Path:
        return self.logs / "shraddha.log"

    @property
    def lock_file(self) -> Path:
        """Used to guarantee a single running instance."""
        return self.home / ".instance.lock"

    def ensure(self) -> Paths:
        """Create every directory, tolerating concurrent creation."""
        for directory in (self.home, self.models, self.cache, self.logs):
            with contextlib.suppress(FileExistsError):
                directory.mkdir(parents=True, exist_ok=True)
        return self

    def as_dict(self) -> dict[str, str]:
        return {
            "home": str(self.home),
            "models": str(self.models),
            "cache": str(self.cache),
            "logs": str(self.logs),
            "config": str(self.config_file),
            "database": str(self.db_file),
        }


def get_paths() -> Paths:
    """Resolve the current layout. Cheap enough to call repeatedly."""
    home = home_dir()
    return Paths(
        home=home,
        models=models_dir(),
        cache=home / "cache",
        logs=home / "logs",
    )


def is_windows() -> bool:
    return sys.platform == "win32"
