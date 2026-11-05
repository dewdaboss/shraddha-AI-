"""Hindi + Hinglish command routing.

Every case here is a sentence a user could actually say. The router is pure: it may only
produce intents from :mod:`shraddha.commands.router`, and anything it cannot resolve
confidently must come back as ``unknown`` rather than as a guess.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shraddha.commands import apps
from shraddha.commands.apps import find_app, normalise_name
from shraddha.commands.router import (
    INTENT_APP_OPEN,
    INTENT_INFO_DATE,
    INTENT_INFO_TIME,
    INTENT_POWER,
    INTENT_UNKNOWN,
    INTENT_VOICE_STOP,
    INTENT_VOICE_SWITCH,
    INTENT_WEB_OPEN,
    UNKNOWN_TARGET_HINT,
    Command,
    CommandRouter,
)

pytestmark = pytest.mark.usefixtures("app_home")


@pytest.fixture()
def router() -> CommandRouter:
    return CommandRouter()


@pytest.fixture()
def folders(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Pretend every known folder exists inside ``tmp_path``."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.setattr(apps, "folder_path", lambda key: downloads)
    return downloads


# ------------------------------------------------------------------ app opening
@pytest.mark.parametrize(
    ("said", "target"),
    [
        ("श्रद्धा, Chrome खोलो।", "chrome"),
        ("chrome kholo", "chrome"),
        ("Chrome khol do", "chrome"),
        ("क्रोम खोलो", "chrome"),
        ("google chrome open karo", "chrome"),
        ("notepad kholo", "notepad"),
        ("कैलकुलेटर खोलो", "calculator"),
        ("calculator open karo", "calculator"),
        ("vscode kholo", "vscode"),
        ("सेटिंग्स खोलो", "settings"),
        ("paint kholo", "paint"),
        ("files kholo", "explorer"),
    ],
)
def test_hindi_and_hinglish_open_commands(router: CommandRouter, said: str, target: str) -> None:
    command = router.route(said)
    assert command.intent == INTENT_APP_OPEN
    assert command.target == target
    assert command.spoken, "the assistant must say what it is doing"


def test_the_wake_word_is_stripped_before_parsing(router: CommandRouter) -> None:
    command = router.route("श्रद्धा, Chrome खोलो।")
    assert command.target == "chrome"
    assert "श्रद्धा" not in command.spoken


def test_web_targets_carry_their_url(router: CommandRouter) -> None:
    command = router.route("श्रद्धा, Arena AI खोलो।")
    assert command.intent == INTENT_WEB_OPEN
    assert command.target == "arena"
    assert command.args["url"] == "https://arena.ai"


def test_an_unknown_app_is_refused_not_guessed(router: CommandRouter) -> None:
    command = router.route("photoshop kholo")
    assert command.intent == INTENT_UNKNOWN
    assert command.spoken == UNKNOWN_TARGET_HINT
    assert command.is_actionable is False


def test_an_open_verb_without_a_target_asks_again(router: CommandRouter) -> None:
    command = router.route("kholo")
    assert command.intent == INTENT_UNKNOWN


# ----------------------------------------------------------------------- folders
def test_downloads_folder_in_hindi(router: CommandRouter, folders: Path) -> None:
    command = router.route("श्रद्धा, मेरी डाउनलोड फाइल खोलो।")
    assert command.intent == "folder.open"
    assert command.target == "downloads"
    assert command.args["path"] == str(folders)


def test_documents_folder_in_hinglish(router: CommandRouter, folders: Path) -> None:
    command = router.route("documents kholo")
    assert command.intent == "folder.open"
    assert command.target == "documents"


def test_a_folder_that_does_not_exist_is_reported_as_unknown(
    router: CommandRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(apps, "folder_path", lambda key: None)
    assert router.route("downloads kholo").intent == INTENT_UNKNOWN


# ------------------------------------------------------------------ date and time
@pytest.mark.parametrize(
    "said",
    ["श्रद्धा, आज की तारीख बताओ।", "aaj ki tarikh kya hai", "आज कौन सा दिन है", "date batao"],
)
def test_date_questions(router: CommandRouter, said: str) -> None:
    assert router.route(said).intent == INTENT_INFO_DATE


@pytest.mark.parametrize("said", ["समय क्या है?", "samay kya hai", "kitne baje hain", "time batao"])
def test_time_questions(router: CommandRouter, said: str) -> None:
    assert router.route(said).intent == INTENT_INFO_TIME


def test_date_is_checked_before_time(router: CommandRouter) -> None:
    # "तारीख" also implies "आज", which must not be mistaken for a clock question.
    assert router.route("आज की तारीख और समय").intent == INTENT_INFO_DATE


# ------------------------------------------------------------------------ voice
@pytest.mark.parametrize(
    "said",
    [
        "श्रद्धा, मेरी बात सुनना बंद करो।",
        "सुनना बंद करो",
        "stop listening",
        "sunna band karo",
        "mute",
    ],
)
def test_stop_listening_wins_over_everything_else(router: CommandRouter, said: str) -> None:
    assert router.route(said).intent == INTENT_VOICE_STOP


@pytest.mark.parametrize("said", ["आवाज़ बदलो", "voice change karo", "next voice", "दूसरी आवाज़"])
def test_voice_switching(router: CommandRouter, said: str) -> None:
    assert router.route(said).intent == INTENT_VOICE_SWITCH


# ------------------------------------------------------------------------ power
def test_power_commands_are_recognised_but_disabled_by_default(router: CommandRouter) -> None:
    command = router.route("कंप्यूटर बंद करो")
    assert command.intent == INTENT_POWER
    assert command.needs_confirmation is False
    assert "सुरक्षा" in command.spoken


@pytest.mark.parametrize(
    ("said", "action"),
    [
        ("shutdown karo", "shutdown"),
        ("restart karo", "restart"),
        ("computer sleep karo", "sleep"),
        ("screen lock karo", "lock"),
    ],
)
def test_power_actions_ask_for_confirmation_when_enabled(said: str, action: str) -> None:
    router = CommandRouter(allow_power_actions=True)
    command = router.route(said)
    assert command.intent == INTENT_POWER
    assert command.needs_confirmation is True
    assert command.args["action"] == action
    assert "हाँ" in command.spoken


def test_a_negated_power_command_is_not_a_power_command(router: CommandRouter) -> None:
    assert router.route("कंप्यूटर बंद मत करो").intent == INTENT_UNKNOWN


# ---------------------------------------------------------------------- fallback
@pytest.mark.parametrize(
    "said",
    [
        "भारत की राजधानी क्या है?",
        "तुम कौन हो",
        "write a poem about rain",
        "श्रद्धा",
        "   ",
    ],
)
def test_everything_else_is_unknown_so_the_chat_layer_answers(
    router: CommandRouter, said: str
) -> None:
    command = router.route(said)
    assert command.intent == INTENT_UNKNOWN
    assert command.is_actionable is False


def test_commands_can_be_switched_off_entirely() -> None:
    command = CommandRouter(enabled=False).route("chrome kholo")
    assert command.intent == INTENT_UNKNOWN
    assert "बंद" in command.spoken


# ----------------------------------------------------------------- catalogue bits
def test_normalise_name_strips_fillers_and_punctuation() -> None:
    assert normalise_name("मेरी Chrome, खोलो।") == "chrome खोलो"
    assert normalise_name("  Please OPEN  Notepad ") == "open notepad"


def test_find_app_prefers_exact_keys_over_substrings() -> None:
    assert find_app("chrome").key == "chrome"  # type: ignore[union-attr]
    assert find_app("गूगल क्रोम").key == "chrome"  # type: ignore[union-attr]
    assert find_app("photoshop") is None


def test_command_target_and_actionable_helpers() -> None:
    command = Command(INTENT_APP_OPEN, args={"target": "chrome"})
    assert command.target == "chrome"
    assert command.is_actionable is True
    assert Command(INTENT_INFO_TIME).is_actionable is False
