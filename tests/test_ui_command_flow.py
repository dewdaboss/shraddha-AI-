"""End-to-end command flow through the controller: speech text -> action -> spoken reply.

The executor is a dry-run recorder and the speech engine records instead of speaking, so
nothing is launched and nothing is audible. What is verified is the *behaviour*: the
right intent, the confirmation round-trip, the mute path, and the Hindi reply in chat.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from shraddha.commands import ActionExecutor
from shraddha.commands.actions import REFUSED
from shraddha.config import AppConfig
from shraddha.paths import get_paths
from shraddha.speech.tts import RecordingTts
from shraddha.ui.app import AssistantController

pytestmark = pytest.mark.usefixtures("qapp")


class Recorder(ActionExecutor):
    """An executor that remembers instead of launching."""

    def __init__(self, allow_power_actions: bool = False) -> None:
        self.launched: list[list[str]] = []
        self.urls: list[str] = []
        self.opened_paths: list[str] = []
        super().__init__(
            popen=self._popen,
            url_opener=lambda url: self.urls.append(url) or True,
            path_opener=self.opened_paths.append,
            allow_power_actions=allow_power_actions,
        )

    def _popen(self, argv, **kwargs):
        self.launched.append(list(argv))
        return object()


def build(config: AppConfig | None = None) -> tuple[AssistantController, Recorder, RecordingTts]:
    settings = config or AppConfig()
    executor = Recorder(allow_power_actions=settings.commands.allow_power_actions)
    voice = RecordingTts()
    controller = AssistantController(
        paths=get_paths().ensure(),
        config=settings,
        server_name=f"shraddha-flow-{uuid.uuid4().hex}",
        executor=executor,
        tts_engine=voice,
    )
    return controller, executor, voice


@pytest.fixture()
def parts(app_home, qapp) -> Iterator[tuple[AssistantController, Recorder, RecordingTts]]:
    controller, executor, voice = build()
    yield controller, executor, voice
    controller.shutdown()
    controller.overlay.deleteLater()
    qapp.processEvents()  # run deferred deletions while the event loop still exists


def replies(controller: AssistantController) -> list[tuple[str, str]]:
    return list(controller.overlay.chat.messages)


# ------------------------------------------------------------------ voice input
def test_a_spoken_command_is_shown_answered_and_spoken(parts) -> None:
    controller, executor, voice = parts

    controller.on_voice_final("क्रोम खोलो")

    messages = replies(controller)
    assert messages[-2] == ("user", "क्रोम खोलो")
    assert messages[-1][0] == "assistant"
    assert "Chrome" in messages[-1][1]
    assert [command.intent for command in executor.history] == ["app.open"]
    assert voice.spoken and voice.spoken[-1] == messages[-1][1]


def test_a_spoken_web_command_opens_the_catalogue_url(parts) -> None:
    controller, executor, _voice = parts

    controller.on_voice_final("श्रद्धा, Arena AI खोलो।")

    assert executor.urls
    assert executor.urls[0].startswith("https://arena.ai")
    assert "Arena" in controller.overlay.chat.last_message()[1]


def test_an_unknown_app_is_refused_in_hindi(parts) -> None:
    controller, executor, _voice = parts

    controller.on_voice_final("photoshop kholo")

    assert executor.launched == []
    assert REFUSED not in controller.overlay.chat.last_message()[1]
    assert "नहीं पता" in controller.overlay.chat.last_message()[1]


def test_a_date_question_is_answered_not_executed(parts) -> None:
    controller, _executor, voice = parts

    controller.on_voice_final("आज की तारीख बताओ")

    assert controller.overlay.chat.last_message()[0] == "assistant"
    assert voice.spoken


def test_empty_transcripts_are_ignored(parts) -> None:
    controller, _executor, _voice = parts
    before = controller.overlay.chat.count
    controller.on_voice_final("   ")
    assert controller.overlay.chat.count == before


# ------------------------------------------------------------------ confirmation
def test_a_power_command_asks_before_doing_anything(app_home, qapp) -> None:
    config = AppConfig()
    config.commands.allow_power_actions = True
    controller, executor, _voice = build(config)
    try:
        reply = controller.handle_text("कंप्यूटर बंद करो")

        assert "हाँ" in reply
        assert controller.confirmation.is_waiting is True
        assert executor.history == [], "nothing happens before the answer"

        assert controller.handle_text("नहीं") == "ठीक है, रद्द कर दिया।"
        assert controller.confirmation.is_waiting is False
        assert executor.history == []
    finally:
        controller.shutdown()
        controller.overlay.deleteLater()


def test_yes_executes_the_pending_command_once(app_home, qapp) -> None:
    config = AppConfig()
    config.commands.allow_power_actions = True
    controller, executor, _voice = build(config)
    try:
        controller.handle_text("कंप्यूटर बंद करो")
        reply = controller.handle_text("हाँ")

        assert [command.intent for command in executor.history] == ["system.power"]
        assert "समर्थित नहीं" in reply, "the action is still refused at the OS layer"
    finally:
        controller.shutdown()
        controller.overlay.deleteLater()


def test_an_unclear_answer_keeps_asking(parts) -> None:
    controller, executor, _voice = parts
    controller.router.allow_power_actions = True
    controller.handle_text("कंप्यूटर बंद करो")

    reply = controller.handle_text("शायद कल")

    assert "हाँ" in reply
    assert controller.confirmation.is_waiting is True
    assert executor.history == []


def test_power_stays_disabled_by_default(parts) -> None:
    controller, executor, _voice = parts
    reply = controller.handle_text("कंप्यूटर बंद करो")

    assert "सुरक्षा" in reply
    assert controller.confirmation.is_waiting is False, "no question, because it cannot run"
    assert executor.launched == [] and executor.urls == [], "nothing was executed"


# ---------------------------------------------------------------------- voice control
def test_stop_listening_mutes_and_replies(parts) -> None:
    controller, _executor, voice = parts

    controller.on_voice_final("श्रद्धा, मेरी बात सुनना बंद करो।")

    assert controller.voice.is_muted is True
    assert controller.overlay.mute_button.isChecked() is True
    assert "बंद" in controller.overlay.chat.last_message()[1]
    assert voice.spoken


def test_muting_while_listening_stops_the_microphone(parts) -> None:
    controller, _executor, _voice = parts

    controller.on_mic_toggled(True)
    controller.on_mute_toggled(True)

    assert controller.bridge.is_running is False, "the worker must not keep capturing"
    assert controller.overlay.mic_button.isChecked() is False, "no fake listening"
    assert controller.overlay.mute_button.isChecked() is True
    assert "म्यूट" in controller.overlay.status_text


def test_mute_toggle_reaches_the_service(parts) -> None:
    controller, _executor, _voice = parts

    controller.on_mute_toggled(True)
    assert controller.voice.is_muted is True
    assert controller.overlay.mute_button.isChecked() is True

    controller.on_mute_toggled(False)
    assert controller.voice.is_muted is False


def test_voice_switching_cycles_the_configured_voice(parts, monkeypatch) -> None:
    controller, _executor, _voice = parts
    monkeypatch.setattr(
        "shraddha.speech.tts.voice_options", lambda configured, models: ["कल्पना", "हेमंत"]
    )

    reply = controller.handle_text("आवाज़ बदलो")

    assert controller.config.tts.voice == "कल्पना"
    assert "कल्पना" in reply

    reply = controller.handle_text("आवाज़ बदलो")
    assert controller.config.tts.voice == "हेमंत"
    assert "हेमंत" in reply


def test_voice_switching_explains_when_nothing_is_installed(parts, monkeypatch) -> None:
    controller, _executor, _voice = parts
    monkeypatch.setattr("shraddha.speech.tts.voice_options", lambda configured, models: [])

    reply = controller.handle_text("आवाज़ बदलो")
    assert "हिन्दी आवाज़" in reply


# ------------------------------------------------------------------------ errors
def test_a_voice_error_is_reported_in_chat_and_status(parts) -> None:
    controller, _executor, _voice = parts

    controller.on_voice_error("माइक्रोफ़ोन उपलब्ध नहीं है।\n(माइक जोड़िए)")

    assert controller.overlay.chat.last_message()[0] == "system"
    assert "माइक" in controller.overlay.chat.last_message()[1]
    assert controller.overlay.status_text.startswith("माइक्रोफ़ोन उपलब्ध नहीं")
    assert controller.overlay.status_dot.state == "idle"


def test_partial_transcripts_update_the_status_line(parts) -> None:
    controller, _executor, _voice = parts
    controller.bridge.partial.emit("क्रोम खो")
    assert controller.overlay.partial_text == "क्रोम खो"


def test_listening_state_is_reflected_in_the_overlay(parts) -> None:
    controller, _executor, _voice = parts

    controller.on_voice_state("listening")
    assert controller.overlay.status_dot.state == "listening"
    assert "सुन" in controller.overlay.status_text

    controller.on_voice_state("idle")
    assert controller.overlay.status_dot.state == "idle"


# --------------------------------------------------------------- typed messages
def test_typed_commands_work_too(parts) -> None:
    controller, executor, _voice = parts

    controller.on_submitted("notepad kholo")

    assert [command.intent for command in executor.history] == ["app.open"]
    assert "Notepad" in controller.overlay.chat.last_message()[1]


def test_ordinary_chat_still_answers(parts) -> None:
    controller, _executor, _voice = parts

    controller.on_submitted("भारत की राजधानी क्या है?")

    assert controller.overlay.chat.last_message()[0] == "assistant"
    assert "Phase" in controller.overlay.chat.last_message()[1]


def test_conversation_is_persisted_for_both_sources(parts) -> None:
    controller, _executor, _voice = parts

    controller.on_voice_final("समय क्या है")
    controller.on_submitted("नमस्ते")

    stored = controller.db.recent_turns(limit=4)
    assert [turn["role"] for turn in stored] == ["user", "assistant", "user", "assistant"]


def test_speaking_can_be_switched_off(app_home, qapp) -> None:
    config = AppConfig()
    config.tts.speak_replies = False
    controller, _executor, voice = build(config)
    try:
        controller.on_voice_final("समय क्या है")
        assert voice.spoken == []
    finally:
        controller.shutdown()
        controller.overlay.deleteLater()
