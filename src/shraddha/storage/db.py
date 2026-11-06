"""SQLite storage: settings, conversation history, notes.

Why SQLite (and not JSON files): history grows unbounded, needs cheap ordering and
deleting, and must survive a power cut. SQLite gives all three with zero processes and
roughly 1 MB of disk. WAL mode keeps writes fast without locking reads.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shraddha.logging_setup import get_logger

log = get_logger("storage")

SCHEMA_VERSION = 1

# Each entry is (version, statements). Migrations are applied in order and the
# version is recorded in `meta`, so upgrades never re-run old statements.
MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        (
            """
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS conversation (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                role       TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
                text       TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_conversation_created ON conversation(created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS notes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                text       TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """,
        ),
    ),
)

MAX_HISTORY_ROWS = 10_000
TRIM_SLACK = 500


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with settings tuned for a desktop app."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=5.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    for pragma in (
        "PRAGMA journal_mode=WAL",  # concurrent readers, fast commits
        "PRAGMA synchronous=NORMAL",  # safe with WAL, much faster than FULL
        "PRAGMA temp_store=MEMORY",  # no temp files on disk
        "PRAGMA foreign_keys=ON",
        "PRAGMA busy_timeout=5000",
    ):
        connection.execute(pragma)
    return connection


def initialize(db_path: Path) -> int:
    """Create or upgrade the schema. Returns the resulting schema version."""
    connection = connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        current = _read_version(connection)
        for version, statements in MIGRATIONS:
            if version <= current:
                continue
            for statement in statements:
                connection.execute(statement)
            _write_version(connection, version)
            log.info("database migrated to schema v%s", version)
            current = version
        return current
    finally:
        connection.close()


def _read_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        return 0
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        return 0


def _write_version(connection: sqlite3.Connection, version: int) -> None:
    connection.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(version),),
    )


class Database:
    """Thin, explicit data-access object. No ORM, no lazy magic."""

    def __init__(self, db_path: Path) -> None:
        self.path = Path(db_path)
        self.version = initialize(self.path)

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        connection = connect(self.path)
        try:
            yield connection.cursor()
        finally:
            connection.close()

    # ------------------------------------------------------------- conversation
    def add_turn(self, role: str, text: str) -> int:
        if role not in {"user", "assistant", "system"}:
            raise ValueError(f"invalid role: {role!r}")
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO conversation(created_at, role, text) VALUES(?, ?, ?)",
                (utc_now(), role, text),
            )
            last_id = cursor.lastrowid or 0
            self._trim_conversation(cursor)
            return int(last_id)

    def recent_turns(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT id, created_at, role, text FROM conversation ORDER BY id DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def clear_conversation(self) -> None:
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM conversation")

    def _trim_conversation(self, cursor: sqlite3.Cursor) -> None:
        """Keep the history bounded so the database cannot grow without limit.

        Amortised: the expensive delete only runs after a slack of extra rows has
        accumulated, so ordinary inserts stay O(1).
        """
        total = int(cursor.execute("SELECT COUNT(*) AS n FROM conversation").fetchone()["n"])
        if total <= MAX_HISTORY_ROWS + TRIM_SLACK:
            return
        cursor.execute(
            "DELETE FROM conversation WHERE id IN "
            "(SELECT id FROM conversation ORDER BY id ASC LIMIT ?)",
            (total - MAX_HISTORY_ROWS,),
        )

    # -------------------------------------------------------------------- notes
    def add_note(self, text: str) -> int:
        with self._cursor() as cursor:
            cursor.execute("INSERT INTO notes(created_at, text) VALUES(?, ?)", (utc_now(), text))
            return int(cursor.lastrowid or 0)

    def recent_notes(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT id, created_at, text FROM notes ORDER BY id DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_notes(self) -> int:
        """Remove every note and return how many were deleted."""
        with self._cursor() as cursor:
            row = cursor.execute("SELECT COUNT(*) AS count FROM notes").fetchone()
            total = int(row["count"]) if row is not None else 0
            cursor.execute("DELETE FROM notes")
            return total

    # ----------------------------------------------------------------- settings
    def set_setting(self, key: str, value: str) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return default if row is None else str(row["value"])

    # -------------------------------------------------------------------- misc
    def stats(self) -> dict[str, int]:
        with self._cursor() as cursor:
            return {
                "conversation": int(
                    cursor.execute("SELECT COUNT(*) AS n FROM conversation").fetchone()["n"]
                ),
                "notes": int(cursor.execute("SELECT COUNT(*) AS n FROM notes").fetchone()["n"]),
                "settings": int(
                    cursor.execute("SELECT COUNT(*) AS n FROM settings").fetchone()["n"]
                ),
            }

    def vacuum(self) -> None:
        connection = connect(self.path)
        try:
            connection.execute("VACUUM")
        finally:
            connection.close()
