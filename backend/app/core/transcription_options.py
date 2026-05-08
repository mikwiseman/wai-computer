"""Curated transcription and dictation processing settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TranscriptionOptionGroup = Literal[
    "dictation_live_stt",
    "recording_live_stt",
    "file_stt",
    "dictation_post_filter",
]


DEFAULT_DICTATION_LIVE_STT_PROVIDER = "openai"
DEFAULT_DICTATION_LIVE_STT_MODEL = "gpt-realtime-whisper"
DEFAULT_RECORDING_LIVE_STT_PROVIDER = "elevenlabs"
DEFAULT_RECORDING_LIVE_STT_MODEL = "scribe_v2_realtime"
DEFAULT_FILE_STT_PROVIDER = "elevenlabs"
DEFAULT_FILE_STT_MODEL = "scribe_v2"
DEFAULT_DICTATION_POST_FILTER_PROVIDER = "anthropic"
DEFAULT_DICTATION_POST_FILTER_MODEL = "claude-haiku-4-5"


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


TRANSCRIPTION_OPTIONS: dict[TranscriptionOptionGroup, tuple[ModelOption, ...]] = {
    "dictation_live_stt": (
        ModelOption(
            provider="openai",
            model="gpt-realtime-whisper",
            label="OpenAI GPT Realtime Whisper",
            description="Default. Latest OpenAI realtime speech-to-text for low-latency dictation.",
        ),
        ModelOption(
            provider="elevenlabs",
            model="scribe_v2_realtime",
            label="ElevenLabs Scribe v2 Realtime",
            description="Previous stable dictation path.",
        ),
        ModelOption(
            provider="inworld",
            model="soniox/stt-rt-v4",
            label="Inworld + Soniox v4 RT",
            description="Experimental multilingual realtime recognizer.",
        ),
    ),
    "recording_live_stt": (
        ModelOption(
            provider="elevenlabs",
            model="scribe_v2_realtime",
            label="ElevenLabs Scribe v2 Realtime",
            description="Default live recording transcription path.",
        ),
        ModelOption(
            provider="openai",
            model="gpt-realtime-whisper",
            label="OpenAI GPT Realtime Whisper",
            description="OpenAI realtime speech-to-text for live recording transcripts.",
        ),
    ),
    "file_stt": (
        ModelOption(
            provider="elevenlabs",
            model="scribe_v2",
            label="ElevenLabs Scribe v2",
            description="Default full-session and uploaded-file transcription path.",
        ),
        ModelOption(
            provider="openai",
            model="gpt-4o-transcribe",
            label="OpenAI GPT-4o Transcribe",
            description="Higher-accuracy OpenAI speech-to-text for uploaded audio files.",
        ),
        ModelOption(
            provider="openai",
            model="gpt-4o-mini-transcribe",
            label="OpenAI GPT-4o mini Transcribe",
            description="Lower-cost OpenAI speech-to-text for uploaded audio files.",
        ),
    ),
    "dictation_post_filter": (
        ModelOption(
            provider="anthropic",
            model="claude-haiku-4-5",
            label="Claude Haiku 4.5",
            description="Default low-latency cleanup for dictated text.",
        ),
        ModelOption(
            provider="anthropic",
            model="claude-sonnet-4-6",
            label="Claude Sonnet 4.6",
            description="Higher-quality cleanup when latency is less important.",
        ),
        ModelOption(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            label="Claude Sonnet 4",
            description="Pinned Claude 4 Sonnet snapshot.",
        ),
        ModelOption(
            provider="anthropic",
            model="claude-3-5-haiku-20241022",
            label="Claude Haiku 3.5",
            description="Older fast cleanup model.",
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
