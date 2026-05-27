"""Tests for app.core.transcription_options."""

from __future__ import annotations

import pytest

from app.core.transcription_options import (
    DEFAULT_DICTATION_LIVE_STT_MODEL,
    DEFAULT_DICTATION_LIVE_STT_PROVIDER,
    DEFAULT_DICTATION_POST_FILTER_MODEL,
    DEFAULT_DICTATION_POST_FILTER_PROVIDER,
    DEFAULT_FILE_STT_MODEL,
    DEFAULT_FILE_STT_PROVIDER,
    DEFAULT_RECORDING_LIVE_STT_MODEL,
    DEFAULT_RECORDING_LIVE_STT_PROVIDER,
    ModelOption,
    is_valid_option,
    normalize_model,
    normalize_provider,
    options_response,
    provider_is_configured,
    validate_configured_option,
    validate_option,
)

# ---------------------------------------------------------------------------
# ModelOption
# ---------------------------------------------------------------------------


def test_model_option_as_dict_returns_all_fields() -> None:
    opt = ModelOption(
        provider="elevenlabs", model="scribe_v2", label="Scribe v2",
        description="Default file STT",
    )
    assert opt.as_dict() == {
        "provider": "elevenlabs",
        "model": "scribe_v2",
        "label": "Scribe v2",
        "description": "Default file STT",
    }


def test_model_option_is_frozen_dataclass() -> None:
    """Defensive: catch accidental @dataclass without frozen=True."""
    opt = ModelOption(provider="p", model="m", label="L", description="d")
    with pytest.raises((AttributeError, Exception)):  # FrozenInstanceError subclass
        opt.provider = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Default constants point at registered options
# ---------------------------------------------------------------------------


def test_defaults_are_registered_options() -> None:
    pairs = [
        ("dictation_live_stt",
         DEFAULT_DICTATION_LIVE_STT_PROVIDER, DEFAULT_DICTATION_LIVE_STT_MODEL),
        ("recording_live_stt",
         DEFAULT_RECORDING_LIVE_STT_PROVIDER, DEFAULT_RECORDING_LIVE_STT_MODEL),
        ("file_stt",
         DEFAULT_FILE_STT_PROVIDER, DEFAULT_FILE_STT_MODEL),
        ("dictation_post_filter",
         DEFAULT_DICTATION_POST_FILTER_PROVIDER, DEFAULT_DICTATION_POST_FILTER_MODEL),
    ]
    for group, provider, model in pairs:
        assert is_valid_option(group, provider, model), \
            f"Default {provider}/{model} for {group} is not in TRANSCRIPTION_OPTIONS"


def test_default_stt_model_set_matches_stable_release_choice() -> None:
    assert (DEFAULT_DICTATION_LIVE_STT_PROVIDER, DEFAULT_DICTATION_LIVE_STT_MODEL) == (
        "openai",
        "gpt-realtime-whisper",
    )
    assert (DEFAULT_RECORDING_LIVE_STT_PROVIDER, DEFAULT_RECORDING_LIVE_STT_MODEL) == (
        "openai",
        "gpt-realtime-whisper",
    )
    assert (DEFAULT_FILE_STT_PROVIDER, DEFAULT_FILE_STT_MODEL) == (
        "elevenlabs",
        "scribe_v2",
    )


# ---------------------------------------------------------------------------
# normalize_provider / normalize_model
# ---------------------------------------------------------------------------


def test_normalize_provider_lowercases_and_trims() -> None:
    assert normalize_provider("  OpenAI  ") == "openai"
    assert normalize_provider("ElevenLabs") == "elevenlabs"


def test_normalize_provider_rejects_empty() -> None:
    with pytest.raises(ValueError, match="provider cannot be empty"):
        normalize_provider("   ")
    with pytest.raises(ValueError, match="provider cannot be empty"):
        normalize_provider("")


def test_normalize_model_trims_but_preserves_case() -> None:
    """Model strings are case-sensitive (gpt-5.5 != GPT-5.5)."""
    assert normalize_model("  gpt-5.5  ") == "gpt-5.5"
    assert normalize_model("Scribe_v2") == "Scribe_v2"


def test_normalize_model_rejects_empty() -> None:
    with pytest.raises(ValueError, match="model cannot be empty"):
        normalize_model("")
    with pytest.raises(ValueError, match="model cannot be empty"):
        normalize_model("   ")


# ---------------------------------------------------------------------------
# is_valid_option
# ---------------------------------------------------------------------------


def test_is_valid_option_matches_registered() -> None:
    assert is_valid_option("dictation_live_stt", "openai", "gpt-realtime-whisper")
    assert is_valid_option("recording_live_stt", "openai", "gpt-realtime-whisper")
    assert is_valid_option("file_stt", "elevenlabs", "scribe_v2")
    assert is_valid_option("dictation_post_filter", "openai", "gpt-5.5")


def test_is_valid_option_normalizes_input() -> None:
    assert is_valid_option("dictation_live_stt", "OPENAI", " gpt-realtime-whisper ")
    assert is_valid_option("file_stt", "ElevenLabs", "scribe_v2")


def test_is_valid_option_rejects_unknown() -> None:
    assert not is_valid_option("dictation_live_stt", "elevenlabs", "scribe_v1")
    assert not is_valid_option("file_stt", "openai", "whisper-1")
    # Provider not in the realtime pool
    assert not is_valid_option("dictation_live_stt", "soniox", "stt-async-v4")
    assert not is_valid_option("dictation_live_stt", "legacy-live", "legacy-model")


