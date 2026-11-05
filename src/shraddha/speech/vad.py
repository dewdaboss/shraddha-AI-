"""Voice activity detection and utterance segmentation - pure Python, no numpy.

Why not Silero VAD? It needs ONNX Runtime and a model file loaded *while idle*, which is
exactly what the low-memory budget forbids. An RMS gate costs a few thousand integer
operations per second, needs no model, and is accurate enough to know when to *wake* the
recogniser - which is all it has to do, because the recogniser decides the words.

Pipeline::

    mic frames ──▶ EnergyVad (per frame) ──▶ VadSegmenter ──▶ AudioSegment ──▶ ASR

The segmenter keeps a short pre-roll so the first syllable is not clipped, rejects
clicks and doors slamming (``min_speech_ms``), and force-closes an utterance at
``max_utterance_ms`` so a noisy room cannot grow the buffer without bound.
"""

from __future__ import annotations

import math
from array import array
from collections import deque
from dataclasses import dataclass

DEFAULT_FRAME_MS = 20
PRE_ROLL_MS = 200
_INT16_SCALE = 32768.0


@dataclass(frozen=True, slots=True)
class AudioSegment:
    """A captured utterance: raw little-endian int16 mono PCM."""

    pcm: bytes
    sample_rate: int
    duration_s: float
    peak: float

    @property
    def is_empty(self) -> bool:
        return not self.pcm

    def __len__(self) -> int:
        return len(self.pcm)


class EnergyVad:
    """Frame-level speech gate based on normalised RMS energy.

    The noise floor adapts slowly while the frame is quiet, so a fan or a fridge hum
    raises the threshold instead of being mistaken for speech, while a sudden voice
    still passes immediately.
    """

    def __init__(self, threshold: float = 0.02, adapt: float = 0.98) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be within 0..1")
        if not 0.0 <= adapt < 1.0:
            raise ValueError("adapt must be within 0..1")
        self.threshold = threshold
        self.adapt = adapt
        self.noise_floor = threshold
        self.last_rms = 0.0

    @staticmethod
    def rms(frame: bytes) -> float:
        """Normalised RMS of one int16 frame (0.0 - 1.0)."""
        if len(frame) < 2:
            return 0.0
        samples = array("h")
        samples.frombytes(frame[: len(frame) - (len(frame) % 2)])
        if not samples:
            return 0.0
        total = 0
        for value in samples:
            total += value * value
        return math.sqrt(total / len(samples)) / _INT16_SCALE

    @staticmethod
    def peak(frame: bytes) -> float:
        if len(frame) < 2:
            return 0.0
        samples = array("h")
        samples.frombytes(frame[: len(frame) - (len(frame) % 2)])
        return (max(abs(min(samples)), abs(max(samples))) / _INT16_SCALE) if samples else 0.0

    def is_speech(self, frame: bytes) -> bool:
        self.last_rms = self.rms(frame)
        if self.last_rms < self.threshold:
            # Track the room while it is quiet; never let the floor exceed the gate.
            self.noise_floor = self.adapt * self.noise_floor + (1 - self.adapt) * self.last_rms
            return False
        return self.last_rms > max(self.threshold, self.noise_floor * 2.0)

    def reset(self) -> None:
        self.noise_floor = self.threshold
        self.last_rms = 0.0


class VadSegmenter:
    """Turns a frame stream into utterances, one :class:`AudioSegment` at a time."""

    def __init__(
        self,
        vad: EnergyVad,
        sample_rate: int = 16_000,
        frame_ms: int = DEFAULT_FRAME_MS,
        min_speech_ms: int = 250,
        silence_ms: int = 700,
        max_utterance_ms: int = 15_000,
        pre_roll_ms: int = PRE_ROLL_MS,
    ) -> None:
        self.vad = vad
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.min_speech_ms = min_speech_ms
        self.silence_ms = silence_ms
        self.max_utterance_ms = max_utterance_ms

        pre_roll_frames = max(0, pre_roll_ms // max(1, frame_ms))
        self._pre_roll: deque[bytes] = deque(maxlen=pre_roll_frames or 1)
        self._frames: list[bytes] = []
        self._in_speech = False
        self._speech_ms = 0
        self._silence_ms = 0
        self._peak = 0.0

    @property
    def frame_samples(self) -> int:
        return self.sample_rate * self.frame_ms // 1000

    @property
    def frame_bytes(self) -> int:
        return self.frame_samples * 2

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def feed(self, frame: bytes) -> AudioSegment | None:
        """Push one frame. Returns a segment when an utterance just ended."""
        if not frame:
            return None

        speech = self.vad.is_speech(frame)
        if not speech:
            self._pre_roll.append(frame)

        if not self._in_speech:
            if not speech:
                return None
            # Speech just started: prepend the pre-roll so we keep the onset.
            self._in_speech = True
            self._speech_ms = 0
            self._silence_ms = 0
            self._peak = 0.0
            self._frames = list(self._pre_roll)
            self._pre_roll.clear()

        self._frames.append(frame)
        self._peak = max(self._peak, self.vad.peak(frame))

        if speech:
            self._speech_ms += self.frame_ms
            self._silence_ms = 0
        else:
            self._silence_ms += self.frame_ms

        total_ms = len(self._frames) * self.frame_ms
        if self._silence_ms >= self.silence_ms or total_ms >= self.max_utterance_ms:
            return self._close()
        return None

    def flush(self) -> AudioSegment | None:
        """Close the utterance in progress (microphone stopped or user released)."""
        if not self._in_speech:
            self._reset()
            return None
        return self._close()

    def reset(self) -> None:
        self._reset()

    # ----------------------------------------------------------------- internals
    def _close(self) -> AudioSegment | None:
        frames, peak, speech_ms = self._frames, self._peak, self._speech_ms
        self._reset()
        if speech_ms < self.min_speech_ms or not frames:
            return None
        pcm = b"".join(frames)
        return AudioSegment(
            pcm=pcm,
            sample_rate=self.sample_rate,
            duration_s=len(pcm) / 2 / self.sample_rate,
            peak=peak,
        )

    def _reset(self) -> None:
        self._frames = []
        self._in_speech = False
        self._speech_ms = 0
        self._silence_ms = 0
        self._peak = 0.0
