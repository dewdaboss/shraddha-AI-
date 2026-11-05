"""The voice pipeline: microphone → VAD → ASR → wake word → transcript.

Deliberately **synchronous**. Audio arrival and model inference are separate calls
(:meth:`VoiceService.feed` and :meth:`VoiceService.process_pending`), so the whole state
machine can be driven frame by frame in a test with no threads, no microphone and no
model. Threading lives one layer up, in :mod:`shraddha.ui.voice`.

Memory policy: the recogniser is created on demand and unloaded after
``asr.idle_unload_s`` of inactivity, so an assistant left in the tray overnight is back
to its idle footprint.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from shraddha.config import AppConfig
from shraddha.logging_setup import get_logger
from shraddha.speech import audio as audio_module
from shraddha.speech.audio import AudioCapture, MicrophoneError
from shraddha.speech.engines import AsrError, OfflineRecognizer, create_recognizer
from shraddha.speech.vad import AudioSegment, EnergyVad, VadSegmenter
from shraddha.speech.wake import WakeWordMatcher, contains_stop_phrase

log = get_logger("voice")

#: How long the assistant stays "awake" after hearing its name, waiting for a command.
COMMAND_WINDOW_S = 8.0

NO_MODEL_MESSAGE = (
    "हिन्दी वाक् मॉडल नहीं मिला, इसलिए मैं सुन नहीं सकती। "
    "टर्मिनल में चलाइए: python scripts/fetch_models.py --set asr-light"
)
NO_MIC_MESSAGE = "माइक्रोफ़ोन उपलब्ध नहीं है, इसलिए आवाज़ से सुनना बंद है।"


class VoiceState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    MUTED = "muted"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class VoiceEvent:
    """Something the UI should show or act on."""

    kind: str
    text: str = ""
    detail: str = ""

    #: kinds: state, partial, final, wake, error, model_loaded, model_unloaded, muted


class VoiceService:
    """Owns the microphone, the VAD and the recogniser lifecycle."""

    def __init__(
        self,
        config: AppConfig | None = None,
        models_dir: Path | None = None,
        capture_factory: Callable[[], AudioCapture] | None = None,
        recognizer_factory: Callable[[], OfflineRecognizer | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or AppConfig()
        self.models_dir = Path(models_dir) if models_dir is not None else None
        self._clock = clock
        self._capture_factory = capture_factory
        self._recognizer_factory = recognizer_factory

        self._capture: AudioCapture | None = None
        self._recognizer: OfflineRecognizer | None = None
        self._recognizer_built = False

        self._vad = EnergyVad(threshold=self.config.asr.vad_threshold)
        self._segmenter = self._make_segmenter()
        self._matcher = WakeWordMatcher(self.config.wake.phrases, self.config.wake.fuzzy_distance)

        self._state = VoiceState.IDLE
        self._muted = False
        self._mode = self.config.wake.mode
        self._pending: deque[AudioSegment] = deque(maxlen=8)
        self._last_activity = self._clock()
        self._awake_until: float | None = None

    # ------------------------------------------------------------------ wiring
    def _make_segmenter(self) -> VadSegmenter:
        asr = self.config.asr
        return VadSegmenter(
            vad=self._vad,
            sample_rate=asr.sample_rate,
            frame_ms=self.config.audio.frame_ms,
            min_speech_ms=asr.min_speech_ms,
            silence_ms=asr.silence_ms,
            max_utterance_ms=asr.max_utterance_ms,
        )

    def _build_capture(self) -> AudioCapture:
        if self._capture_factory is not None:
            return self._capture_factory()
        return AudioCapture(
            device=self.config.asr.device,
            sample_rate=self.config.asr.sample_rate,
            frame_ms=self.config.audio.frame_ms,
        )

    def _build_recognizer(self) -> OfflineRecognizer | None:
        if self._recognizer_factory is not None:
            return self._recognizer_factory()
        model_dir = self.models_dir or self.config.asr.model_dir
        return create_recognizer(
            engine=self.config.asr.engine,
            model_dir=Path(model_dir) if model_dir else None,
            sample_rate=self.config.asr.sample_rate,
            num_threads=self.config.asr.num_threads,
        )

    # ------------------------------------------------------------------- state
    @property
    def state(self) -> VoiceState:
        return self._state

    @property
    def is_muted(self) -> bool:
        return self._muted

    @property
    def is_listening(self) -> bool:
        return self._capture is not None

    @property
    def recognizer_name(self) -> str:
        return self._recognizer.name if self._recognizer is not None else "none"

    @property
    def is_model_loaded(self) -> bool:
        return self._recognizer is not None and self._recognizer.is_loaded

    @property
    def mode(self) -> str:
        return self._mode

    def mic_status(self) -> tuple[bool, str]:
        """Whether audio capture can work right now, and why not."""
        return audio_module.availability()

    # ------------------------------------------------------------------- setup
    def set_config(self, config: AppConfig) -> list[VoiceEvent]:
        self.config = config
        self._vad.threshold = config.asr.vad_threshold
        self._segmenter = self._make_segmenter()
        self._matcher = WakeWordMatcher(config.wake.phrases, config.wake.fuzzy_distance)
        self._mode = config.wake.mode
        return []

    # --------------------------------------------------------------- listening
    def start(self, mode: str | None = None) -> list[VoiceEvent]:
        """Open the microphone. Returns the events to report."""
        if mode:
            self._mode = mode
        if self._mode == "off":
            return [VoiceEvent("error", "आवाज़ से सुनना सेटिंग में बंद है।", detail="wake.mode=off")]

        if self._muted:
            self.set_muted(False)

        if self.is_listening:
            return [self._state_event()]

        events: list[VoiceEvent] = []
        if not self._ensure_recognizer(events):
            self._set_state(VoiceState.ERROR)
            events.append(self._state_event())
            return events

        try:
            capture = self._build_capture()
            capture.start(self.feed)
        except MicrophoneError as exc:
            log.warning("microphone unavailable: %s", exc)
            self._set_state(VoiceState.ERROR)
            events.append(VoiceEvent("error", exc.user_message(), detail=exc.code))
            events.append(self._state_event())
            return events

        self._capture = capture
        self._segmenter.reset()
        self._awake_until = None if self._mode == "phrase" else self._clock() + 1e9
        self._last_activity = self._clock()
        self._set_state(VoiceState.LISTENING)
        events.append(self._state_event())
        log.info("listening started (mode=%s, engine=%s)", self._mode, self.recognizer_name)
        return events

    def start_push_to_talk(self) -> list[VoiceEvent]:
        return self.start(mode="push_to_talk")

    def stop(self) -> list[VoiceEvent]:
        """Close the microphone and flush any utterance in progress."""
        events: list[VoiceEvent] = []
        capture, self._capture = self._capture, None
        if capture is not None:
            capture.stop()
        segment = self._segmenter.flush()
        if segment is not None:
            self._pending.append(segment)
        self._awake_until = None
        self._set_state(VoiceState.MUTED if self._muted else VoiceState.IDLE)
        events.append(self._state_event())
        return events

    def set_muted(self, muted: bool) -> list[VoiceEvent]:
        self._muted = muted
        events: list[VoiceEvent] = []
        if muted and self._capture is not None:
            capture, self._capture = self._capture, None
            capture.stop()
            self._segmenter.reset()
            self._set_state(VoiceState.MUTED)
        elif not muted and self._state == VoiceState.MUTED:
            self._set_state(VoiceState.IDLE)
        events.append(VoiceEvent("muted", "muted" if muted else "unmuted"))
        events.append(self._state_event())
        log.info("microphone %s", "muted" if muted else "unmuted")
        return events

    def toggle_mute(self) -> list[VoiceEvent]:
        return self.set_muted(not self._muted)

    # ------------------------------------------------------------------ audio
    def feed(self, pcm: bytes) -> list[VoiceEvent]:
        """Push captured audio (called from the audio thread). VAD only, never ASR."""
        if self._muted or not pcm or self._capture is None:
            return []
        was_speaking = self._segmenter.in_speech
        segment = self._segmenter.feed(pcm)
        events: list[VoiceEvent] = []
        if segment is not None:
            self._pending.append(segment)
            self._set_state(VoiceState.PROCESSING)
            events.append(self._state_event())
        elif self._segmenter.in_speech and not was_speaking:
            events.append(VoiceEvent("partial", ""))
        return events

    @property
    def has_pending_segments(self) -> bool:
        return bool(self._pending)

    def process_pending(self) -> list[VoiceEvent]:
        """Recognise every queued utterance (worker thread or tests)."""
        events: list[VoiceEvent] = []
        while self._pending:
            segment = self._pending.popleft()
            events.extend(self._recognise(segment))
        return events

    def _recognise(self, segment: AudioSegment) -> list[VoiceEvent]:
        events: list[VoiceEvent] = []
        if self._recognizer is None and not self._ensure_recognizer(events):
            self._set_state(VoiceState.ERROR)
            events.append(self._state_event())
            return events
        if self._recognizer is None:  # pragma: no cover - defensive
            return events

        try:
            transcript = self._recognizer.transcribe(segment.pcm, segment.sample_rate)
        except AsrError as exc:
            log.warning("recognition failed: %s", exc)
            self._set_state(VoiceState.ERROR)
            events.append(VoiceEvent("error", exc.user_message(), detail=exc.code))
            events.append(self._state_event())
            return events

        text = transcript.text.strip()
        self._last_activity = self._clock()
        if not text:
            self._set_state(VoiceState.LISTENING if self._capture else VoiceState.IDLE)
            events.append(self._state_event())
            return events

        events.extend(self._route_transcript(text))
        if self._capture is not None and self._state != VoiceState.MUTED:
            self._set_state(VoiceState.LISTENING)
        else:
            self._set_state(VoiceState.MUTED if self._muted else VoiceState.IDLE)
        events.append(self._state_event())
        return events

    def _route_transcript(self, text: str) -> list[VoiceEvent]:
        """Wake-word gate, then hand the command text to the caller."""
        if contains_stop_phrase(text):
            return [VoiceEvent("final", text), *self.set_muted(True)]

        if self._mode == "phrase" and not self._is_awake():
            match = self._matcher.detect(text)
            if not match.matched:
                log.debug("not addressed to the assistant: %r", text)
                return [VoiceEvent("ignored", text)]
            self._awake_until = self._clock() + COMMAND_WINDOW_S
            events = [VoiceEvent("wake", match.phrase)]
            if match.has_command:
                events.append(VoiceEvent("final", match.command))
            return events

        if self._mode == "phrase":
            # Awake: the user is already talking to us.
            match = self._matcher.detect(text)
            command = match.command if match.has_command else text
            self._awake_until = self._clock() + COMMAND_WINDOW_S
            return [VoiceEvent("final", command)]
        return [VoiceEvent("final", text)]

    def _is_awake(self) -> bool:
        return self._awake_until is not None and self._clock() < self._awake_until

    # -------------------------------------------------------------- lifecycle
    def tick(self) -> list[VoiceEvent]:
        """Housekeeping: unload the model once the assistant has been idle."""
        events: list[VoiceEvent] = []
        if self._recognizer is None or self._capture is not None or self.has_pending_segments:
            return events
        idle_s = self.config.asr.idle_unload_s
        if idle_s <= 0:
            return events
        if self._clock() - self._last_activity >= idle_s:
            self._recognizer.unload()
            events.append(VoiceEvent("model_unloaded", self._recognizer.name))
            log.info("ASR model unloaded after %ss idle", idle_s)
        if self._awake_until is not None and not self._is_awake():
            self._awake_until = None
        return events

    def close(self) -> None:
        self.stop()
        if self._recognizer is not None:
            self._recognizer.close()
            self._recognizer = None
        self._recognizer_built = False
        self._pending.clear()
        self._set_state(VoiceState.IDLE)

    # --------------------------------------------------------------- internals
    def _ensure_recognizer(self, events: list[VoiceEvent]) -> bool:
        if self._recognizer is not None and self._recognizer.is_loaded:
            return True
        if self._recognizer is None:
            if self._recognizer_built:
                events.append(VoiceEvent("error", NO_MODEL_MESSAGE, detail="no_model"))
                return False
            self._recognizer = self._build_recognizer()
            self._recognizer_built = True
            if self._recognizer is None:
                events.append(VoiceEvent("error", NO_MODEL_MESSAGE, detail="no_model"))
                return False
        try:
            self._recognizer.load()
        except AsrError as exc:
            log.warning("model load failed: %s", exc)
            events.append(VoiceEvent("error", exc.user_message(), detail=exc.code))
            return False
        events.append(VoiceEvent("model_loaded", self._recognizer.name))
        return True

    def _set_state(self, state: VoiceState) -> None:
        self._state = state

    def _state_event(self) -> VoiceEvent:
        return VoiceEvent("state", self._state.value)
