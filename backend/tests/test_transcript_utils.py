"""Tests for shared transcript helpers."""

from app.core.transcript_utils import TranscriptResult, detect_wav_channels


def test_detect_wav_channels_returns_stereo_when_header_says_two_channels():
    header = bytearray(44)
    header[:4] = b"RIFF"
    header[8:12] = b"WAVE"
    header[22:24] = (2).to_bytes(2, byteorder="little")

    assert detect_wav_channels(bytes(header)) == 2


def test_detect_wav_channels_defaults_to_mono_for_invalid_header():
    assert detect_wav_channels(b"not-a-wav") == 1


def test_transcript_result_keeps_provider_normalized_fields():
    result = TranscriptResult(
        text="Hello",
        speaker="Speaker 1",
        is_final=True,
        start_ms=100,
        end_ms=400,
        confidence=0.9,
    )

    assert result.text == "Hello"
    assert result.speaker == "Speaker 1"
    assert result.is_final is True
