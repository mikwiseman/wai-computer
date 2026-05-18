"""Tests covering each provider branch in create_realtime_transcription_session
and the helper builders. Targets app/core/realtime_transcription.py lines
125-130, 155, 216-243, 257, 263, 271."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.realtime_transcription import (
    _build_deepgram_realtime_session,
    _build_inworld_realtime_session,
    create_realtime_transcription_session,
)


# ---------------------------------------------------------------------------
# _build_deepgram_realtime_session
# ---------------------------------------------------------------------------


def test_build_deepgram_realtime_session() -> None:
    """Cover lines 125-130 — the deepgram builder body."""
    fake = SimpleNamespace(
        api_key="dg-key", sample_rate=16000, language="en",
        channels=1, model="nova-3", websocket_url="wss://dg/x",
    )
    with patch(
        "app.core.realtime_transcription.mint_deepgram_realtime_session",
        return_value=fake,
    ):
        session = _build_deepgram_realtime_session(
            model="nova-3", language="en", channels=1,
        )
    assert session.provider == "deepgram"
    assert session.token == "dg-key"
    assert session.websocket_url == "wss://dg/x"
    assert session.audio_format == "linear16_16000"
    assert session.auth_scheme == "token"


# ---------------------------------------------------------------------------
# _build_inworld_realtime_session
# ---------------------------------------------------------------------------


def test_build_inworld_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without INWORLD_API_KEY → raises ValueError (line 155)."""
    monkeypatch.setattr(
        "app.core.realtime_transcription.get_settings",
        lambda: SimpleNamespace(inworld_api_key=""),
    )
    with pytest.raises(ValueError, match="INWORLD_API_KEY"):
        _build_inworld_realtime_session(
            "en", 1, model="soniox/stt-rt-v4",
        )


def test_build_inworld_returns_session_when_key_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inworld builder with API key configured."""
    monkeypatch.setattr(
        "app.core.realtime_transcription.get_settings",
        lambda: SimpleNamespace(inworld_api_key="iw-key"),
    )
    fake_inworld = SimpleNamespace(
        auth_header="Basic abc123",
        websocket_url="wss://iw/x",
        model_id="soniox/stt-rt-v4",
        language="en",
        audio_encoding="LINEAR16",
        sample_rate_hertz=16000,
        number_of_channels=1,
    )
    with patch(
        "app.core.realtime_transcription.build_inworld_session",
        return_value=fake_inworld,
    ):
        session = _build_inworld_realtime_session(
            "en", 1, model="soniox/stt-rt-v4",
        )
    assert session.provider == "inworld"
    assert session.auth_scheme == "basic"
    assert session.websocket_url == "wss://iw/x"


# ---------------------------------------------------------------------------
# create_realtime_transcription_session — dictation provider branches
# ---------------------------------------------------------------------------


def _make_user(
    *, dictation_provider="elevenlabs", dictation_model="scribe_v2_realtime",
    recording_provider="elevenlabs", recording_model="scribe_v2_realtime",
):
    return SimpleNamespace(
        dictation_live_stt_provider=dictation_provider,
        dictation_live_stt_model=dictation_model,
        recording_live_stt_provider=recording_provider,
        recording_live_stt_model=recording_model,
    )


@pytest.mark.asyncio
async def test_dispatch_dictation_elevenlabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover lines 222-238 (elevenlabs dictation branch)."""
    user = _make_user(dictation_provider="elevenlabs",
                       dictation_model="scribe_v2_realtime")
    monkeypatch.setattr(
        "app.core.realtime_transcription._create_elevenlabs_realtime_token",
        AsyncMock(return_value=("el-token", 600)),
    )
    monkeypatch.setattr(
        "app.core.realtime_transcription.get_settings",
        lambda: SimpleNamespace(elevenlabs_no_verbatim=False),
    )
    session = await create_realtime_transcription_session(
        purpose="dictation", user=user,
    )
    assert session.provider == "elevenlabs"
    assert session.token == "el-token"
    assert session.auth_scheme == "query_token"