def test_realtime_pools_are_task_specific() -> None:
    """Dictation and recording are locked to the same fixed realtime model."""
    assert is_valid_option("dictation_live_stt", "openai", "gpt-realtime-whisper")
    assert is_valid_option("recording_live_stt", "openai", "gpt-realtime-whisper")
    assert not is_valid_option("recording_live_stt", "deepgram", "nova-3")
    assert not is_valid_option("dictation_live_stt", "deepgram", "nova-3")
    assert not is_valid_option("dictation_live_stt", "soniox", "stt-rt-v4")
    assert not is_valid_option("recording_live_stt", "soniox", "stt-rt-v4")
    assert not is_valid_option("file_stt", "deepgram", "nova-3")


# ---------------------------------------------------------------------------
# validate_option
# ---------------------------------------------------------------------------


def test_validate_option_returns_normalized() -> None:
    provider, model = validate_option("dictation_live_stt", "  OPENAI  ", "gpt-realtime-whisper")
    assert provider == "openai"
    assert model == "gpt-realtime-whisper"


def test_validate_option_raises_for_unknown() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        validate_option("file_stt", "openai", "whisper-1")


def test_validate_option_rejects_empty_provider() -> None:
    with pytest.raises(ValueError, match="provider cannot be empty"):
        validate_option("dictation_live_stt", "", "any")


def test_validate_option_rejects_empty_model() -> None:
    with pytest.raises(ValueError, match="model cannot be empty"):
        validate_option("dictation_live_stt", "elevenlabs", "")


# ---------------------------------------------------------------------------
# options_response
# ---------------------------------------------------------------------------


def test_options_response_returns_all_four_groups() -> None:
    out = options_response()
    assert set(out.keys()) == {
        "dictation_live_stt",
        "recording_live_stt",
        "file_stt",
        "dictation_post_filter",
    }


def test_options_response_each_entry_is_dict_with_required_fields() -> None:
    out = options_response()
    for group, entries in out.items():
        assert isinstance(entries, list), f"{group} must be a list for API response"
        for entry in entries:
            assert {"provider", "model", "label", "description"}.issubset(entry.keys())
            # All values are strings (no leaked None/int)
            for value in entry.values():
                assert isinstance(value, str)


def test_options_response_stt_groups_are_fixed() -> None:
    out = options_response()
    assert out["dictation_live_stt"] == [
        {
            "provider": "openai",
            "model": "gpt-realtime-whisper",
            "label": "OpenAI GPT Realtime Whisper",
            "description": "Fixed streaming speech-to-text model for live dictation.",
        }
    ]
    assert out["recording_live_stt"] == [
        {
            "provider": "openai",
            "model": "gpt-realtime-whisper",
            "label": "OpenAI GPT Realtime Whisper",
            "description": "Fixed streaming speech-to-text model for live recording.",
        }
    ]


def test_options_response_file_stt_only_fixed_model() -> None:
    out = options_response()
    assert out["file_stt"] == [
        {
            "provider": "elevenlabs",
            "model": "scribe_v2",
            "label": "ElevenLabs Scribe v2",
            "description": "Fixed file transcription model with diarization.",
        }
    ]


def test_provider_is_configured_checks_required_key_names() -> None:
    settings = type(
        "Settings",
        (),
        {
            "elevenlabs_api_key": "xi-key",
            "openai_api_key": "",
            "deepgram_api_key": "dg-key",
            "soniox_api_key": "soniox-key",
        },
    )()

    assert provider_is_configured("elevenlabs", settings)
    assert provider_is_configured("deepgram", settings)
    assert provider_is_configured("soniox", settings)
    assert not provider_is_configured("openai", settings)
    assert not provider_is_configured("unknown", settings)


def test_options_response_filters_unconfigured_providers() -> None:
    settings = type(
        "Settings",
        (),
        {
            "elevenlabs_api_key": "xi-key",
            "openai_api_key": "",
            "deepgram_api_key": "dg-key",
            "soniox_api_key": "",
        },
    )()

    out = options_response(settings=settings, configured_only=True)

    assert out["dictation_live_stt"] == []
    assert out["recording_live_stt"] == []
    assert {entry["provider"] for entry in out["file_stt"]} == {"elevenlabs"}
    assert out["dictation_post_filter"] == []


def test_validate_configured_option_rejects_missing_provider_key() -> None:
    settings = type(
        "Settings",
        (),
        {
            "elevenlabs_api_key": "",
            "openai_api_key": "",
            "deepgram_api_key": "",
            "soniox_api_key": "",
        },
    )()

    with pytest.raises(ValueError, match="not configured"):
        validate_configured_option(
            "dictation_live_stt",
            "openai",
            "gpt-realtime-whisper",
            settings=settings,
        )


def test_validate_configured_option_returns_valid_configured_option() -> None:
    settings = type(
        "Settings",
        (),
        {
            "elevenlabs_api_key": "xi-key",
            "openai_api_key": "sk-test",
            "deepgram_api_key": "",
            "soniox_api_key": "",
        },
    )()

    assert validate_configured_option(
        "file_stt",
        " ElevenLabs ",
        "scribe_v2",
        settings=settings,
    ) == ("elevenlabs", "scribe_v2")
