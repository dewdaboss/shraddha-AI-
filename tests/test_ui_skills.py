"""Phase 4 through the real controller: typed command -> skill -> Hindi answer.

Qt runs headless (``minimal`` platform). The executor is a recorder, the TTS engine
records instead of speaking, and every OS-level skill is injected, so nothing is armed,
pressed, closed or copied on the machine running the tests.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from shraddha.commands import ActionExecutor
from shraddha.config import AppConfig
from shraddha.paths import get_paths
from shraddha.speech.tts import RecordingTts
from shraddha.ui.app import AssistantController

pytestmark = pytest.mark.usefixtures("qapp")


class Recorder(ActionExecutor):
    """An executor that remembers instead of doing."""

    def __init__(self) -> None:
        self.launched: list[list[str]] = []
        self.volume_calls: list[str] = []
        self.window_calls: list[str] = []
        self.clipboard: list[str] = []
        super().__init__(
            popen=self._popen,
            url_opener=lambda url: True,
            path_opener=lambda path: None,
            volume_control=lambda action: self.volume_calls.append(action) or True,
            window_control=lambda action: self.window_calls.append(action) or True,
            clipboard_write=lambda text: self.clipboard.append(text) or True,
            clipboard_read=lambda: self.clipboard[-1] if self.clipboard else "",
        )

    def _popen(self, argv, **kwargs):
        self.launched.append(list(argv))
        return object()


@pytest.fixture()
def controller(app_home: Path, qapp) -> Iterator[tuple[AssistantController, Recorder, RecordingTts]]:
    executor = Recorder()
    voice = RecordingTts()
    instance = AssistantController(
        paths=get_paths().ensure(),
        config=AppConfig(),
        server_name=f"shraddha-skills-{uuid.uuid4().hex}",
        executor=executor,
        tts_engine=voice,
    )
    yield instance, executor, voice
    instance.shutdown()
    instance.overlay.deleteLater()
    qapp.processEvents()


def last(instance: AssistantController) -> tuple[str, str]:
    return instance.overlay.chat.messages[-1]


# ------------------------------------------------------------------------- timer
def test_a_timer_command_arms_it_and_answers_in_hindi(controller) -> None:
    instance, _executor, _voice = controller

    instance.on_submitted("5 मिनट का टाइमर लगाओ")

    assert last(instance)[0] == "assistant"
    assert "टाइमर" in last(instance)[1]
    assert instance.timer.is_running is True
    instance.timer.cancel()


def test_a_fired_timer_is_announced_in_chat_and_out_loud(controller) -> None:
    instance, _executor, voice = controller
    before = instance.overlay.chat.count

    instance.on_timer_fired("5 मिनट")

    assert instance.overlay.chat.count == before + 1
    role, text = last(instance)
    assert role == "system"
    assert "टाइमर पूरा हुआ" in text
    assert voice.spoken and voice.spoken[-1] == text


def test_a_fired_timer_is_persisted(controller) -> None:
    instance, _executor, _voice = controller
    instance.on_timer_fired("1 मिनट")

    turns = [turn["text"] for turn in instance.db.recent_turns(5)]
    assert any("टाइमर पूरा हुआ" in text for text in turns)


def test_shutdown_cancels_a_pending_timer(app_home: Path, qapp) -> None:
    instance = AssistantController(
        paths=get_paths().ensure(),
        config=AppConfig(),
        server_name=f"shraddha-skills-{uuid.uuid4().hex}",
        executor=Recorder(),
        tts_engine=RecordingTts(),
    )
    instance.on_submitted("10 मिनट का टाइमर लगाओ")
    assert instance.timer.is_running is True

    instance.shutdown()

    assert instance.timer.is_running is False
    instance.overlay.deleteLater()
    qapp.processEvents()


def test_timer_status_and_cancel_commands(controller) -> None:
    instance, _executor, _voice = controller

    instance.on_submitted("5 मिनट का टाइमर लगाओ")
    instance.on_submitted("टाइमर कितना बाकी है")
    assert "चल रहा है" in last(instance)[1]

    instance.on_submitted("टाइमर बंद करो")
    assert "रद्द" in last(instance)[1]
    assert instance.timer.is_running is False


# ------------------------------------------------------------------------- notes
def test_notes_round_trip_through_the_database(controller) -> None:
    instance, _executor, _voice = controller

    instance.on_submitted("नोट लिखो दूध लाना है")
    assert "नोट" in last(instance)[1]

    instance.on_submitted("मेरा नोट पढ़ो")
    assert "दूध लाना है" in last(instance)[1]


def test_clearing_notes_asks_first(controller) -> None:
    instance, _executor, _voice = controller
    instance.on_submitted("नोट लिखो कुछ ज़रूरी")

    instance.on_submitted("नोट साफ़ करो")
    assert "हाँ" in last(instance)[1] or "नहीं" in last(instance)[1]

    instance.on_submitted("नहीं")
    instance.on_submitted("मेरा नोट पढ़ो")
    assert "कुछ ज़रूरी" in last(instance)[1], "declining must keep the note"

    instance.on_submitted("नोट साफ़ करो")
    instance.on_submitted("हाँ")
    instance.on_submitted("मेरा नोट पढ़ो")
    assert "कोई नोट नहीं" in last(instance)[1]


# --------------------------------------------------------------------- clipboard
def test_clipboard_copy_and_read(controller) -> None:
    instance, executor, _voice = controller

    instance.on_submitted("copy karo बैठक 5 बजे")
    assert executor.clipboard == ["बैठक 5 बजे"]

    instance.on_submitted("clipboard kya hai")
    assert "बैठक 5 बजे" in last(instance)[1]


# ------------------------------------------------------------------------ volume
def test_volume_commands_reach_the_skill(controller) -> None:
    instance, executor, _voice = controller

    instance.on_submitted("volume बढ़ाओ")
    instance.on_submitted("volume कम करो")
    assert executor.volume_calls == ["up", "down"]

    instance.on_submitted("volume 60 karo")
    assert "सीधे सेट नहीं" in last(instance)[1]


# ------------------------------------------------------------------------ window
def test_closing_a_window_requires_confirmation(controller) -> None:
    instance, executor, _voice = controller

    instance.on_submitted("window बंद करो")
    assert executor.window_calls == [], "nothing may close before the user agrees"

    instance.on_submitted("हाँ")
    assert executor.window_calls == ["close"]


def test_minimizing_a_window_needs_no_confirmation(controller) -> None:
    instance, executor, _voice = controller

    instance.on_submitted("window छोटा करो")

    assert executor.window_calls == ["minimize"]


# ------------------------------------------------------------------- file search
def test_file_search_uses_the_injected_roots(controller, tmp_path: Path, monkeypatch) -> None:
    from shraddha.commands import actions

    instance, executor, _voice = controller
    root = tmp_path / "Documents"
    root.mkdir()
    (root / "budget-2026.xlsx").write_text("x", encoding="utf-8")
    executor.search_roots = lambda: (root,)
    monkeypatch.setattr(actions, "folder_path", lambda _key: root)

    instance.on_submitted("documents mein budget dhundo")

    assert "budget-2026.xlsx" in last(instance)[1]
    assert executor.launched == [], "searching must never open anything"


# ------------------------------------------------------------------ regressions
def test_existing_commands_still_work(controller) -> None:
    instance, executor, _voice = controller

    instance.on_submitted("क्रोम खोलो")
    assert [command.intent for command in executor.history] == ["app.open"]
    assert "Chrome" in last(instance)[1], "the Phase 2 command flow must be untouched"

    instance.on_submitted("time kya hai")
    assert "बजे" in last(instance)[1] or ":" in last(instance)[1]


def test_the_timer_bridge_survives_shutdown(controller) -> None:
    instance, _executor, _voice = controller
    instance.on_submitted("5 मिनट का टाइमर लगाओ")
    instance.shutdown()
    assert instance.timer.is_running is False
