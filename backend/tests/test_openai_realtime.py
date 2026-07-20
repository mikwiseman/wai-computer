"""Tests for the OpenAI realtime transcription session helpers."""

from types import SimpleNamespace

import pytest

from app.core.openai_realtime import (
    OPENAI_REALTIME_MODEL,
    OPENAI_REALTIME_SAMPLE_RATE,
    build_transcription_session_update,
    map_openai_error_code,
    normalize_openai_realtime_language,
    openai_realtime_transcription_delay,
    require_openai_api_key,
)


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> None:
    values = {
        "openai_api_key": "sk-test",
        "openai_realtime_transcription_delay": "high",
        **overrides,
    }
    monkeypatch.setattr(
        "app.core.openai_realtime.get_settings",
        lambda: SimpleNamespace(**values),
    )


def test_require_openai_api_key_returns_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch)
    assert require_openai_api_key() == "sk-test"


def test_require_openai_api_key_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, openai_api_key="   ")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        require_openai_api_key()


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("multi", None),
        ("", None),
        (None, None),
        ("auto", None),
        ("und", None),
        ("ru", "ru"),
        ("EN-US", "en"),
        ("en-us", "en"),
        ("  De  ", "de"),
    ],
)
def test_normalize_openai_realtime_language(language: str | None, expected: str | None) -> None:
    assert normalize_openai_realtime_language(language) == expected


def test_transcription_delay_validates_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, openai_realtime_transcription_delay="xhigh")
    assert openai_realtime_transcription_delay() == "xhigh"

    _patch_settings(monkeypatch, openai_realtime_transcription_delay="warp-speed")
    with pytest.raises(ValueError, match="openai_realtime_transcription_delay"):
        openai_realtime_transcription_delay()


def test_build_session_update_pins_manual_commit_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch)
    payload = build_transcription_session_update(
        model=OPENAI_REALTIME_MODEL,
        language="ru",
    )
    assert payload["type"] == "session.update"
    session = payload["session"]
    assert session["type"] == "transcription"
    audio_input = session["audio"]["input"]
    assert audio_input["format"] == {
        "type": "audio/pcm",
        "rate": OPENAI_REALTIME_SAMPLE_RATE,
    }
    # gpt-realtime-whisper rejects VAD configs; explicit null pins manual commit.
    assert audio_input["turn_detection"] is None
    assert audio_input["noise_reduction"] == {"type": "near_field"}
    assert audio_input["transcription"] == {
        "model": OPENAI_REALTIME_MODEL,
        "language": "ru",
        "delay": "high",
    }


def test_build_session_update_omits_language_for_multi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch)
    payload = build_transcription_session_update(
        model=OPENAI_REALTIME_MODEL,
        language="multi",
    )
    transcription = payload["session"]["audio"]["input"]["transcription"]
    assert "language" not in transcription
    assert transcription["delay"] == "high"


def test_build_session_update_skips_delay_for_other_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch)
    payload = build_transcription_session_update(
        model="some-future-transcribe-model",
        language="en",
    )
    transcription = payload["session"]["audio"]["input"]["transcription"]
    assert "delay" not in transcription


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("invalid_api_key", "authentication_error"),
        ("unauthorized", "authentication_error"),
        ("insufficient_quota", "insufficient_quota"),
        ("rate_limit_exceeded", "rate_limit_exceeded"),
        ("requests_limit_reached", "rate_limit_exceeded"),
        ("invalid_model", "unsupported_model"),
        ("something_else", "something_else"),
        (None, "provider_error"),
        ("", "provider_error"),
    ],
)
def test_map_openai_error_code(code: str | None, expected: str) -> None:
    assert map_openai_error_code(code) == expected
