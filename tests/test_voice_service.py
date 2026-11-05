"""The voice pipeline, driven without a microphone and without a model.

``VoiceService`` is deliberately synchronous and injectable, so each test can hand it
synthetic frames and a scripted recogniser. That is what makes the real behaviour -
mute, wake gating, error messages, idle unload - testable on a machine with no audio
hardware at all.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from pathlib import Path

import pytest

from shraddha.config import AppConfig
from shraddha.speech.audio import MicrophoneError
from shraddha.speech.engines.base import AsrError, Transcript
from shraddha.speech.service import NO_MODEL_MESSAGE, VoiceService, VoiceState

SAMPLE_RATE = 16_000
FRAME_MS = 20


def speech(ms: int = FRAME_MS, amplitude: int = 8000) -> bytes:
    samples = SAMPLE_RATE * ms // 1000
    return struct.pack(f"<{samples}h", *([amplitude, -amplitude] * (samples // 2)))


def silence(ms: int = FRAME_MS) -> bytes:
    return b"\x00\x00" * (SAMPLE_RATE * ms // 1000)


class FakeCapture:
    """Stands in for ``AudioCapture``: no PortAudio, no device."""

    def __init__(self) -> None:
        self.callback = None
        self.started = 0
        self.stopped = 0

    def start(self, callback) -> None:
        self.callback = callback
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def is_running(self) -> bool:
        return self.started > self.stopped


class FakeRecognizer:
    """Returns scripted transcripts; records load/unload cycles."""

    name = "fake"

    def __init__(self, replies: list[str] | None = None, fail_on: str | None = None) -> None:
        self.replies = list(replies or ["क्रोम खोलो"])
        self.fail_on = fail_on
        self.loaded = False
        self.loads = 0
        self.unloads = 0
        self.closed = False
        self.received: list[bytes] = []

    @property
    def is_loaded(self) -> bool:
        return self.loaded

    def load(self) -> None:
        if self.fail_on == "load":
            raise AsrError("मॉडल लोड नहीं हो सका।", hint="test", code="load_failed")
        self.loads += 1
        self.loaded = True

    def unload(self) -> None:
        self.unloads += 1
        self.loaded = False

    def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        self.received.append(pcm)
        if self.fail_on == "transcribe":
            raise AsrError("पहचान विफल रही।", hint="test", code="decode_failed")
        text = self.replies.pop(0) if self.replies else ""
        return Transcript(text=text, engine="fake", duration_s=len(pcm) / 2 / sample_rate)

    def close(self) -> None:
        self.closed = True
        self.loaded = False


@pytest.fixture()
def config() -> AppConfig:
    cfg = AppConfig()
    cfg.asr.engine = "none"  # models come from the injected factory, never the disk
    cfg.asr.min_speech_ms = 200
    cfg.asr.silence_ms = 100
    cfg.asr.max_utterance_ms = 5000
    cfg.asr.idle_unload_s = 120
    cfg.wake.mode = "push_to_talk"
    return cfg


class Clock:
    """A hand-cranked monotonic clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def capture() -> FakeCapture:
    return FakeCapture()


@pytest.fixture()
def recognizer() -> FakeRecognizer:
    return FakeRecognizer()


@pytest.fixture()
def clock() -> Clock:
    return Clock()


@pytest.fixture()
def service(config, capture, recognizer, clock) -> Iterator[VoiceService]:
    instance = VoiceService(
        config=config,
        models_dir=Path("/nonexistent"),
        capture_factory=lambda: capture,
        recognizer_factory=lambda: recognizer,
        clock=clock,
    )
    yield instance
    instance.close()


def say(service: VoiceService, speech_frames: int = 15, silence_frames: int = 8) -> list:
    """Speak one short utterance and let the VAD close it."""
    events = []
    for _ in range(speech_frames):
        events += service.feed(speech())
    for _ in range(silence_frames):
        events += service.feed(silence())
    return events


def kinds(events) -> list[str]:
    return [event.kind for event in events]


# ------------------------------------------------------------------- listening
def test_start_opens_the_microphone_and_reports_listening(service, capture) -> None:
    events = service.start()

    assert service.state is VoiceState.LISTENING
    assert service.is_listening is True
    assert capture.started == 1
    assert "state" in kinds(events)


def test_start_is_idempotent(service, capture) -> None:
    service.start()
    service.start()
    assert capture.started == 1


def test_the_model_is_loaded_only_when_listening_starts(service, recognizer) -> None:
    assert recognizer.loads == 0
    assert service.is_model_loaded is False

    service.start()
    assert recognizer.loads == 1
    assert service.is_model_loaded is True


