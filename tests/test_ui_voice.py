"""The Qt bridge: service events in, signals out, on its own thread.

A fake service stands in for the real one, so these tests exercise the wiring - not a
microphone, not a model - and finish in milliseconds.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from shraddha.speech.service import VoiceEvent, VoiceState
from shraddha.ui.voice import VoiceBridge

pytestmark = pytest.mark.usefixtures("qapp")


class FakeService:
    """Duck-typed ``VoiceService``: scripted events, recorded calls."""

    def __init__(self, events: list[VoiceEvent] | None = None) -> None:
        self.mode = "push_to_talk"
        self.state = VoiceState.IDLE
        self.is_muted = False
        self.events = events or []
        self.start_modes: list[str | None] = []
        self.frames: list[bytes] = []
        self.stop_calls = 0
        self.close_calls = 0
        self.ticks = 0
        self.has_pending_segments = False

    def start(self, mode: str | None = None):
        self.start_modes.append(mode)
        self.state = VoiceState.LISTENING
        return [VoiceEvent("state", VoiceState.LISTENING.value), *self.events]

    def stop(self):
        self.stop_calls += 1
        self.state = VoiceState.IDLE
        return [VoiceEvent("state", VoiceState.IDLE.value)]

    def set_muted(self, muted: bool):
        self.is_muted = muted
        return [VoiceEvent("muted", "muted" if muted else "unmuted")]

    def toggle_mute(self):
        return self.set_muted(not self.is_muted)

    def feed(self, pcm: bytes):
        self.frames.append(pcm)
        return []

    def process_pending(self):
        return []

    def tick(self):
        self.ticks += 1
        return []

    def close(self):
        self.close_calls += 1


@pytest.fixture()
def service() -> FakeService:
    return FakeService()


@pytest.fixture()
def bridge(service: FakeService) -> Iterator[VoiceBridge]:
    instance = VoiceBridge(service)  # type: ignore[arg-type]
    yield instance
    instance.stop()


def collect(signal) -> list:
    received: list = []
    signal.connect(received.append)
    return received


# ------------------------------------------------------------------- dispatch
def test_final_transcripts_become_signals(bridge: VoiceBridge) -> None:
    heard = collect(bridge.final)
    bridge._emit_all([VoiceEvent("final", "क्रोम खोलो")])
    assert heard == ["क्रोम खोलो"]


def test_every_event_kind_is_mapped(bridge: VoiceBridge) -> None:
    states = collect(bridge.state_changed)
    partials = collect(bridge.partial)
    errors = collect(bridge.error)
    mutes = collect(bridge.muted)
    loaded = collect(bridge.model_loaded)
    wakes = []
    bridge.wake.connect(lambda: wakes.append(True))

    bridge._emit_all(
        [
            VoiceEvent("state", "listening"),
            VoiceEvent("partial", "क्रो"),
            VoiceEvent("error", "माइक नहीं मिला"),
            VoiceEvent("muted", "muted"),
            VoiceEvent("model_loaded", "vosk"),
            VoiceEvent("wake", "श्रद्धा"),
        ]
    )

    assert states == ["listening"]
    assert partials == ["क्रो"]
    assert errors == ["माइक नहीं मिला"]
    assert mutes == [True]
    assert loaded == ["vosk"]
    assert wakes == [True]


def test_unknown_and_ignored_events_are_harmless(bridge: VoiceBridge) -> None:
    heard = collect(bridge.final)
    bridge._emit_all([VoiceEvent("ignored", "आज मौसम अच्छा है"), VoiceEvent("mystery")])
    assert heard == []


# ------------------------------------------------------------------ pipeline
def test_start_runs_the_service_on_a_worker_thread(bridge: VoiceBridge, service) -> None:
    bridge.start()
    try:
        assert bridge.is_running is True
        assert service.start_modes == ["push_to_talk"]
    finally:
        bridge.stop()

    assert bridge.is_running is False
    assert service.stop_calls >= 1


def test_the_mode_can_be_chosen(bridge: VoiceBridge, service) -> None:
    bridge.start(mode="phrase")
    bridge.stop()
    assert service.start_modes == ["phrase"]


def test_frames_are_queued_and_then_drained(bridge: VoiceBridge) -> None:
    bridge._live = True
    bridge._on_frame(b"pcm")
    assert bridge._frames.qsize() == 1
    bridge._drain_frames()
    assert bridge._frames.qsize() == 0


def test_frames_are_dropped_when_not_live(bridge: VoiceBridge) -> None:
    bridge._on_frame(b"pcm")
    assert bridge._frames.qsize() == 0


def test_stop_without_start_is_safe(bridge: VoiceBridge, service) -> None:
    bridge.stop()
    assert bridge.is_running is False
    assert service.stop_calls == 0


# ---------------------------------------------------------------------- mute
def test_toggle_mute_emits_the_new_state(bridge: VoiceBridge, service) -> None:
    muted = collect(bridge.muted)
    bridge.toggle_mute()
    assert service.is_muted is True
    assert muted == [True]


def test_set_muted_is_idempotent(bridge: VoiceBridge, service) -> None:
    muted = collect(bridge.muted)
    bridge.set_muted(True)
    bridge.set_muted(True)
    assert muted == [True, True]
    assert service.is_muted is True


def test_shutdown_closes_the_service(bridge: VoiceBridge, service) -> None:
    bridge.shutdown()
    assert service.close_calls == 1


def test_state_is_exposed_for_the_ui(bridge: VoiceBridge) -> None:
    assert bridge.state is VoiceState.IDLE
    assert bridge.is_muted is False
