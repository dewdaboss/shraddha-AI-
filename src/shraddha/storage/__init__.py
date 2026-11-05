"""Local persistence: one SQLite file, no server, no ORM."""

from __future__ import annotations

from shraddha.storage.db import Database, initialize

__all__ = ["Database", "initialize"]
