"""Curated transcription and dictation processing settings.

Fixed model slots:

- **Dictation realtime** favours transcription accuracy on natural
  code-switched speech plus streaming live preview: OpenAI
  ``gpt-realtime-whisper`` through the realtime proxy, finalized by manual
  commit on hotkey release.
- **Recording realtime** favours stable long-running streaming, live captions,
  and diarization (Deepgram Nova-3).
- **Batch** populates ``file_stt`` for uploaded audio.
- **Dictation post-filter** is the server-side smart cleanup pass (fillers,
  self-corrections/backtracking, spoken formatting commands); levels live on
  the user (``dictation_cleanup_level``), not in this registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

TranscriptionOptionGroup = Literal[
    "dictation_live_stt",
    "recording_live_stt",
    "file_stt",
    "dictation_post_filter",
]


DEFAULT_DICTATION_LIVE_STT_PROVIDER = "openai"
DEFAULT_DICTATION_LIVE_STT_MODEL = "gpt-realtime-whisper"
DEFAULT_RECORDING_LIVE_STT_PROVIDER = "deepgram"
DEFAULT_RECORDING_LIVE_STT_MODEL = "nova-3"
DEFAULT_FILE_STT_PROVIDER = "elevenlabs"
DEFAULT_FILE_STT_MODEL = "scribe_v2"
DEFAULT_DICTATION_POST_FILTER_PROVIDER = "disabled"
DEFAULT_DICTATION_POST_FILTER_MODEL = "none"


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


_DICTATION_REALTIME_OPTIONS: tuple[ModelOption, ...] = (
    ModelOption(
        provider="openai",
        model="gpt-realtime-whisper",
        label="OpenAI gpt-realtime-whisper",
        description=(
            "Natively streaming OpenAI speech-to-text tuned for dictation: "
            "live word-by-word preview, strong multilingual and mixed-language "
            "accuracy."
        ),
    ),
)

_RECORDING_REALTIME_OPTIONS: tuple[ModelOption, ...] = (
    ModelOption(
        provider="deepgram",
        model="nova-3",
        label="Deepgram Nova-3",
        description="Fixed low-latency streaming speech-to-text model for live recording.",
    ),
)


TRANSCRIPTION_OPTIONS: dict[TranscriptionOptionGroup, tuple[ModelOption, ...]] = {
    "dictation_live_stt": _DICTATION_REALTIME_OPTIONS,
    "recording_live_stt": _RECORDING_REALTIME_OPTIONS,
    "file_stt": (
        ModelOption(
            provider="elevenlabs",
            model="scribe_v2",
            label="ElevenLabs Scribe v2",
            description=(
                "Highest-accuracy batch transcription with speaker diarization "
                "and filler-word removal."
            ),
        ),
        ModelOption(
            provider="deepgram",
            model="nova-3",
            label="Deepgram Nova-3",
            description="Full-session batch transcription with v2 speaker diarization.",
        ),
    ),
    "dictation_post_filter": (),
}

_PROVIDER_KEY_BY_NAME = {
    "deepgram": "deepgram_api_key",
    "elevenlabs": "elevenlabs_api_key",
    "openai": "openai_api_key",
    "cerebras": "cerebras_api_key",
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


def provider_is_configured(provider: str, settings: Any) -> bool:
    """Return whether the provider has the server-side credential it needs.

    The picker is a contract: every provider/model pair exposed to clients must
    be able to mint a real upstream request from this backend environment.
    """
    normalized_provider = normalize_provider(provider)
    key_name = _PROVIDER_KEY_BY_NAME.get(normalized_provider)
    if key_name is None:
        return False
    return bool(str(getattr(settings, key_name, "") or "").strip())


def validate_configured_option(
    group: TranscriptionOptionGroup,
    provider: str,
    model: str,
    *,
    settings: Any,
) -> tuple[str, str]:
    normalized_provider, normalized_model = validate_option(group, provider, model)
    if not provider_is_configured(normalized_provider, settings):
        raise ValueError(
            f"Provider {normalized_provider} is not configured for {group}: "
            f"missing {_PROVIDER_KEY_BY_NAME[normalized_provider]}"
        )
    return normalized_provider, normalized_model


def options_response(
    *,
    settings: Any | None = None,
    configured_only: bool = False,
) -> dict[str, list[dict[str, str]]]:
    return {
        group: [
            option.as_dict()
            for option in options
            if not configured_only
            or settings is not None and provider_is_configured(option.provider, settings)
        ]
        for group, options in TRANSCRIPTION_OPTIONS.items()
    }
