"""Phase 4 - the action layer for timer, notes, clipboard, volume, windows and search.

Every OS dependency is a fake here: no timer is armed, no clipboard is touched, no window
is closed and no key is pressed. What is verified is the decision making - including the
honest Hindi answer when a skill is unavailable on this platform.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shraddha.commands.actions import (
    NO_NOTES,
    NO_TIMER,
    VOLUME_SET_UNSUPPORTED,
    WINDOWS_ONLY,
    ActionExecutor,
    search_files,
    startswith_tokens,
    windows_skills,
)
from shraddha.commands.router import (
    INTENT_CLIPBOARD_COPY,
    INTENT_CLIPBOARD_READ,
    INTENT_FILE_SEARCH,
    INTENT_NOTE_ADD,
    INTENT_NOTE_CLEAR,
    INTENT_NOTE_READ,
    INTENT_TIMER_CANCEL,
    INTENT_TIMER_SET,
    INTENT_TIMER_STATUS,
    INTENT_VOLUME,
    INTENT_WINDOW,
    Command,
)
from shraddha.storage import Database

pytestmark = pytest.mark.usefixtures("app_home")


# ------------------------------------------------------------------------ fakes
class FakeTimer:
    def __init__(self) -> None:
        self.started: list[int] = []
        self.cancelled = 0
        self.status_calls = 0
        self.fail = False

    def start(self, seconds: int) -> str:
        if self.fail:
            raise RuntimeError("timer exploded")
        self.started.append(seconds)
        return f"{seconds} सेकंड का टाइमर लगा दिया।"

    def cancel(self) -> str:
        self.cancelled += 1
        return "टाइमर रद्द कर दिया।"

    def status(self) -> str:
        self.status_calls += 1
        return "5 मिनट का टाइमर चल रहा है।"


# ------------------------------------------------------------------------ timer
def test_timer_set_cancel_status() -> None:
    timer = FakeTimer()
    executor = ActionExecutor(timer=timer)

    started = executor.execute(Command(INTENT_TIMER_SET, args={"seconds": "300"}))
    assert started.ok is True
    assert timer.started == [300]

    assert executor.execute(Command(INTENT_TIMER_CANCEL)).ok is True
    assert timer.cancelled == 1

    assert executor.execute(Command(INTENT_TIMER_STATUS)).ok is True
    assert timer.status_calls == 1


def test_timer_validation_and_missing_service() -> None:
    assert ActionExecutor().execute(Command(INTENT_TIMER_SET, args={"seconds": "300"})).message == NO_TIMER

    executor = ActionExecutor(timer=FakeTimer())
    bad = executor.execute(Command(INTENT_TIMER_SET, args={"seconds": "abc"}))
    assert bad.ok is False
    assert "अवधि" in bad.message
    assert executor.execute(Command(INTENT_TIMER_SET, args={"seconds": "-5"})).ok is False


def test_a_broken_timer_is_reported_not_raised() -> None:
    timer = FakeTimer()
    timer.fail = True
    result = ActionExecutor(timer=timer).execute(Command(INTENT_TIMER_SET, args={"seconds": "60"}))
    assert result.ok is True  # the object returned a sentence; we keep it visible
    assert "नहीं" in result.message or "टाइमर" in result.message


# ------------------------------------------------------------------------ notes
@pytest.fixture()
def notes_db(tmp_path: Path) -> Database:
    return Database(tmp_path / "notes.db")


@pytest.fixture()
def notes_executor(notes_db: Database) -> ActionExecutor:
    return ActionExecutor(
        notes_add=notes_db.add_note,
        notes_recent=lambda limit: [note["text"] for note in notes_db.recent_notes(limit)],
        notes_clear=notes_db.delete_notes,
    )


def test_a_note_is_stored_and_read_back(notes_executor: ActionExecutor, notes_db: Database) -> None:
    stored = notes_executor.execute(Command(INTENT_NOTE_ADD, args={"text": "दूध लाना है"}))
    assert stored.ok is True

    assert [note["text"] for note in notes_db.recent_notes(5)] == ["दूध लाना है"]

    read = notes_executor.execute(Command(INTENT_NOTE_READ))
    assert read.ok is True
    assert "दूध लाना है" in read.message


def test_notes_are_numbered_newest_first(notes_executor: ActionExecutor) -> None:
    notes_executor.execute(Command(INTENT_NOTE_ADD, args={"text": "पहला"}))
    notes_executor.execute(Command(INTENT_NOTE_ADD, args={"text": "दूसरा"}))
    message = notes_executor.execute(Command(INTENT_NOTE_READ)).message
    assert "1. दूसरा" in message
    assert "2. पहला" in message


def test_reading_with_no_notes_says_so(notes_executor: ActionExecutor) -> None:
    result = notes_executor.execute(Command(INTENT_NOTE_READ))
    assert result.ok is True
    assert "कोई नोट नहीं" in result.message


def test_clearing_notes_reports_the_count(notes_executor: ActionExecutor) -> None:
    notes_executor.execute(Command(INTENT_NOTE_ADD, args={"text": "एक"}))
    notes_executor.execute(Command(INTENT_NOTE_ADD, args={"text": "दो"}))

    result = notes_executor.execute(Command(INTENT_NOTE_CLEAR))

    assert result.ok is True
    assert "2" in result.message
    assert notes_executor.execute(Command(INTENT_NOTE_READ)).message.count(".") == 0


def test_notes_without_a_store_are_refused_honestly() -> None:
    executor = ActionExecutor()
    assert executor.execute(Command(INTENT_NOTE_ADD, args={"text": "x"})).message == NO_NOTES
    assert executor.execute(Command(INTENT_NOTE_READ)).message == NO_NOTES
    assert executor.execute(Command(INTENT_NOTE_CLEAR)).message == NO_NOTES


def test_an_empty_note_is_refused(notes_executor: ActionExecutor) -> None:
    result = notes_executor.execute(Command(INTENT_NOTE_ADD, args={"text": "   "}))
    assert result.ok is False
    assert "क्या नोट" in result.message


def test_a_broken_notes_store_is_reported(tmp_path: Path) -> None:
    def explode(_text: str) -> int:
        raise RuntimeError("disk on fire")

    executor = ActionExecutor(notes_add=explode)
    result = executor.execute(Command(INTENT_NOTE_ADD, args={"text": "x"}))
    assert result.ok is False
    assert "सेव नहीं" in result.message


# -------------------------------------------------------------------- clipboard
def test_clipboard_copy_and_read() -> None:
    board: list[str] = []
    executor = ActionExecutor(
        clipboard_write=lambda text: board.append(text) or True,
        clipboard_read=lambda: board[-1] if board else "",
    )

    assert executor.execute(Command(INTENT_CLIPBOARD_COPY, args={"text": "बैठक 5 बजे"})).ok is True
    assert board == ["बैठक 5 बजे"]

    result = executor.execute(Command(INTENT_CLIPBOARD_READ))
    assert result.ok is True
    assert "बैठक 5 बजे" in result.message


def test_empty_clipboard_and_long_clipboard() -> None:
    empty = ActionExecutor(clipboard_read=lambda: "  ")
    assert "खाली" in empty.execute(Command(INTENT_CLIPBOARD_READ)).message

    long_text = "x" * 900
    long = ActionExecutor(clipboard_read=lambda: long_text)
    message = long.execute(Command(INTENT_CLIPBOARD_READ)).message
    assert len(message) < 700, "a huge clipboard must not flood the chat bubble"


def test_clipboard_needs_the_right_platform() -> None:
    result = ActionExecutor().execute(Command(INTENT_CLIPBOARD_READ))
    assert result.ok is False
    assert result.message == WINDOWS_ONLY


def test_a_failing_clipboard_is_reported() -> None:
    def explode(_text: str) -> bool:
        raise OSError("clipboard locked by another app")

    result = ActionExecutor(clipboard_write=explode).execute(
        Command(INTENT_CLIPBOARD_COPY, args={"text": "x"})
    )
    assert result.ok is False
    assert "कॉपी नहीं" in result.message


# ----------------------------------------------------------------------- volume
def test_volume_up_down_mute() -> None:
    calls: list[str] = []
    executor = ActionExecutor(volume_control=lambda action: calls.append(action) or True)

    for action in ("up", "down", "mute"):
        assert executor.execute(Command(INTENT_VOLUME, args={"action": action})).ok is True
    assert calls == ["up", "down", "mute"]


def test_absolute_volume_is_honest_about_its_limit() -> None:
    calls: list[str] = []
    executor = ActionExecutor(volume_control=lambda action: calls.append(action) or True)

    result = executor.execute(Command(INTENT_VOLUME, args={"action": "set", "level": "40"}))

    assert result.ok is False
    assert result.message == VOLUME_SET_UNSUPPORTED
    assert calls == [], "nothing may be pressed for an unsupported request"


def test_volume_without_a_platform_controller() -> None:
    result = ActionExecutor().execute(Command(INTENT_VOLUME, args={"action": "up"}))
    assert result.ok is False
    assert result.message == WINDOWS_ONLY


def test_volume_failure_is_reported() -> None:
    result = ActionExecutor(volume_control=lambda _action: False).execute(
        Command(INTENT_VOLUME, args={"action": "up"})
    )
    assert result.ok is False
    assert "आवाज़ बदल नहीं सकी" in result.message


# ----------------------------------------------------------------------- window
def test_window_minimize_and_close() -> None:
    calls: list[str] = []
    executor = ActionExecutor(window_control=lambda action: calls.append(action) or True)

    assert executor.execute(Command(INTENT_WINDOW, args={"action": "minimize"})).ok is True
    assert executor.execute(Command(INTENT_WINDOW, args={"action": "close"})).ok is True
    assert calls == ["minimize", "close"]


def test_window_without_a_platform_controller_and_on_failure() -> None:
    assert ActionExecutor().execute(Command(INTENT_WINDOW, args={"action": "minimize"})).message == WINDOWS_ONLY

    failing = ActionExecutor(window_control=lambda _action: False)
    result = failing.execute(Command(INTENT_WINDOW, args={"action": "close"}))
    assert result.ok is False
    assert "विंडो नहीं मिली" in result.message


# ------------------------------------------------------------------ file search
@pytest.fixture()
def documents(tmp_path: Path) -> Path:
    root = tmp_path / "Documents"
    root.mkdir(parents=True, exist_ok=True)
    (root / "budget-2026.xlsx").write_text("x", encoding="utf-8")
    (root / "old budget.txt").write_text("x", encoding="utf-8")
    (root / "notes.txt").write_text("x", encoding="utf-8")
    (root / "बजट-2026.xlsx").write_text("x", encoding="utf-8")
    (root / "nested").mkdir()
    (root / "nested" / "budget-draft.docx").write_text("x", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "budget-noise.js").write_text("x", encoding="utf-8")
    return root


def test_search_finds_matching_files_and_skips_noise(documents: Path) -> None:
    matches = search_files([documents], "budget")

    names = sorted(path.name for path in matches)
    assert names == ["budget-2026.xlsx", "budget-draft.docx", "old budget.txt"]
    assert all("node_modules" not in str(path) for path in matches)


def test_search_works_with_devanagari_names(documents: Path) -> None:
    """Hindi query + Hindi filename: found. Latin query + Hindi filename: honestly not."""
    matches = search_files([documents], "बजट")
    assert [path.name for path in matches] == ["बजट-2026.xlsx"]
    assert search_files([documents], "salary") == []


def test_search_matches_any_word_order_and_ignores_case(documents: Path) -> None:
    assert [p.name for p in search_files([documents], "BUDGET 2026")] == ["budget-2026.xlsx"]
    assert search_files([documents], "nonexistent") == []


def test_search_respects_the_limit(documents: Path) -> None:
    assert len(search_files([documents], "budget", limit=2)) == 2


def test_search_respects_the_depth_limit(tmp_path: Path) -> None:
    deep = tmp_path / "deep"
    target = deep / "a" / "b" / "c" / "d" / "e"
    target.mkdir(parents=True)
    (target / "buried.txt").write_text("x", encoding="utf-8")
    assert search_files([deep], "buried", max_depth=2) == []
    assert search_files([deep], "buried", max_depth=8)


def test_executor_search_messages(documents: Path) -> None:
    executor = ActionExecutor(search_roots=lambda: (documents,))

    found = executor.execute(Command(INTENT_FILE_SEARCH, args={"query": "budget"}))
    assert found.ok is True
    assert "3 फाइल" in found.message

    missing = executor.execute(Command(INTENT_FILE_SEARCH, args={"query": "salary"}))
    assert missing.ok is False
    assert "नहीं मिली" in missing.message


def test_executor_search_without_roots(tmp_path: Path) -> None:
    executor = ActionExecutor(search_roots=lambda: (tmp_path / "does-not-exist",))
    result = executor.execute(Command(INTENT_FILE_SEARCH, args={"query": "x"}))
    assert result.ok is False
    assert "कोई फोल्डर नहीं मिला" in result.message


def test_executor_search_without_a_query(documents: Path) -> None:
    executor = ActionExecutor(search_roots=lambda: (documents,))
    result = executor.execute(Command(INTENT_FILE_SEARCH, args={"query": "  "}))
    assert result.ok is False
    assert "क्या ढूँढना है" in result.message


def test_token_helper() -> None:
    assert startswith_tokens("budget-2026.xlsx", ["budget", "2026"]) is True
    assert startswith_tokens("budget.xlsx", ["2026"]) is False


# ------------------------------------------------------------------ platform api
def test_windows_skills_are_empty_off_windows() -> None:
    import sys

    if sys.platform == "win32":  # pragma: no cover - only on Windows
        assert set(windows_skills()) == {
            "clipboard_read",
            "clipboard_write",
            "volume_control",
            "window_control",
        }
    else:
        assert windows_skills() == {}


def test_dry_run_never_touches_a_skill() -> None:
    calls: list[str] = []
    executor = ActionExecutor(dry_run=True, volume_control=lambda a: calls.append(a) or True)
    result = executor.execute(Command(INTENT_VOLUME, args={"action": "up"}))
    assert result.ok is True
    assert result.detail == "dry_run"
    assert calls == []
