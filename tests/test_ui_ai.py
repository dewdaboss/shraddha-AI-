"""Phase 3 - the Qt side: streamed bubbles, the worker bridge, and the controller.

The provider is fake, so both the chat view and the controller are exercised without a
network call, and the tests stay fast enough to run on every commit.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from shraddha.ai.base import AiError, AiEvent
from shraddha.ai.service import STATUS_READY, AiService
from shraddha.config import AppConfig, LlmConfig
from shraddha.paths import get_paths
from shraddha.speech.tts import RecordingTts
from shraddha.ui.ai import AiBridge
from shraddha.ui.app import AssistantController
from shraddha.ui.chat import STREAM_PLACEHOLDER, ChatView

pytestmark = pytest.mark.usefixtures("qapp")


def pump(qapp, bridge: AiBridge | None = None, timeout: float = 3.0) -> None:
    """Wait for the worker, then let Qt deliver the queued signals."""
    if bridge is not None:
        bridge.wait(timeout)
    qapp.processEvents()
    if bridge is not None:
        bridge.wait(0.5)
        qapp.processEvents()


# ------------------------------------------------------------------ chat view
def test_a_streamed_answer_grows_in_one_bubble(qapp) -> None:
    chat = ChatView()
    try:
        chat.begin_stream()
        assert chat.is_streaming is True
        assert chat.last_message() == ("assistant", STREAM_PLACEHOLDER)

        chat.append_chunk("भारत की")
        chat.append_chunk(" राजधानी")
        text = chat.finish_stream()

        assert text == "भारत की राजधानी"
        assert chat.is_streaming is False
        assert chat.count == 1
        assert chat.messages == [("assistant", "भारत की राजधानी")]
    finally:
        chat.deleteLater()


def test_appending_without_beginning_still_works(qapp) -> None:
    chat = ChatView()
    try:
        assert chat.append_chunk("सीधा") == "सीधा"
        assert chat.is_streaming is True
        chat.finish_stream()
        assert chat.messages == [("assistant", "सीधा")]
    finally:
        chat.deleteLater()


def test_two_streams_do_not_share_a_bubble(qapp) -> None:
    chat = ChatView()
    try:
        chat.begin_stream()
        chat.append_chunk("पहला")
        chat.begin_stream()  # closes the first one
        chat.append_chunk("दूसरा")
        chat.finish_stream()
        assert chat.messages == [("assistant", "पहला"), ("assistant", "दूसरा")]
    finally:
        chat.deleteLater()


def test_a_cancelled_stream_is_marked(qapp) -> None:
    chat = ChatView()
    try:
        chat.begin_stream()
        chat.append_chunk("आधा जवाब")
        assert chat.cancel_stream() == "आधा जवाब …"
        assert chat.is_streaming is False
    finally:
        chat.deleteLater()


def test_clearing_cancels_the_stream(qapp) -> None:
    chat = ChatView()
    try:
        chat.begin_stream()
        chat.append_chunk("कुछ")
        chat.clear()
        assert chat.is_streaming is False
        assert chat.count == 0
        assert chat.finish_stream() == ""
    finally:
        chat.deleteLater()


# --------------------------------------------------------------------- bridge
class FakeService:
    """Stands in for :class:`AiService`; replays a scripted event stream."""

    def __init__(self, events=(), error: Exception | None = None) -> None:
        self.events = list(events)
        self.error = error
        self.questions: list[str] = []
        self.closed = False

    @property
    def ready(self) -> bool:
        return True

    def status(self) -> str:
        return STATUS_READY

    def status_message(self) -> str:
        return ""

    def apply_consent(self, _intent: str) -> str:
        return "ठीक है।"

    def ask(self, text: str):
        self.questions.append(text)
        if self.error is not None:
            raise self.error
        yield from self.events

    def close(self) -> None:
        self.closed = True


def collect(qapp, service: FakeService, question: str = "सवाल") -> tuple[list[str], list[str], list[tuple[str, str]]]:
    bridge = AiBridge(service)  # type: ignore[arg-type]
    partials: list[str] = []
    finals: list[str] = []
    errors: list[tuple[str, str]] = []
    bridge.partial.connect(partials.append)
    bridge.final.connect(finals.append)
    bridge.error.connect(lambda message, code: errors.append((message, code)))
    assert bridge.ask(question) is True
    pump(qapp, bridge)
    return partials, finals, errors


def test_the_bridge_streams_and_finishes(qapp) -> None:
    service = FakeService(
        [
            AiEvent("partial", "नमस्ते"),
            AiEvent("partial", " जी"),
            AiEvent("final", "नमस्ते जी"),
        ]
    )

    partials, finals, errors = collect(qapp, service)

    assert partials == ["नमस्ते", " जी"]
    assert finals == ["नमस्ते जी"]
    assert errors == []
    assert service.questions == ["सवाल"]


def test_the_bridge_reports_errors_instead_of_raising(qapp) -> None:
    service = FakeService([AiEvent("error", "इंटरनेट नहीं है।", "network")])
    partials, finals, errors = collect(qapp, service)
    assert (partials, finals) == ([], [])
    assert errors == [("इंटरनेट नहीं है।", "network")]


def test_a_crashing_service_is_caught_and_reported(qapp) -> None:
    service = FakeService(error=RuntimeError("boom"))
    _partials, _finals, errors = collect(qapp, service)
    assert errors and errors[0][1] == "ai_error"


def test_only_one_request_runs_at_a_time(qapp) -> None:
    import threading

    release = threading.Event()

    class SlowService(FakeService):
        def ask(self, text: str):
            self.questions.append(text)
            assert release.wait(3)  # hold the worker until the assertion below is done
            yield AiEvent("final", "ठीक")

    service = SlowService()
    bridge = AiBridge(service)  # type: ignore[arg-type]
    started = bridge.ask("पहला")
    second = bridge.ask("दूसरा")
    release.set()
    pump(qapp, bridge)
    assert started is True
    assert second is False
    assert service.questions == ["पहला"]


def test_cancel_stops_the_worker(qapp) -> None:
    service = FakeService([AiEvent("partial", "एक"), AiEvent("final", "एक")])
    bridge = AiBridge(service)  # type: ignore[arg-type]
    cancelled: list[bool] = []
    bridge.cancelled.connect(lambda: cancelled.append(True))
    bridge.ask("सवाल")
    bridge.cancel()
    pump(qapp, bridge)
    assert bridge.is_busy is False


def test_shutdown_closes_the_service(qapp) -> None:
    service = FakeService([AiEvent("final", "ठीक")])
    bridge = AiBridge(service)  # type: ignore[arg-type]
    bridge.shutdown()
    assert service.closed is True


# --------------------------------------------------------------- the controller
class StubProvider:
    name = "gemini"
    model = "gemini-flash-latest"

    def __init__(self, chunks=("दिल्ली", " है।")) -> None:
        self.chunks = chunks

    def availability(self):
        return True, ""

    def stream(self, messages, system=None):
        yield from self.chunks

    def close(self) -> None:
        pass


def ready_config() -> AppConfig:
    config = AppConfig()
    config.llm = LlmConfig(provider="gemini", enabled=True, allow_cloud=True)
    return config


@pytest.fixture()
def ai_home(app_home, qapp, monkeypatch: pytest.MonkeyPatch) -> Iterator[AssistantController]:
    import shraddha.ai.service as ai_service_module

    monkeypatch.setattr(ai_service_module, "module_available", lambda _name: True)
    monkeypatch.setattr(
        ai_service_module, "resolve_api_key", lambda **_kw: ("AIzaTESTKEY", "env:GEMINI_API_KEY")
    )
    config = ready_config()
    service = AiService(config.llm, provider=StubProvider())
    voice = RecordingTts()
    controller = AssistantController(
        paths=get_paths().ensure(),
        config=config,
        server_name=f"shraddha-ai-{uuid.uuid4().hex}",
        tts_engine=voice,
        ai_service=service,
    )
    controller.voice_tts = voice  # convenience for assertions
    yield controller
    controller.shutdown()
    controller.overlay.deleteLater()
    qapp.processEvents()


def wait_for_answer(qapp, controller: AssistantController) -> None:
    deadline = time.monotonic() + 5
    while controller.ai_bridge.is_busy and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    pump(qapp, controller.ai_bridge)


def test_an_unknown_question_is_answered_by_ai_and_shown_as_one_bubble(ai_home) -> None:
    controller = ai_home

    controller._respond_to("भारत की राजधानी क्या है?", "typed")
    wait_for_answer(qt_app(controller), controller)

    messages = controller.overlay.chat.messages
    assert messages[-2] == ("user", "भारत की राजधानी क्या है?")
    assert messages[-1] == ("assistant", "दिल्ली है।")
    assert controller.overlay.is_streaming is False


def test_the_answer_is_spoken_once(ai_home) -> None:
    controller = ai_home
    controller._respond_to("भारत की राजधानी क्या है?", "typed")
    wait_for_answer(qt_app(controller), controller)
    assert controller.voice_tts.spoken == ["दिल्ली है।"]


def test_local_commands_still_win_over_the_model(ai_home) -> None:
    controller = ai_home
    reply, question = controller.plan_text("क्रोम खोलो")
    assert question is None
    assert "Chrome" in reply


def test_a_router_refusal_is_never_overridden_by_the_model(ai_home) -> None:
    controller = ai_home
    reply, question = controller.plan_text("photoshop kholo")
    assert question is None
    assert "नहीं पता" in reply


def test_the_consent_phrase_toggles_cloud_ai_and_is_persisted(ai_home) -> None:
    controller = ai_home
    controller.config.llm.allow_cloud = False

    reply, question = controller.plan_text("क्लाउड AI चालू करो")

    assert question is None
    assert "क्लाउड AI चालू" in reply
    assert controller.config.llm.allow_cloud is True
    assert get_paths().config_file.exists()


def test_without_consent_the_question_stays_local_and_a_notice_appears(app_home, qapp, monkeypatch) -> None:
    import shraddha.ai.service as ai_service_module

    monkeypatch.setattr(ai_service_module, "module_available", lambda _name: True)
    monkeypatch.setattr(
        ai_service_module, "resolve_api_key", lambda **_kw: ("AIzaTESTKEY", "env:GEMINI_API_KEY")
    )
    config = ready_config()
    config.llm.allow_cloud = False
    controller = AssistantController(
        paths=get_paths().ensure(),
        config=config,
        server_name=f"shraddha-ai-{uuid.uuid4().hex}",
        tts_engine=RecordingTts(),
        ai_service=AiService(config.llm, provider=StubProvider()),
    )
    try:
        reply, question = controller.plan_text("भारत की राजधानी क्या है?")
        assert question is None
        assert reply  # a local answer, not silence
        notice = controller.overlay.chat.messages[-1]
        assert notice[0] == "system"
        assert "क्लाउड AI" in notice[1]
        # ...and only once per session.
        controller.plan_text("दूसरा सवाल")
        notices = [text for _role, text in controller.overlay.chat.messages if "क्लाउड AI" in text]
        assert len(notices) == 1
    finally:
        controller.shutdown()
        controller.overlay.deleteLater()
        qapp.processEvents()


def test_an_ai_error_becomes_a_visible_message(app_home, qapp, monkeypatch) -> None:
    import shraddha.ai.service as ai_service_module

    monkeypatch.setattr(ai_service_module, "module_available", lambda _name: True)
    monkeypatch.setattr(
        ai_service_module, "resolve_api_key", lambda **_kw: ("AIzaTESTKEY", "env:GEMINI_API_KEY")
    )
    config = ready_config()

    class FailingProvider(StubProvider):
        def stream(self, messages, system=None):
            raise AiError("इंटरनेट नहीं है।", code="network")
            yield ""  # pragma: no cover - unreachable, keeps this a generator

    controller = AssistantController(
        paths=get_paths().ensure(),
        config=config,
        server_name=f"shraddha-ai-{uuid.uuid4().hex}",
        tts_engine=RecordingTts(),
        ai_service=AiService(config.llm, provider=FailingProvider()),
    )
    try:
        controller._respond_to("कुछ पूछूँ", "typed")
        wait_for_answer(qapp, controller)
        assert controller.overlay.chat.last_message()[0] == "assistant"
        assert "इंटरनेट" in controller.overlay.chat.last_message()[1]
        assert controller.executor.history == []  # the model never triggers an action
    finally:
        controller.shutdown()
        controller.overlay.deleteLater()
        qapp.processEvents()


def qt_app(_controller: AssistantController):
    from PySide6.QtWidgets import QApplication

    return QApplication.instance()