def test_a_full_utterance_becomes_a_transcript(service, recognizer) -> None:
    service.start()
    say(service)

    assert service.has_pending_segments is True
    events = service.process_pending()

    assert [event.text for event in events if event.kind == "final"] == ["क्रोम खोलो"]
    assert recognizer.received, "the recogniser must see the captured audio"
    assert service.state is VoiceState.LISTENING


def test_the_recogniser_receives_sixteen_kilohertz_audio(service, recognizer) -> None:
    service.start()
    say(service)
    service.process_pending()
    assert len(recognizer.received[0]) % 2 == 0
    assert len(recognizer.received[0]) >= 15 * len(speech())


def test_silence_produces_no_transcript(service, recognizer) -> None:
    recognizer.replies = [""]
    service.start()
    say(service)
    events = service.process_pending()
    assert "final" not in kinds(events)


def test_frames_are_ignored_before_listening_starts(service) -> None:
    assert service.feed(speech()) == []


def test_stop_closes_the_microphone(service, capture) -> None:
    service.start()
    events = service.stop()

    assert capture.stopped >= 1
    assert service.is_listening is False
    assert service.state is VoiceState.IDLE
    assert "state" in kinds(events)


# ------------------------------------------------------------------- push-to-talk
def test_push_to_talk_selects_the_right_mode(service) -> None:
    service.start_push_to_talk()
    assert service.mode == "push_to_talk"


def test_stopping_flushes_a_half_finished_sentence(service) -> None:
    service.start()
    for _ in range(15):
        service.feed(speech())
    service.stop()
    assert service.has_pending_segments is True, "the last words must not be lost"


# ------------------------------------------------------------------------ mute
def test_muting_stops_the_microphone_and_ignores_audio(service, capture) -> None:
    service.start()
    service.set_muted(True)

    assert service.is_muted is True
    assert service.state is VoiceState.MUTED
    assert capture.stopped >= 1
    assert service.feed(speech()) == [], "a muted microphone must not process audio"


def test_unmuting_reports_ready_again(service) -> None:
    service.start()
    service.set_muted(True)
    events = service.toggle_mute()

    assert service.is_muted is False
    assert service.state is VoiceState.IDLE
    assert ("muted", "unmuted") in [(event.kind, event.text) for event in events]


def test_toggle_mute_flips_each_time(service) -> None:
    assert service.is_muted is False
    service.toggle_mute()
    assert service.is_muted is True
    service.toggle_mute()
    assert service.is_muted is False


def test_starting_while_muted_clears_the_mute(service) -> None:
    service.set_muted(True)
    service.start()
    assert service.is_muted is False


def test_a_stop_phrase_mutes_from_inside_a_transcript(service, recognizer) -> None:
    recognizer.replies = ["मेरी बात सुनना बंद करो"]
    service.start()
    say(service)
    events = service.process_pending()

    assert ("final", "मेरी बात सुनना बंद करो") in [(e.kind, e.text) for e in events]
    assert service.is_muted is True


# ----------------------------------------------------------------- unavailable model
def test_a_missing_model_explains_how_to_get_one(config, capture) -> None:
    service = VoiceService(
        config=config,
        models_dir=Path("/nonexistent"),
        capture_factory=lambda: capture,
        recognizer_factory=lambda: None,
    )
    events = service.start()

    errors = [event for event in events if event.kind == "error"]
    assert errors, "the user must be told, not left guessing"
    assert errors[0].text == NO_MODEL_MESSAGE
    assert errors[0].detail == "no_model"
    assert "fetch_models.py" in errors[0].text
    assert service.state is VoiceState.ERROR
    assert capture.started == 0, "no point opening the microphone without a model"


def test_the_missing_model_is_only_reported_once(config, capture) -> None:
    calls = []

    def factory():
        calls.append(1)

    service = VoiceService(
        config=config, capture_factory=lambda: capture, recognizer_factory=factory
    )
    service.start()
    service.stop()
    service.start()

    assert len(calls) == 1, "a failed build must not be retried on every click"
    service.close()


def test_a_model_that_fails_to_load_is_reported(config, capture) -> None:
    broken = FakeRecognizer(fail_on="load")
    service = VoiceService(
        config=config, capture_factory=lambda: capture, recognizer_factory=lambda: broken
    )
    events = service.start()

    errors = [event for event in events if event.kind == "error"]
    assert errors and "test" in errors[0].text
    assert service.state is VoiceState.ERROR
    service.close()


def test_a_recognition_failure_does_not_kill_the_pipeline(service, recognizer) -> None:
    recognizer.fail_on = "transcribe"
    service.start()
    say(service)
    events = service.process_pending()

    assert "error" in kinds(events)
    assert service.state is VoiceState.ERROR
    assert service.is_listening is True, "the microphone stays open for the next attempt"


