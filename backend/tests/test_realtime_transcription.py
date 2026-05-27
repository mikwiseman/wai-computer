"""Tests for the active realtime transcription runtime."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from jose import jwt

from app.config import get_settings
from app.core.deepgram import build_realtime_websocket_url
from app.core.realtime_transcription import (
    REALTIME_PROXY_AUDIENCE,
    RealtimeTranscriptionProxyClaims,
    UnsupportedRealtimeLanguageError,
    _build_deepgram_realtime_session,
    build_deepgram_realtime_url_from_proxy_claims,
    create_realtime_transcription_session,
    decode_realtime_proxy_token,
)

DEEPGRAM_REALTIME_MODEL = "nova-3"


@pytest.mark.asyncio
async def test_create_realtime_transcription_session_uses_deepgram_recording_defaults():
    with patch(
        "app.core.realtime_transcription.require_deepgram_api_key",
        return_value="provider_key",
    ):
        session = await create_realtime_transcription_session(language="multi", channels=1)

    assert session.provider == "deepgram"
    assert session.expires_in_seconds == 60
    assert session.sample_rate == 16_000
    assert session.audio_format == "linear16"
    assert session.language == "multi"
    assert session.channels == 1
    assert session.model == DEEPGRAM_REALTIME_MODEL
    assert session.keep_alive_interval_seconds == 4
    assert session.commit_strategy is None
    assert session.no_verbatim is False
    assert session.websocket_url == "ws://localhost:8000/api/transcription/stream"
    assert session.auth_scheme == "bearer"
    claims = decode_realtime_proxy_token(session.token)
    assert claims.language == "multi"
    assert claims.model == DEEPGRAM_REALTIME_MODEL
    provider_url = build_realtime_websocket_url(
        language=claims.language,
        channels=claims.channels,
        purpose=claims.purpose,
        model=claims.model,
    )
    assert "smart_format=true" in provider_url
    assert "interim_results=true" in provider_url
    assert "utterances=true" in provider_url
    assert "endpointing=100" in provider_url


@pytest.mark.asyncio
async def test_create_realtime_transcription_session_ignores_user_recording_choice():
    user = type(
        "User",
        (),
        {
            "recording_live_stt_provider": "removed-live-provider",
            "recording_live_stt_model": "removed-live-model",
        },
    )()

    with patch(
        "app.core.realtime_transcription.require_deepgram_api_key",
        return_value="provider_key",
    ):
        session = await create_realtime_transcription_session(
            language="ru-RU",
            channels=2,
            purpose="recording",
            user=user,
        )

    assert session.provider == "deepgram"
    assert session.model == DEEPGRAM_REALTIME_MODEL
    assert session.language == "ru"
    assert session.channels == 1
    assert session.auth_scheme == "bearer"
    claims = decode_realtime_proxy_token(session.token)
    provider_url = build_realtime_websocket_url(
        language=claims.language,
        channels=claims.channels,
        purpose=claims.purpose,
        model=claims.model,
    )
    assert "endpointing=300" in provider_url
    assert "numerals=true" in provider_url


@pytest.mark.asyncio
async def test_create_dictation_session_adds_english_dictation_params():
    with patch(
        "app.core.realtime_transcription.require_deepgram_api_key",
        return_value="provider_key",
    ):
        session = await create_realtime_transcription_session(
            language="en-US",
            channels=1,
            purpose="dictation",
        )

    assert session.provider == "deepgram"
    assert session.model == DEEPGRAM_REALTIME_MODEL
    claims = decode_realtime_proxy_token(session.token)
    provider_url = build_realtime_websocket_url(
        language=claims.language,
        channels=claims.channels,
        purpose=claims.purpose,
        model=claims.model,
    )
    assert "dictation=true" in provider_url
    assert "punctuate=true" in provider_url
    assert "numerals=true" in provider_url
    assert "utterances=true" not in provider_url


@pytest.mark.asyncio
async def test_create_dictation_session_skips_english_only_dictation_for_multi():
    with patch(
        "app.core.realtime_transcription.require_deepgram_api_key",
        return_value="provider_key",
    ):
        session = await create_realtime_transcription_session(
            language="   ",
            channels=1,
            purpose="dictation",
        )

    assert session.language == "multi"
    claims = decode_realtime_proxy_token(session.token)
    provider_url = build_realtime_websocket_url(
        language=claims.language,
        channels=claims.channels,
        purpose=claims.purpose,
        model=claims.model,
    )
    assert "dictation=true" not in provider_url
    assert "punctuate=true" not in provider_url
    assert "numerals=true" in provider_url
    assert "endpointing=100" in provider_url


@pytest.mark.asyncio
async def test_build_deepgram_realtime_session_requires_api_key():
    with patch(
        "app.core.realtime_transcription.require_deepgram_api_key",
        side_effect=ValueError("DEEPGRAM_API_KEY not configured"),
    ):
        with pytest.raises(ValueError, match="DEEPGRAM_API_KEY not configured"):
            await _build_deepgram_realtime_session(
                "ru",
                1,
                model=DEEPGRAM_REALTIME_MODEL,
                purpose="recording",
                subject="user",
                websocket_url="ws://localhost:8000/api/transcription/stream",
            )


@pytest.mark.asyncio
async def test_build_deepgram_realtime_session_rejects_unsupported_language():
    with pytest.raises(UnsupportedRealtimeLanguageError):
        await _build_deepgram_realtime_session(
            "zz-TEST",
            1,
            model=DEEPGRAM_REALTIME_MODEL,
            purpose="recording",
            subject="user",
            websocket_url="ws://localhost:8000/api/transcription/stream",
        )


@pytest.mark.asyncio
async def test_create_realtime_transcription_session_rejects_non_deepgram_runtime():
    with patch(
        "app.core.realtime_transcription.validate_option",
        return_value=("removed-provider", "removed-model"),
    ):
        with pytest.raises(
            ValueError,
            match="Unsupported recording_live_stt_provider: removed-provider",
        ):
            await create_realtime_transcription_session(language="multi")


def test_realtime_transcription_router_exposes_only_session_mint_endpoint():
    """Live STT is a backend-minted proxy path, not provider fallback routing."""
    from app.api.routes.realtime_transcription import router

    route_paths = {getattr(route, "path", None) for route in router.routes}

    assert route_paths == {"/transcription/session", "/transcription/stream"}


def _encode_proxy_payload(overrides: dict[str, object]) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "sub": "user",
        "aud": REALTIME_PROXY_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(seconds=60),
        "language": "ru",
        "channels": 1,
        "model": DEEPGRAM_REALTIME_MODEL,
        "purpose": "dictation",
    }
    payload.update(overrides)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"sub": ""}, "subject"),
        ({"language": ""}, "language"),
        ({"model": ""}, "model"),
        ({"purpose": "invalid"}, "purpose"),
        ({"channels": 0}, "channels"),
    ],
)
def test_decode_realtime_proxy_token_rejects_invalid_claims(
    overrides: dict[str, object],
    message: str,
):
    token = _encode_proxy_payload(overrides)

    with pytest.raises(ValueError, match=message):
        decode_realtime_proxy_token(token)


def test_decode_realtime_proxy_token_rejects_invalid_signature():
    with pytest.raises(ValueError, match="Invalid realtime transcription token"):
        decode_realtime_proxy_token("not-a-jwt")


def test_build_deepgram_realtime_url_from_proxy_claims_uses_claims():
    url = build_deepgram_realtime_url_from_proxy_claims(
        RealtimeTranscriptionProxyClaims(
            subject="user",
            language="ru",
            channels=1,
            model=DEEPGRAM_REALTIME_MODEL,
            purpose="recording",
        )
    )

    assert "model=nova-3" in url
    assert "language=ru" in url
    assert "utterances=true" in url
