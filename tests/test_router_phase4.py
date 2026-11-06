"""Phase 4 - the new intents, as sentences a user would actually say.

Pure routing only: no timer is armed and no OS call is made. The interesting cases are
the *near misses* - "notepad kholo" must stay an app command, "mute karo" must stay the
microphone, and "5 minute ka समय बताओ" must still be a clock question.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shraddha.commands import apps
from shraddha.commands.router import (
    INTENT_APP_OPEN,
    INTENT_CLIPBOARD_COPY,
    INTENT_CLIPBOARD_READ,
    INTENT_FILE_SEARCH,
    INTENT_FOLDER_OPEN,
    INTENT_INFO_DATE,
    INTENT_INFO_TIME,
    INTENT_NOTE_ADD,
    INTENT_NOTE_CLEAR,
    INTENT_NOTE_READ,
    INTENT_TIMER_CANCEL,
    INTENT_TIMER_SET,
    INTENT_TIMER_STATUS,
    INTENT_UNKNOWN,
    INTENT_VOICE_STOP,
    INTENT_VOLUME,
    INTENT_WINDOW,
    Command,
    CommandRouter,
)

pytestmark = pytest.mark.usefixtures("app_home")


@pytest.fixture()
def router(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CommandRouter:
    """Every known folder "exists" inside tmp_path, so folder routing is testable."""
    documents = tmp_path / "Documents"
    documents.mkdir()
    monkeypatch.setattr(apps, "folder_path", lambda key: documents)
    return CommandRouter()


# ------------------------------------------------------------------------ timer
@pytest.mark.parametrize(
    ("said", "seconds"),
    [
        ("5 minute ka timer lagao", 300),
        ("5 मिनट का टाइमर लगाओ", 300),
        ("2 minutes ka timer", 120),
        ("30 second ka timer lagao", 30),
        ("1 ghante ka timer lagao", 3_600),
        ("1 ghanta 30 minute ka timer", 5_400),
        ("aadha ghanta timer", 1_800),
        ("10 second ka alarm", 10),
        ("ek minute ka timer", 60),
        ("timer lagao 45 seconds ka", 45),
    ],
)
def test_timer_durations_are_understood(router: CommandRouter, said: str, seconds: int) -> None:
    command = router.route(said)
    assert command.intent == INTENT_TIMER_SET
    assert command.args["seconds"] == str(seconds)
    assert command.spoken, "the user must hear what was armed"
    assert command.needs_confirmation is False


def test_timer_cancel_and_status(router: CommandRouter) -> None:
    assert router.route("timer band karo").intent == INTENT_TIMER_CANCEL
    assert router.route("टाइमर रद्द करो").intent == INTENT_TIMER_CANCEL
    assert router.route("timer cancel").intent == INTENT_TIMER_CANCEL
    assert router.route("timer kitna baki hai").intent == INTENT_TIMER_STATUS
    assert router.route("टाइमर कितना बाकी है").intent == INTENT_TIMER_STATUS


@pytest.mark.parametrize("said", ["1 second ka timer", "100 ghante ka timer", "0 minute ka timer"])
def test_out_of_range_timers_are_refused(router: CommandRouter, said: str) -> None:
    command = router.route(said)
    assert command.intent == INTENT_UNKNOWN
    assert command.spoken


def test_a_timer_without_a_duration_asks_for_one(router: CommandRouter) -> None:
    command = router.route("timer lagao")
    assert command.intent == INTENT_UNKNOWN
    assert "मिनट" in command.spoken or "टाइमर" in command.spoken


# ------------------------------------------------------------------------ notes
def test_note_is_stored_with_its_text(router: CommandRouter) -> None:
    command = router.route("नोट लिखो दूध लाना है")
    assert command.intent == INTENT_NOTE_ADD
    assert command.args["text"] == "दूध लाना है"


def test_note_read_and_clear(router: CommandRouter) -> None:
    assert router.route("मेरा नोट पढ़ो").intent == INTENT_NOTE_READ
    assert router.route("notes batao").intent == INTENT_NOTE_READ
    clear = router.route("नोट साफ़ करो")
    assert clear.intent == INTENT_NOTE_CLEAR
    assert clear.needs_confirmation is True, "deleting data must always be confirmed"


def test_note_without_content_asks_for_it(router: CommandRouter) -> None:
    command = router.route("note likho")
    assert command.intent == INTENT_UNKNOWN
    assert command.spoken


# -------------------------------------------------------------------- clipboard
def test_clipboard_copy_keeps_the_content(router: CommandRouter) -> None:
    command = router.route("copy karo बैठक 5 बजे")
    assert command.intent == INTENT_CLIPBOARD_COPY
    assert command.args["text"] == "बैठक 5 बजे"


def test_clipboard_copy_without_content_asks_for_it(router: CommandRouter) -> None:
    command = router.route("ye copy karo")
    assert command.intent == INTENT_UNKNOWN
    assert command.spoken


def test_clipboard_read(router: CommandRouter) -> None:
    assert router.route("clipboard kya hai").intent == INTENT_CLIPBOARD_READ
    assert router.route("क्लिपबोर्ड में क्या है").intent == INTENT_CLIPBOARD_READ


# ----------------------------------------------------------------------- volume
@pytest.mark.parametrize(
    ("said", "action"),
    [
        ("volume badhao", "up"),
        ("आवाज़ बढ़ाओ", "up"),
        ("volume कम करो", "down"),
        ("volume down", "down"),
        ("volume mute karo", "mute"),
    ],
)
def test_volume_actions(router: CommandRouter, said: str, action: str) -> None:
    command = router.route(said)
    assert command.intent == INTENT_VOLUME
    assert command.args["action"] == action


def test_absolute_volume_is_recognised_so_the_reply_can_be_specific(router: CommandRouter) -> None:
    command = router.route("volume 40 karo")
    assert command.intent == INTENT_VOLUME
    assert command.args == {"action": "set", "level": "40"}


def test_mic_mute_is_still_the_microphone(router: CommandRouter) -> None:
    assert router.route("mute karo").intent == INTENT_VOICE_STOP
    assert router.route("म्यूट करो").intent == INTENT_VOICE_STOP


# ----------------------------------------------------------------------- window
def test_window_minimize_and_close(router: CommandRouter) -> None:
    minimised = router.route("window minimize karo")
    assert minimised.intent == INTENT_WINDOW
    assert minimised.args["action"] == "minimize"
    assert minimised.needs_confirmation is False

    closed = router.route("window band karo")
    assert closed.intent == INTENT_WINDOW
    assert closed.args["action"] == "close"
    assert closed.needs_confirmation is True, "closing a window is destructive"


# ------------------------------------------------------------------ file search
def test_search_extracts_the_query_and_the_folder(router: CommandRouter) -> None:
    command = router.route("documents में बजट फाइल ढूँढो")
    assert command.intent == INTENT_FILE_SEARCH
    assert command.args["folder"] == "documents"
    assert "बजट" in command.args["query"]
    assert "फाइल" not in command.args["query"]


def test_search_without_a_query_asks(router: CommandRouter) -> None:
    command = router.route("documents mein dhundo")
    assert command.intent == INTENT_UNKNOWN
    assert command.spoken


# ------------------------------------------------------------------ near misses
@pytest.mark.parametrize(
    ("said", "intent"),
    [
        ("notepad kholo", INTENT_APP_OPEN),
        ("नोटपैड खोलो", INTENT_APP_OPEN),
        ("Chrome kholo", INTENT_APP_OPEN),
        ("documents kholo", INTENT_FOLDER_OPEN),
        ("आज की तारीख बताओ", INTENT_INFO_DATE),
        ("time kya hai", INTENT_INFO_TIME),
        ("5 minute ka समय बताओ", INTENT_INFO_TIME),
        ("5 मिनट बाद क्या होगा", INTENT_UNKNOWN),
        ("volume बदलो", INTENT_UNKNOWN),
    ],
)
def test_phase_4_does_not_steal_existing_commands(
    router: CommandRouter, said: str, intent: str
) -> None:
    assert router.route(said).intent == intent


def test_the_new_intents_count_as_actions() -> None:
    for intent in (
        INTENT_TIMER_SET,
        INTENT_TIMER_CANCEL,
        INTENT_NOTE_ADD,
        INTENT_NOTE_READ,
        INTENT_CLIPBOARD_COPY,
        INTENT_CLIPBOARD_READ,
        INTENT_VOLUME,
        INTENT_WINDOW,
        INTENT_FILE_SEARCH,
    ):
        assert Command(intent).is_actionable is True
    assert Command(INTENT_TIMER_STATUS).is_actionable is True
    assert Command(INTENT_UNKNOWN).is_actionable is False
    assert Command(INTENT_INFO_TIME).is_actionable is False


def test_routing_stays_fast(router: CommandRouter) -> None:
    """The exit criterion from the roadmap: < 5 ms per match, measured here."""
    import time

    sentences = [
        "क्रोम खोलो",
        "5 मिनट का टाइमर लगाओ",
        "नोट लिखो दूध लाना है",
        "volume बढ़ाओ",
        "documents में बजट ढूँढो",
    ]
    started = time.perf_counter()
    for _ in range(200):
        for sentence in sentences:
            router.route(sentence)
    average_ms = (time.perf_counter() - started) * 1_000 / (200 * len(sentences))
    assert average_ms < 5.0, f"routing took {average_ms:.2f} ms per sentence"
