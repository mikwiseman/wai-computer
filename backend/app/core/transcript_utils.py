"""Shared transcript models and audio helpers."""

from dataclasses import dataclass


@dataclass
class TranscriptResult:
    """Normalized transcript segment returned by speech-to-text providers."""

    text: str
    speaker: str | None
    is_final: bool
    start_ms: int
    end_ms: int
    confidence: float


def detect_wav_channels(audio_data: bytes) -> int:
    """Return the channel count from a WAV header, defaulting to mono."""
    if len(audio_data) < 44:
        return 1
    if audio_data[:4] != b"RIFF" or audio_data[8:12] != b"WAVE":
        return 1
    channels = int.from_bytes(audio_data[22:24], byteorder="little")
    return channels if channels > 0 else 1