@pytest.mark.asyncio
async def test_dispatch_dictation_deepgram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover lines 216-221 (deepgram dictation branch)."""
    user = _make_user(dictation_provider="deepgram", dictation_model="nova-3")
    fake = SimpleNamespace(
        api_key="dg", sample_rate=16000, language="en", channels=1,
        model="nova-3", websocket_url="wss://dg/x",
    )
    monkeypatch.setattr(
        "app.core.realtime_transcription.mint_deepgram_realtime_session",
        lambda **kw: fake,
    )
    session = await create_realtime_transcription_session(
        purpose="dictation", user=user,
    )
    assert session.provider == "deepgram"


@pytest.mark.asyncio
async def test_dispatch_dictation_inworld(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover line 243 (inworld dictation branch)."""
    user = _make_user(
        dictation_provider="inworld", dictation_model="soniox/stt-rt-v4",
    )
    monkeypatch.setattr(
        "app.core.realtime_transcription.get_settings",
        lambda: SimpleNamespace(
            inworld_api_key="iw-key",
            elevenlabs_no_verbatim=False,
        ),
    )
    fake_inworld = SimpleNamespace(
        auth_header="Basic abc123",
        websocket_url="wss://iw/x",
        model_id="soniox/stt-rt-v4",
        language="en",
        audio_encoding="LINEAR16",
        sample_rate_hertz=16000,
        number_of_channels=1,
    )
    monkeypatch.setattr(
        "app.core.realtime_transcription.build_inworld_session",
        lambda **kw: fake_inworld,
    )
    session = await create_realtime_transcription_session(
        purpose="dictation", user=user,
    )
    assert session.provider == "inworld"


# ---------------------------------------------------------------------------
# create_realtime_transcription_session — recording branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_recording_deepgram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover line 263 (deepgram recording branch)."""
    user = _make_user(recording_provider="deepgram", recording_model="nova-3")
    fake = SimpleNamespace(
        api_key="dg", sample_rate=16000, language="en", channels=1,
        model="nova-3", websocket_url="wss://dg/x",
    )
    monkeypatch.setattr(
        "app.core.realtime_transcription.mint_deepgram_realtime_session",
        lambda **kw: fake,
    )
    session = await create_realtime_transcription_session(
        purpose="recording", user=user,
    )
    assert session.provider == "deepgram"


@pytest.mark.asyncio
async def test_dispatch_recording_with_no_user_uses_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """user=None → defaults (DEFAULT_RECORDING_LIVE_STT_PROVIDER)."""
    monkeypatch.setattr(
        "app.core.realtime_transcription._create_elevenlabs_realtime_token",
        AsyncMock(return_value=("el", 600)),
    )
    monkeypatch.setattr(
        "app.core.realtime_transcription.get_settings",
        lambda: SimpleNamespace(elevenlabs_no_verbatim=False),
    )
    session = await create_realtime_transcription_session(
        purpose="recording", user=None,
    )
    assert session.provider == "elevenlabs"


@pytest.mark.asyncio
async def test_resolved_language_lower_strip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """language="  EN  " is normalized to "en"."""
    monkeypatch.setattr(
        "app.core.realtime_transcription._create_elevenlabs_realtime_token",
        AsyncMock(return_value=("el", 600)),
    )
    monkeypatch.setattr(
        "app.core.realtime_transcription.get_settings",
        lambda: SimpleNamespace(elevenlabs_no_verbatim=False),
    )
    session = await create_realtime_transcription_session(
        language="  EN  ", purpose="recording", user=None,
    )
    assert session.language == "en"


@pytest.mark.asyncio
async def test_empty_language_falls_back_to_multi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """language="" or whitespace falls back to "multi"."""
    monkeypatch.setattr(
        "app.core.realtime_transcription._create_elevenlabs_realtime_token",
        AsyncMock(return_value=("el", 600)),
    )
    monkeypatch.setattr(
        "app.core.realtime_transcription.get_settings",
        lambda: SimpleNamespace(elevenlabs_no_verbatim=False),
    )
    session = await create_realtime_transcription_session(
        language="   ", purpose="recording", user=None,
    )
    assert session.language == "multi"
