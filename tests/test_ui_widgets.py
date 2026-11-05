"""Qt widget tests. Skipped automatically when PySide6 is not installed.

These run on the ``minimal`` platform plugin in headless CI, so they exercise real Qt
widget construction, layout, signals and painting - but not a compositor, a GPU or a
font stack with Devanagari coverage.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from shraddha.ui.chat import ChatView, MessageBubble
from shraddha.ui.icons import (
    app_icon,
    app_pixmap,
    close_pixmap,
    mic_pixmap,
    send_pixmap,
    stop_pixmap,
)
from shraddha.ui.overlay import AssistantOverlay
from shraddha.ui.tray import TrayController

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture()
def overlay(qapp) -> Iterator[AssistantOverlay]:
    window = AssistantOverlay(hotkey_label="Ctrl+Alt+S")
    yield window
    window.hide()
    window.deleteLater()


# --------------------------------------------------------------------- overlay
def test_overlay_geometry_and_identity(overlay: AssistantOverlay) -> None:
    assert overlay.objectName() == "Overlay"
    assert overlay.width() >= overlay.minimumWidth()
    assert overlay.height() >= overlay.minimumHeight()


def test_overlay_is_frameless_tool_window(overlay: AssistantOverlay) -> None:
    flags = overlay.windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.Tool, "a tool window stays out of the taskbar"
    assert flags & Qt.WindowType.WindowStaysOnTopHint


def test_overlay_has_the_documented_controls(overlay: AssistantOverlay) -> None:
    assert overlay.text_input.objectName() == "Input"
    assert overlay.mic_button.isCheckable()
    assert overlay.status_dot.state == "idle"
    assert overlay.chat.count == 0


def test_appending_messages_populates_the_chat(overlay: AssistantOverlay) -> None:
    overlay.append_message("नमस्ते", "assistant")
    overlay.append_message("समय क्या है?", "user")
    assert overlay.chat.messages == [("assistant", "नमस्ते"), ("user", "समय क्या है?")]


def test_input_submits_trimmed_text(overlay: AssistantOverlay) -> None:
    received: list[str] = []
    overlay.submitted.connect(received.append)
    overlay.submit_text("  समय क्या है?  ")
    assert received == ["समय क्या है?"]
    assert overlay.text_input.text() == "", "the field must clear after sending"


def test_empty_input_does_not_submit(overlay: AssistantOverlay) -> None:
    received: list[str] = []
    overlay.submitted.connect(received.append)
    overlay.submit_text("   ")
    assert received == []


def test_send_button_enabled_only_with_text(overlay: AssistantOverlay) -> None:
    from PySide6.QtWidgets import QPushButton

    send = overlay.findChild(QPushButton, "SendButton")
    assert send is not None
    assert send.isEnabled() is False
    overlay.text_input.setText("नमस्ते")
    assert send.isEnabled() is True
    overlay.text_input.setText("   ")
    assert send.isEnabled() is False


def test_listening_state_updates_ui_without_emitting(overlay: AssistantOverlay) -> None:
    emitted: list[bool] = []
    overlay.mic_toggled.connect(emitted.append)
    overlay.set_listening(True)
    assert overlay.mic_button.isChecked() is True
    assert overlay.status_dot.state == "listening"
    assert emitted == [], "programmatic state changes must not echo back as user input"

    overlay.set_listening(False)
    assert overlay.mic_button.isChecked() is False
    assert overlay.status_dot.state == "idle"


def test_mic_button_emits_toggle_and_animates_only_while_listening(
    overlay: AssistantOverlay,
) -> None:
    emitted: list[bool] = []
    overlay.mic_toggled.connect(emitted.append)
    overlay.mic_button.setChecked(True)
    assert emitted == [True]
    assert overlay.mic_button.is_animating is True

    overlay.mic_button.setChecked(False)
    assert emitted == [True, False]
    assert overlay.mic_button.is_animating is False, "idle assistant must not animate"


def test_escape_hides_the_overlay(overlay: AssistantOverlay) -> None:
    overlay.show_overlay()
    assert overlay.isVisible() is True
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    overlay.keyPressEvent(event)
    assert overlay.isVisible() is False


def test_show_and_hide_are_idempotent(overlay: AssistantOverlay) -> None:
    overlay.show_overlay()
    overlay.show_overlay()
    assert overlay.isVisible() is True
    overlay.hide_overlay()
    overlay.hide_overlay()
    assert overlay.isVisible() is False


def test_toggle_round_trips(overlay: AssistantOverlay) -> None:
    overlay.toggle()
    assert overlay.isVisible() is True
    overlay.toggle()
    assert overlay.isVisible() is False


def test_clear_chat(overlay: AssistantOverlay) -> None:
    overlay.append_message("a", "assistant")
    overlay.clear_chat()
    assert overlay.chat.count == 0


def test_hotkey_hint_is_displayed(overlay: AssistantOverlay) -> None:
    from PySide6.QtWidgets import QLabel

    hint = overlay.findChild(QLabel, "Hint")
    assert hint is not None
    assert hint.text() == "CTRL+ALT+S"
    overlay.set_hint("ctrl+shift+space")
    assert hint.text() == "CTRL+SHIFT+SPACE", "the hint chip shows the active hotkey"


def test_status_text_can_be_changed(overlay: AssistantOverlay) -> None:
    from PySide6.QtWidgets import QLabel

    subtitle = overlay.findChild(QLabel, "Subtitle")
    assert subtitle is not None
    overlay.set_status("परीक्षण")
    assert subtitle.text() == "परीक्षण"


# ------------------------------------------------------------------------ chat
def test_chat_trims_old_bubbles(qapp) -> None:
    chat = ChatView(max_bubbles=3)
    for index in range(6):
        chat.add_message(f"m{index}", "assistant")
    assert chat.count == 3
    assert [text for _, text in chat.messages] == ["m3", "m4", "m5"]


def test_bubble_roles_are_validated() -> None:
    with pytest.raises(ValueError, match="unknown message role"):
        MessageBubble("text", "robot")


def test_chat_last_message(qapp) -> None:
    chat = ChatView()
    assert chat.last_message() is None
    chat.add_message("a", "user")
    assert chat.last_message() == ("user", "a")


def test_chat_labels_are_plain_text(qapp) -> None:
    chat = ChatView()
    bubble = chat.add_message("<b>not bold</b>", "assistant")
    assert bubble.text == "<b>not bold</b>"


# ------------------------------------------------------------------------ tray
def test_tray_reports_availability(qapp) -> None:
    tray = TrayController("Ctrl+Alt+S")
    # Headless CI and Linux sessions often have no tray; the app must still work.
    assert isinstance(tray.is_available, bool)
    tray.show()
    tray.hide()
    tray.set_listening(True)
    tray.set_listening(False)


# ----------------------------------------------------------------------- icons
def test_icons_render(qapp) -> None:
    assert not app_pixmap(64).isNull()
    assert not mic_pixmap(22).isNull()
    assert not send_pixmap(20).isNull()
    assert not close_pixmap(16).isNull()
    assert not stop_pixmap(18).isNull()
    assert not app_icon(256).isNull()


def test_app_icon_has_multiple_sizes(qapp) -> None:
    icon = app_icon(256)
    assert len(icon.availableSizes()) >= 3, "HiDPI needs more than one bitmap"
