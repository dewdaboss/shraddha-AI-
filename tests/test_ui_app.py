"""Wiring tests: the controller, the tray/hotkey/IPC seams and persistence.

The controller is built against a temporary home directory and a unique IPC name, so
these tests never touch the real running assistant.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from shraddha.config import AppConfig
from shraddha.paths import get_paths
from shraddha.ui.app import AssistantController
from shraddha.ui.ipc import ActivationServer, notify_running_instance

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture()
def controller(app_home: Path, qapp) -> Iterator[AssistantController]:
    instance = AssistantController(
        paths=get_paths().ensure(),
        config=AppConfig(),
        server_name=f"shraddha-test-{uuid.uuid4().hex}",
    )
    yield instance
    instance.shutdown()
    instance.overlay.deleteLater()


def test_welcome_message_is_shown(controller: AssistantController) -> None:
    assert controller.overlay.chat.count == 1
    role, text = controller.overlay.chat.last_message()
    assert role == "assistant"
    assert "श्रद्धा" in text


def test_submitting_a_command_answers_and_persists(controller: AssistantController) -> None:
    controller.on_submitted("समय क्या है?")

    messages = controller.overlay.chat.messages
    assert messages[-2] == ("user", "समय क्या है?")
    assert messages[-1][0] == "assistant"
    assert ":" in messages[-1][1]

    assert controller.db is not None
    stored = controller.db.recent_turns(limit=2)
    assert [turn["role"] for turn in stored] == ["user", "assistant"]


def test_fallback_is_stored_too(controller: AssistantController) -> None:
    controller.on_submitted("भारत की राजधानी क्या है?")
    assert "Phase 6" in controller.overlay.chat.messages[-1][1]


def test_microphone_without_recogniser_explains_itself_once(
    controller: AssistantController,
) -> None:
    controller.on_mic_toggled(True)
    assert controller.overlay.chat.messages[-1][0] == "system"
    assert "Phase 2" in controller.overlay.chat.messages[-1][1]
    assert controller.overlay.mic_button.isChecked() is False, "must not fake listening"
    assert controller.overlay.status_dot.state == "idle"

    count_before = controller.overlay.chat.count
    controller.on_mic_toggled(True)
    assert controller.overlay.chat.count == count_before, "the hint must not spam the chat"


def test_history_is_restored_in_a_new_controller(app_home: Path, qapp) -> None:
    paths = get_paths().ensure()
    first = AssistantController(
        paths=paths, config=AppConfig(), server_name=f"t-{uuid.uuid4().hex}"
    )
    first.on_submitted("नमस्ते")
    first.shutdown()

    second = AssistantController(
        paths=paths, config=AppConfig(), server_name=f"t-{uuid.uuid4().hex}"
    )
    try:
        roles = [role for role, _ in second.overlay.chat.messages]
        assert roles.count("user") >= 1
        assert "नमस्ते" in [text for role, text in second.overlay.chat.messages if role == "user"]
    finally:
        second.shutdown()


def test_clear_chat_also_clears_storage(controller: AssistantController) -> None:
    controller.on_submitted("नमस्ते")
    controller.on_clear_chat()
    assert controller.overlay.chat.count == 0
    assert controller.db is not None
    assert controller.db.recent_turns() == []


def test_start_acquires_the_single_instance_lock(controller: AssistantController) -> None:
    assert controller.start(show_overlay=False) is True
    assert controller.has_lock is True

    second = AssistantController(
        paths=get_paths(),
        config=AppConfig(),
        server_name=f"t-{uuid.uuid4().hex}",
    )
    try:
        assert second.start(show_overlay=False) is False, "a second instance must be refused"
    finally:
        second.shutdown()


def test_shutdown_releases_the_lock(controller: AssistantController) -> None:
    controller.start(show_overlay=False)
    controller.shutdown()
    assert controller.has_lock is False
    assert not controller.paths.lock_file.exists()


def test_activation_request_shows_the_overlay(controller: AssistantController) -> None:
    controller.overlay.hide()
    controller.on_activation_requested()
    assert controller.overlay.isVisible() is True


def test_tray_activation_toggles_the_overlay(controller: AssistantController) -> None:
    before = controller.overlay.isVisible()
    controller.on_tray_activated()
    assert controller.overlay.isVisible() is not before


def test_hotkey_label_is_reported_even_without_windows(controller: AssistantController) -> None:
    assert controller.hotkey.label == "Ctrl+Alt+S"
    assert controller.hotkey.is_registered is False, "registration is Windows-only"


def test_database_failure_degrades_gracefully(app_home: Path, qapp, monkeypatch) -> None:
    from shraddha.ui import app as app_module

    def explode(*args, **kwargs):
        raise OSError("disk is full")

    monkeypatch.setattr(app_module, "Database", explode, raising=False)
    broken = AssistantController(
        paths=get_paths().ensure(), config=AppConfig(), server_name=f"t-{uuid.uuid4().hex}"
    )
    try:
        assert broken.db is None
        broken.on_submitted("नमस्ते")  # must not raise
        assert broken.overlay.chat.count >= 3
    finally:
        broken.shutdown()


# ------------------------------------------------------------------------- IPC
def test_activation_server_round_trip(qapp) -> None:
    name = f"shraddha-ipc-test-{uuid.uuid4().hex}"
    server = ActivationServer(name)
    received: list[bool] = []
    server.activated.connect(lambda: received.append(True))
    try:
        assert server.start() is True
        assert notify_running_instance(name) is True
        for _ in range(20):
            qapp.processEvents()
            if received:
                break
        assert received == [True]
    finally:
        server.stop()


def test_notify_returns_false_when_nobody_listens(qapp) -> None:
    assert notify_running_instance(f"absent-{uuid.uuid4().hex}") is False