# --------------------------------------------------------------- unavailable mic
def test_a_missing_microphone_is_explained(config, recognizer) -> None:
    def no_mic():
        raise MicrophoneError("कोई माइक नहीं मिला", hint="माइक जोड़िए", code="no_device")

    service = VoiceService(
        config=config, capture_factory=no_mic, recognizer_factory=lambda: recognizer
    )
    events = service.start()

    errors = [event for event in events if event.kind == "error"]
    assert errors
    assert "माइक" in errors[0].text
    assert service.state is VoiceState.ERROR
    service.close()


def test_mic_status_is_reported_without_opening_the_device(service) -> None:
    available, reason = service.mic_status()
    assert isinstance(available, bool)
    assert isinstance(reason, str)


def test_voice_can_be_switched_off_in_the_settings(service, config) -> None:
    config.wake.mode = "off"
    service.set_config(config)
    events = service.start()

    assert [event.detail for event in events if event.kind == "error"] == ["wake.mode=off"]
    assert service.is_listening is False


# ------------------------------------------------------------------ wake mode
def test_phrase_mode_ignores_speech_that_does_not_start_with_her_name(
    service, config, recognizer
) -> None:
    config.wake.mode = "phrase"
    service.set_config(config)
    recognizer.replies = ["आज मौसम अच्छा है"]
    service.start("phrase")
    say(service)
    events = service.process_pending()

    assert "ignored" in kinds(events)
    assert "final" not in kinds(events)


def test_phrase_mode_wakes_and_runs_the_trailing_command(service, config, recognizer) -> None:
    config.wake.mode = "phrase"
    service.set_config(config)
    recognizer.replies = ["श्रद्धा, Chrome खोलो।"]
    service.start("phrase")
    say(service)
    events = service.process_pending()

    assert "wake" in kinds(events)
    finals = [event.text for event in events if event.kind == "final"]
    assert finals == ["chrome खोलो"], "the name must not reach the command router"


def test_the_awake_window_accepts_a_follow_up_without_the_name(
    service, config, recognizer, clock
) -> None:
    config.wake.mode = "phrase"
    service.set_config(config)
    recognizer.replies = ["श्रद्धा", "क्रोम खोलो"]
    service.start("phrase")

    say(service)
    first = service.process_pending()
    clock.advance(2.0)  # still inside the 8 s command window
    say(service)
    second = service.process_pending()

    assert "wake" in kinds(first)
    assert "wake" not in kinds(second), "already awake: no second wake needed"
    assert [event.text for event in second if event.kind == "final"] == ["क्रोम खोलो"]


def test_the_awake_window_closes(service, config, recognizer, clock) -> None:
    config.wake.mode = "phrase"
    service.set_config(config)
    recognizer.replies = ["श्रद्धा", "क्रोम खोलो"]
    service.start("phrase")

    say(service)
    service.process_pending()
    clock.advance(60.0)
    say(service)
    events = service.process_pending()

    assert [event.text for event in events if event.kind == "final"] == []


# ---------------------------------------------------------------- idle unloading
def test_the_model_is_unloaded_when_nobody_is_speaking(service, recognizer, clock) -> None:
    service.start()
    say(service)
    service.process_pending()
    service.stop()

    assert service.tick() == []
    clock.advance(200)
    events = service.tick()

    assert ("model_unloaded", "fake") in [(event.kind, event.text) for event in events]
    assert recognizer.unloads == 1
    assert service.is_model_loaded is False


def test_the_model_stays_loaded_while_the_microphone_is_open(service, recognizer, clock) -> None:
    service.start()
    clock.advance(10_000)
    assert service.tick() == []
    assert recognizer.unloads == 0


def test_unloading_can_be_disabled(config, capture, recognizer, clock) -> None:
    config.asr.idle_unload_s = 0
    service = VoiceService(
        config=config,
        capture_factory=lambda: capture,
        recognizer_factory=lambda: recognizer,
        clock=clock,
    )
    service.start()
    service.stop()
    clock.advance(10_000)

    assert service.tick() == []
    assert recognizer.unloads == 0
    service.close()


# ---------------------------------------------------------------------- cleanup
def test_close_releases_everything(service, recognizer) -> None:
    service.start()
    service.close()

    assert recognizer.closed is True
    assert service.is_listening is False
    assert service.state is VoiceState.IDLE


def test_a_changed_configuration_is_applied(service, config) -> None:
    config.wake.mode = "phrase"
    config.asr.vad_threshold = 0.05
    service.set_config(config)

    assert service.mode == "phrase"
    assert service.config.asr.vad_threshold == pytest.approx(0.05)
