"""Tests for the SQLite layer: migrations, history, notes, settings, trimming."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from shraddha.storage import db


def test_initialize_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "test.db"
    first = db.initialize(target)
    second = db.initialize(target)
    assert first == second == db.SCHEMA_VERSION


def test_schema_contains_expected_tables(tmp_path: Path) -> None:
    target = tmp_path / "test.db"
    db.initialize(target)
    connection = sqlite3.connect(target)
    try:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        connection.close()
    assert {"meta", "conversation", "notes", "settings"} <= names


def test_wal_mode_is_enabled(tmp_path: Path) -> None:
    connection = db.connect(tmp_path / "wal.db")
    try:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        connection.close()
    assert mode.lower() == "wal"


def test_conversation_round_trip(tmp_path: Path) -> None:
    database = db.Database(tmp_path / "test.db")
    database.add_turn("user", "क्रोम खोलो")
    database.add_turn("assistant", "ठीक है, खोल रही हूँ।")

    turns = database.recent_turns()
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[0]["text"] == "क्रोम खोलो"


def test_recent_turns_returns_oldest_first_and_respects_limit(tmp_path: Path) -> None:
    database = db.Database(tmp_path / "test.db")
    for index in range(5):
        database.add_turn("user", f"message {index}")

    turns = database.recent_turns(limit=2)
    assert [t["text"] for t in turns] == ["message 3", "message 4"]


def test_invalid_role_is_rejected(tmp_path: Path) -> None:
    database = db.Database(tmp_path / "test.db")
    with pytest.raises(ValueError, match="invalid role"):
        database.add_turn("root", "nope")


def test_notes_and_clear(tmp_path: Path) -> None:
    database = db.Database(tmp_path / "test.db")
    database.add_note("दूध लाना है")
    assert database.recent_notes()[0]["text"] == "दूध लाना है"
    database.clear_conversation()
    assert database.recent_notes(), "clearing conversation must not touch notes"


def test_settings_upsert(tmp_path: Path) -> None:
    database = db.Database(tmp_path / "test.db")
    database.set_setting("theme", "dark")
    database.set_setting("theme", "light")
    assert database.get_setting("theme") == "light"
    assert database.get_setting("missing", "fallback") == "fallback"


def test_history_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "MAX_HISTORY_ROWS", 5)
    monkeypatch.setattr(db, "TRIM_SLACK", 2)

    database = db.Database(tmp_path / "test.db")
    for index in range(20):
        database.add_turn("user", f"m{index}")

    remaining = database.stats()["conversation"]
    assert remaining <= 7, f"history should be trimmed, found {remaining} rows"
    assert database.recent_turns(1)[0]["text"] == "m19", "newest turn must survive trimming"


def test_stats_counts_each_table(tmp_path: Path) -> None:
    database = db.Database(tmp_path / "test.db")
    database.add_turn("user", "a")
    database.add_note("b")
    database.set_setting("k", "v")
    assert database.stats() == {"conversation": 1, "notes": 1, "settings": 1}
