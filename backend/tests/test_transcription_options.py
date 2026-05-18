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
    TRANSCRIPTION_OPTIONS,
    ModelOption,
    is_valid_option,
    normalize_model,
    normalize_provider,
    options_response,
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
    assert is_valid_option("dictation_live_stt", "elevenlabs", "scribe_v2_realtime")
    assert is_valid_option("recording_live_stt", "deepgram", "nova-3")
    assert is_valid_option("file_stt", "soniox", "stt-async-v4")
    assert is_valid_option("dictation_post_filter", "openai", "gpt-5.5")


def test_is_valid_option_normalizes_input() -> None:
    assert is_valid_option("dictation_live_stt", "ELEVENLABS", " scribe_v2_realtime ")
    assert is_valid_option("file_stt", "DeepGram", "nova-3")


def test_is_valid_option_rejects_unknown() -> None:
    assert not is_valid_option("dictation_live_stt", "elevenlabs", "scribe_v1")
    assert not is_valid_option("file_stt", "openai", "whisper-1")
    # Provider not in the realtime pool
    assert not is_valid_option("dictation_live_stt", "soniox", "stt-async-v4")


def test_is_valid_option_realtime_pool_shared_between_groups() -> None:
    """dictation_live_stt and recording_live_stt share the same option pool."""
    for option in TRANSCRIPTION_OPTIONS["dictation_live_stt"]:
        assert is_valid_option("recording_live_stt", option.provider, option.model)


# ---------------------------------------------------------------------------
# validate_option
# ---------------------------------------------------------------------------


def test_validate_option_returns_normalized() -> None:
    provider, model = validate_option("dictation_live_stt", "  ELEVENLABS  ", "scribe_v2_realtime")
    assert provider == "elevenlabs"
    assert model == "scribe_v2_realtime"


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


def test_options_response_realtime_groups_have_same_pool() -> None:
    out = options_response()
    assert out["dictation_live_stt"] == out["recording_live_stt"]


def test_options_response_at_least_three_file_stt_options() -> None:
    out = options_response()
    assert len(out["file_stt"]) >= 3
