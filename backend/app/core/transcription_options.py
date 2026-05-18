"""Curated transcription and dictation processing settings.

Two scenarios, two model pools:

- **Realtime** populates both ``dictation_live_stt`` and ``recording_live_stt``
  from a single curated list. The mechanics are identical (streaming audio in,
  text deltas out); dictation is just a shorter session.
- **Batch** populates ``file_stt`` for uploaded audio.

Hard language filter: every realtime/batch option here covers at least 50
languages out of the box. English-only or 6-language models are intentionally
excluded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TranscriptionOptionGroup = Literal[
    "dictation_live_stt",
    "recording_live_stt",
    "file_stt",
    "dictation_post_filter",
]


DEFAULT_DICTATION_LIVE_STT_PROVIDER = "elevenlabs"
DEFAULT_DICTATION_LIVE_STT_MODEL = "scribe_v2_realtime"
DEFAULT_RECORDING_LIVE_STT_PROVIDER = "elevenlabs"
DEFAULT_RECORDING_LIVE_STT_MODEL = "scribe_v2_realtime"
DEFAULT_FILE_STT_PROVIDER = "elevenlabs"
DEFAULT_FILE_STT_MODEL = "scribe_v2"
DEFAULT_DICTATION_POST_FILTER_PROVIDER = "openai"
DEFAULT_DICTATION_POST_FILTER_MODEL = "gpt-5.5"


@dataclass(frozen=True)
class ModelOption:
    provider: str
    model: str
    label: str
    description: str

    def as_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "label": self.label,
            "description": self.description,
        }


_REALTIME_OPTIONS: tuple[ModelOption, ...] = (
    ModelOption(
        provider="elevenlabs",
        model="scribe_v2_realtime",
        label="ElevenLabs Scribe v2 Realtime",
        description="Default. 90+ languages, 150 ms latency, 32-speaker diarization.",
    ),
    ModelOption(
        provider="deepgram",
        model="nova-3",
        label="Deepgram Nova-3 (also works for files)",
        description="50+ languages, sub-300 ms streaming, code-switching, smart format.",
    ),
    ModelOption(
        provider="inworld",
        model="soniox/stt-rt-v4",
        label="Soniox v4 Realtime",
        description="60+ languages, 5-hour sessions, semantic end-of-turn detection.",
    ),
    ModelOption(
        provider="openai",
        model="gpt-realtime-whisper",
        label="OpenAI GPT Realtime Whisper",
        description="Whisper-family language coverage, low-latency streaming.",
    ),
)


TRANSCRIPTION_OPTIONS: dict[TranscriptionOptionGroup, tuple[ModelOption, ...]] = {
    "dictation_live_stt": _REALTIME_OPTIONS,
    "recording_live_stt": _REALTIME_OPTIONS,
    "file_stt": (
        ModelOption(
            provider="elevenlabs",
            model="scribe_v2",
            label="ElevenLabs Scribe v2",
            description="Default. 90+ languages, 48-speaker diarization, word timestamps.",
        ),
        ModelOption(
            provider="deepgram",
            model="nova-3",
            label="Deepgram Nova-3 (also works for realtime)",
            description="50+ languages, smart format + diarization in batch.",
        ),
        ModelOption(
            provider="soniox",
            model="stt-async-v4",
            label="Soniox v4 Async",
            description="60+ languages, full-audio-context diarization, up to 5-hour files.",
        ),
    ),
    "dictation_post_filter": (
        ModelOption(
            provider="openai",
            model="gpt-5.5",
            label="OpenAI GPT-5.5",
            description="Default cleanup model for dictated text.",
        ),
    ),
}


def normalize_provider(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("provider cannot be empty")
    return normalized


def normalize_model(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("model cannot be empty")
    return normalized


def is_valid_option(group: TranscriptionOptionGroup, provider: str, model: str) -> bool:
    normalized_provider = normalize_provider(provider)
    normalized_model = normalize_model(model)
    return any(
        option.provider == normalized_provider and option.model == normalized_model
        for option in TRANSCRIPTION_OPTIONS[group]
    )


def validate_option(group: TranscriptionOptionGroup, provider: str, model: str) -> tuple[str, str]:
    normalized_provider = normalize_provider(provider)
    normalized_model = normalize_model(model)
    if not is_valid_option(group, normalized_provider, normalized_model):
        raise ValueError(f"Unsupported {group} option: {normalized_provider}/{normalized_model}")
    return normalized_provider, normalized_model


def options_response() -> dict[str, list[dict[str, str]]]:
    return {
        group: [option.as_dict() for option in options]
        for group, options in TRANSCRIPTION_OPTIONS.items()
    }
