"""Voice-activity detection and utterance segmentation.

The VAD is the gatekeeper for the whole pipeline: it decides *when* the ASR is allowed
to run, which is what keeps idle RAM low. These tests use synthetic frames, so they need
no microphone and no model.
"""

from __future__ import annotations

import struct

import pytest

from shraddha.speech.vad import AudioSegment, EnergyVad, VadSegmenter

SAMPLE_RATE = 16_000
FRAME_MS = 20


def speech(ms: int = FRAME_MS, amplitude: int = 8000) -> bytes:
    """A loud, clearly voiced frame."""
    samples = SAMPLE_RATE * ms // 1000
    return struct.pack(f"<{samples}h", *([amplitude, -amplitude] * (samples // 2)))


def silence(ms: int = FRAME_MS) -> bytes:
    samples = SAMPLE_RATE * ms // 1000
    return b"\x00\x00" * samples


@pytest.fixture()
def segmenter() -> VadSegmenter:
    return VadSegmenter(
        vad=EnergyVad(threshold=0.02),
        sample_rate=SAMPLE_RATE,
        frame_ms=FRAME_MS,
        min_speech_ms=200,
        silence_ms=100,
        max_utterance_ms=2000,
    )


# --------------------------------------------------------------------------- VAD
def test_rms_of_silence_is_zero() -> None:
    assert EnergyVad.rms(silence()) == pytest.approx(0.0)


def test_rms_of_full_scale_tone_is_near_one() -> None:
    assert EnergyVad.rms(speech(amplitude=32000)) > 0.9


def test_rms_tolerates_empty_and_odd_length_frames() -> None:
    assert EnergyVad.rms(b"") == 0.0
    assert EnergyVad.rms(b"\x01") == 0.0


def test_speech_and_silence_are_classified() -> None:
    vad = EnergyVad(threshold=0.02)
    assert vad.is_speech(speech()) is True
    assert vad.is_speech(silence()) is False


def test_a_quiet_hum_sits_below_the_gate() -> None:
    vad = EnergyVad(threshold=0.1)
    hum = speech(amplitude=200)  # about 0.006 normalised
    assert vad.is_speech(hum) is False


def test_peak_tracks_the_loudest_sample() -> None:
    assert EnergyVad.peak(speech(amplitude=16000)) == pytest.approx(16000 / 32768, rel=0.01)
    assert EnergyVad.peak(silence()) == 0.0


@pytest.mark.parametrize("threshold", [-0.1, 1.1])
def test_threshold_is_validated(threshold: float) -> None:
    with pytest.raises(ValueError):
        EnergyVad(threshold=threshold)


def test_reset_restores_the_noise_floor() -> None:
    vad = EnergyVad(threshold=0.02)
    vad.is_speech(silence(200))
    vad.noise_floor = 0.5
    vad.reset()
    assert vad.noise_floor == pytest.approx(0.02)
    assert vad.last_rms == 0.0


# ---------------------------------------------------------------------- segmenter
def test_a_full_utterance_becomes_one_segment(segmenter: VadSegmenter) -> None:
    produced: list[AudioSegment] = []
    for _ in range(15):  # 300 ms of speech
        produced += [segment for segment in [segmenter.feed(speech())] if segment]
    assert produced == [], "must wait for the trailing silence"

    for _ in range(5):  # 100 ms of silence closes the utterance
        produced += [segment for segment in [segmenter.feed(silence())] if segment]

    assert len(produced) == 1
    segment = produced[0]
    assert segment.sample_rate == SAMPLE_RATE
    assert 0.2 <= segment.duration_s <= 0.55
    assert segment.peak > 0.2


def test_a_click_shorter_than_min_speech_is_ignored(segmenter: VadSegmenter) -> None:
    for _ in range(3):  # 60 ms - a door, not a sentence
        assert segmenter.feed(speech()) is None
    for _ in range(20):
        assert segmenter.feed(silence()) is None
    assert segmenter.in_speech is False


def test_max_utterance_cuts_a_long_monologue(segmenter: VadSegmenter) -> None:
    produced = None
    for _ in range(200):  # 4 s of continuous speech, cap is 2 s
        produced = segmenter.feed(speech())
        if produced is not None:
            break
    assert produced is not None
    assert produced.duration_s >= 1.5


def test_flush_closes_an_utterance_without_silence(segmenter: VadSegmenter) -> None:
    for _ in range(20):
        segmenter.feed(speech())
    segment = segmenter.flush()
    assert segment is not None
    assert segment.duration_s >= 0.35
    assert segmenter.in_speech is False


def test_flush_without_speech_returns_nothing(segmenter: VadSegmenter) -> None:
    segmenter.feed(silence())
    assert segmenter.flush() is None


def test_pre_roll_keeps_the_onset_of_the_word(segmenter: VadSegmenter) -> None:
    for _ in range(3):
        segmenter.feed(silence())
    for _ in range(15):
        segmenter.feed(speech())
    for _ in range(5):
        segment = segmenter.feed(silence())
        if segment is not None:
            break
    assert segment is not None
    # 15 speech frames plus the 3 kept from the pre-roll (200 ms window at 20 ms each).
    assert len(segment.pcm) > 15 * len(speech())


def test_reset_clears_a_partial_utterance(segmenter: VadSegmenter) -> None:
    for _ in range(10):
        segmenter.feed(speech())
    assert segmenter.in_speech is True
    segmenter.reset()
    assert segmenter.in_speech is False
    assert segmenter.flush() is None


def test_empty_frames_are_ignored(segmenter: VadSegmenter) -> None:
    assert segmenter.feed(b"") is None


def test_frame_geometry_matches_the_sample_rate(segmenter: VadSegmenter) -> None:
    assert segmenter.frame_samples == 320
    assert segmenter.frame_bytes == 640
    assert len(speech()) == segmenter.frame_bytes
