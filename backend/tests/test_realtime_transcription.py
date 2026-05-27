"""Tests for the active realtime transcription runtime."""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.deepgram import build_realtime_websocket_url
from app.core.realtime_transcription import (
    RealtimeTranscriptionSession,
    _build_deepgram_realtime_session,
    create_realtime_transcription_session,
)

DEEPGRAM_REALTIME_MODEL = "nova-3"


@pytest.mark.asyncio
async def test_create_realtime_transcription_session_uses_deepgram_recording_defaults():
    with patch(
        "app.core.realtime_transcription.create_temporary_token",
        new=AsyncMock(return_value=("dg_token", 60)),
    ):
        session = await create_realtime_transcription_session(language="multi", channels=1)

    assert session == RealtimeTranscriptionSession(
        provider="deepgram",
        token="dg_token",
        expires_in_seconds=60,
        sample_rate=16_000,
        audio_format="linear16",
        language="multi",
        channels=1,
        model=DEEPGRAM_REALTIME_MODEL,
        keep_alive_interval_seconds=4,
        commit_strategy=None,
        no_verbatim=False,
        websocket_url=build_realtime_websocket_url(
            language="multi",
            channels=1,
            purpose="recording",
            model=DEEPGRAM_REALTIME_MODEL,
        ),
        auth_scheme="bearer",
    )
    assert "smart_format=true" in session.websocket_url
    assert "interim_results=true" in session.websocket_url
    assert "utterances=true" in session.websocket_url
    assert "endpointing=100" in session.websocket_url


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
        "app.core.realtime_transcription.create_temporary_token",
        new=AsyncMock(return_value=("dg_token", 60)),
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
    assert session.token == "dg_token"
    assert session.auth_scheme == "bearer"
    assert "endpointing=300" in session.websocket_url
    assert "numerals=true" in session.websocket_url


@pytest.mark.asyncio
async def test_create_dictation_session_adds_english_dictation_params():
    with patch(
        "app.core.realtime_transcription.create_temporary_token",
        new=AsyncMock(return_value=("dg_token", 60)),
    ):
        session = await create_realtime_transcription_session(
            language="en-US",
            channels=1,
            purpose="dictation",
        )

    assert session.provider == "deepgram"
    assert session.model == DEEPGRAM_REALTIME_MODEL
    assert "dictation=true" in session.websocket_url
    assert "punctuate=true" in session.websocket_url
    assert "numerals=true" in session.websocket_url
    assert "utterances=true" not in session.websocket_url


@pytest.mark.asyncio
async def test_create_dictation_session_skips_english_only_dictation_for_multi():
    with patch(
        "app.core.realtime_transcription.create_temporary_token",
        new=AsyncMock(return_value=("dg_token", 60)),
    ):
        session = await create_realtime_transcription_session(
            language="   ",
            channels=1,
            purpose="dictation",
        )

    assert session.language == "multi"
    assert "dictation=true" not in session.websocket_url
    assert "punctuate=true" not in session.websocket_url
    assert "numerals=true" in session.websocket_url
    assert "endpointing=100" in session.websocket_url


@pytest.mark.asyncio
async def test_build_deepgram_realtime_session_requires_api_key():
    with patch(
        "app.core.realtime_transcription.create_temporary_token",
        new=AsyncMock(side_effect=ValueError("DEEPGRAM_API_KEY not configured")),
    ):
        with pytest.raises(ValueError, match="DEEPGRAM_API_KEY not configured"):
            await _build_deepgram_realtime_session(
                "ru",
                1,
                model=DEEPGRAM_REALTIME_MODEL,
                purpose="recording",
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
    """Live STT is a single backend-minted Deepgram path, not provider proxy routing."""
    from app.api.routes.realtime_transcription import router

    route_paths = {getattr(route, "path", None) for route in router.routes}

    assert route_paths == {"/transcription/session"}
