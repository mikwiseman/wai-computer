"""Tests covering each provider branch in realtime transcription session minting."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from app.core.realtime_transcription import (
    _build_deepgram_realtime_session,
    _build_inworld_realtime_session,
    _build_soniox_realtime_session,
    create_realtime_transcription_session,
)


def _patch_soniox_mint(
    monkeypatch: pytest.MonkeyPatch,
    *,
    language: str = "multi",
    channels: int = 1,
) -> AsyncMock:
    fake = SimpleNamespace(
        temporary_api_key="sx-temp",
        sample_rate=16000,
        language=language,
        channels=channels,
        model="stt-rt-v4",
        websocket_url="wss://stt-rt.soniox.com/transcribe-websocket",
        expires_in_seconds=60,
    )
    mock = AsyncMock(return_value=fake)
    monkeypatch.setattr(
        "app.core.realtime_transcription.mint_soniox_realtime_session",
        mock,
    )
    return mock


def _patch_inworld_mint(
    monkeypatch: pytest.MonkeyPatch,
    *,
    language: str = "multi",
    channels: int = 1,
) -> None:
    monkeypatch.setattr(
        "app.core.realtime_transcription.get_settings",
        lambda: SimpleNamespace(inworld_api_key="iw-key:iw-secret", inworld_workspace=""),
    )
    monkeypatch.setattr(
        "app.core.realtime_transcription.mint_inworld_client_jwt",
        AsyncMock(return_value=SimpleNamespace(token="iw-jwt", expires_in_seconds=840)),
    )
    monkeypatch.setattr(
        "app.core.realtime_transcription.build_inworld_session",
        lambda **kw: SimpleNamespace(
            auth_header="Bearer iw-jwt",
            websocket_url="wss://iw/x",
            model_id="inworld/inworld-stt-1",
            language=language,
            audio_encoding="LINEAR16",
            sample_rate_hertz=16000,
            number_of_channels=channels,
            expires_in_seconds=840,
        ),
    )


@pytest.mark.asyncio
async def test_build_deepgram_realtime_session() -> None:
    fake = SimpleNamespace(
        access_token="dg-jwt",
        sample_rate=16000,
        language="en",
        channels=1,
        model="nova-3",
        websocket_url="wss://dg/x",
        expires_in_seconds=30,
        keep_alive_interval_seconds=8,
    )
    with patch(
        "app.core.realtime_transcription.mint_deepgram_realtime_session",
        new=AsyncMock(return_value=fake),
    ):
        session = await _build_deepgram_realtime_session(
            model="nova-3", language="en", channels=1,
        )
    assert session.provider == "deepgram"
    assert session.token == "dg-jwt"
    assert session.websocket_url == "wss://dg/x"
    assert session.audio_format == "linear16_16000"
    assert session.auth_scheme == "bearer"
    assert session.expires_in_seconds == 30
    assert session.keep_alive_interval_seconds == 8


@pytest.mark.asyncio
async def test_build_deepgram_realtime_session_uses_backend_proxy_for_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=UUID("11111111-1111-1111-1111-111111111111"))
    monkeypatch.setattr(
        "app.core.realtime_transcription.get_settings",
        lambda: SimpleNamespace(
            deepgram_api_key="dg-key",
            deepgram_realtime_proxy_token_ttl_seconds=600,
            frontend_url="https://wai.computer",
        ),
    )

    session = await _build_deepgram_realtime_session(
        model="flux-general-multi",
        language="ru",
        channels=1,
        user=user,
    )

    assert session.provider == "deepgram"
    assert session.model == "flux-general-multi"
    assert session.auth_scheme == "bearer"
    assert session.expires_in_seconds == 600
    assert session.sample_rate == 16000
    assert session.websocket_url is not None
    assert session.websocket_url.startswith("wss://wai.computer/api/transcription/deepgram-proxy?")
    assert "model=flux-general-multi" in session.websocket_url
    assert "language=ru" in session.websocket_url


@pytest.mark.asyncio
async def test_build_soniox_realtime_session() -> None:
    fake = SimpleNamespace(
        temporary_api_key="sx-temp",
        sample_rate=16000,
        language="ru",
        channels=2,
        model="stt-rt-v4",
        websocket_url="wss://stt-rt.soniox.com/transcribe-websocket",
        expires_in_seconds=60,
    )
    with patch(
        "app.core.realtime_transcription.mint_soniox_realtime_session",
        new=AsyncMock(return_value=fake),
    ):
        session = await _build_soniox_realtime_session(
            model="stt-rt-v4", language="ru", channels=2,
        )
    assert session.provider == "soniox"
    assert session.token == "sx-temp"
    assert session.auth_scheme == "message_api_key"
    assert session.websocket_url == "wss://stt-rt.soniox.com/transcribe-websocket"


@pytest.mark.asyncio
async def test_build_inworld_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.realtime_transcription.get_settings",
        lambda: SimpleNamespace(inworld_api_key="", inworld_workspace=""),
    )
    with pytest.raises(ValueError, match="INWORLD_API_KEY"):
        await _build_inworld_realtime_session(
            "en", 1, model="inworld/inworld-stt-1",
        )


@pytest.mark.asyncio
async def test_build_inworld_returns_bearer_jwt_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.realtime_transcription.get_settings",
        lambda: SimpleNamespace(inworld_api_key="iw-key:iw-secret", inworld_workspace=""),
    )
    fake_jwt = SimpleNamespace(token="iw-jwt", expires_in_seconds=840)
    fake_inworld = SimpleNamespace(
        auth_header="Bearer iw-jwt",
        websocket_url="wss://iw/x",
        model_id="inworld/inworld-stt-1",
        language="en",
        audio_encoding="LINEAR16",
        sample_rate_hertz=16000,
        number_of_channels=1,
        expires_in_seconds=840,
    )
    with (
        patch(
            "app.core.realtime_transcription.mint_inworld_client_jwt",
            new=AsyncMock(return_value=fake_jwt),
        ),
        patch(
            "app.core.realtime_transcription.build_inworld_session",
            return_value=fake_inworld,
        ),
    ):
        session = await _build_inworld_realtime_session(
            "en", 1, model="inworld/inworld-stt-1",
        )
    assert session.provider == "inworld"
    assert session.token == "iw-jwt"
    assert session.auth_scheme == "bearer"
    assert session.websocket_url == "wss://iw/x"


def _make_user(
    *,
    dictation_provider="elevenlabs",
    dictation_model="scribe_v2_realtime",
    recording_provider="elevenlabs",
    recording_model="scribe_v2_realtime",
):
    return SimpleNamespace(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        dictation_live_stt_provider=dictation_provider,
        dictation_live_stt_model=dictation_model,
        recording_live_stt_provider=recording_provider,
        recording_live_stt_model=recording_model,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("elevenlabs", "scribe_v2_realtime"),
        ("deepgram", "flux-general-multi"),
        ("soniox", "stt-rt-v4"),
        ("inworld", "inworld/inworld-stt-1"),
    ],
)
async def test_dispatch_dictation_ignores_saved_model_and_uses_inworld(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    model: str,
) -> None:
    user = _make_user(
        dictation_provider=provider,
        dictation_model=model,
    )
    _patch_inworld_mint(monkeypatch)
    session = await create_realtime_transcription_session(
        purpose="dictation", user=user,
    )
    assert session.provider == "inworld"
    assert session.model == "inworld/inworld-stt-1"
    assert session.auth_scheme == "bearer"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("elevenlabs", "scribe_v2_realtime"),
        ("deepgram", "nova-3"),
        ("soniox", "stt-rt-v4"),
        ("inworld", "inworld/inworld-stt-1"),
    ],
)
async def test_dispatch_recording_ignores_saved_model_and_uses_inworld(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    model: str,
) -> None:
    user = _make_user(
        recording_provider=provider,
        recording_model=model,
    )
    _patch_inworld_mint(monkeypatch)
    session = await create_realtime_transcription_session(
        purpose="recording", user=user,
    )
    assert session.provider == "inworld"
    assert session.model == "inworld/inworld-stt-1"
    assert session.auth_scheme == "bearer"


@pytest.mark.asyncio
async def test_dispatch_recording_with_no_user_uses_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_inworld_mint(monkeypatch)
    session = await create_realtime_transcription_session(
        purpose="recording", user=None,
    )
    assert session.provider == "inworld"
    assert session.auth_scheme == "bearer"


@pytest.mark.asyncio
async def test_dispatch_dictation_with_no_user_uses_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_inworld_mint(monkeypatch)
    session = await create_realtime_transcription_session(
        purpose="dictation", user=None,
    )
    assert session.provider == "inworld"
    assert session.model == "inworld/inworld-stt-1"
    assert session.auth_scheme == "bearer"


@pytest.mark.asyncio
async def test_resolved_language_lower_strip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_inworld_mint(monkeypatch, language="en")
    session = await create_realtime_transcription_session(
        language="  EN  ", purpose="recording", user=None,
    )
    assert session.language == "en"


@pytest.mark.asyncio
async def test_empty_language_falls_back_to_multi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_inworld_mint(monkeypatch)
    session = await create_realtime_transcription_session(
        language="   ", purpose="recording", user=None,
    )
    assert session.language == "multi"
