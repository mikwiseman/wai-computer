"""Unit tests for the Inworld realtime STT integration."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.inworld import (
    INWORLD_STT_WS_URL,
    build_session,
    inline_query_url,
    normalise_inworld_credential,
    transcribe_audio_file,
)


def test_normalise_credential_accepts_raw_id_secret() -> None:
    raw = "client_abc:secret_xyz"
    encoded = normalise_inworld_credential(raw)
    decoded = base64.b64decode(encoded).decode("utf-8")
    assert decoded == raw


def test_normalise_credential_passes_through_already_base64() -> None:
    raw = "id:secret"
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    assert normalise_inworld_credential(encoded) == encoded


def test_normalise_credential_rejects_empty() -> None:
    with pytest.raises(ValueError):
        normalise_inworld_credential("   ")


def test_normalise_credential_rejects_plain_string_without_colon() -> None:
    with pytest.raises(ValueError):
        # 32 chars, plausible API token shape but no colon and not valid base64.
        normalise_inworld_credential("not-a-valid-credential-format-x")


def test_build_session_uses_soniox_default_and_basic_auth() -> None:
    session = build_session(api_key="user:pass")

    assert session.websocket_url == INWORLD_STT_WS_URL
    assert session.model_id == "soniox/stt-rt-v4"
    assert session.audio_encoding == "LINEAR16"
    assert session.sample_rate_hertz == 16_000
    assert session.number_of_channels == 1
    assert session.auth_header.startswith("Basic ")
    decoded = base64.b64decode(session.auth_header.removeprefix("Basic ")).decode("utf-8")
    assert decoded == "user:pass"


def test_build_session_honours_overrides() -> None:
    session = build_session(
        api_key="user:pass",
        model_id="inworld/inworld-stt-1",
        language="ru",
        sample_rate=24_000,
        channels=2,
    )
    assert session.model_id == "inworld/inworld-stt-1"
    assert session.language == "ru"
    assert session.sample_rate_hertz == 24_000
    assert session.number_of_channels == 2


def test_build_session_normalises_blank_language_to_multi() -> None:
    session = build_session(api_key="user:pass", language="   ")
    assert session.language == "multi"


def test_inline_query_url_includes_auth_header() -> None:
    session = build_session(api_key="user:pass")
    url = inline_query_url(session)
    assert url.startswith(INWORLD_STT_WS_URL)
    assert "key=Basic" in url


@pytest.mark.asyncio
async def test_transcribe_audio_file_posts_sync_stt_payload() -> None:
    response = httpx.Response(
        200,
        json={
            "transcription": {
                "transcript": "Hello world",
                "is_final": True,
                "word_timestamps": [
                    {"word": "Hello", "start_time_ms": 100, "end_time_ms": 300},
                    {"word": "world", "start_time_ms": 350, "end_time_ms": 700},
                ],
            },
        },
        request=httpx.Request("POST", "https://api.inworld.ai/stt/v1/transcribe"),
    )

    with (
        patch("app.core.inworld.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)) as mock_post,
    ):
        mock_settings.return_value.inworld_api_key = "user:pass"
        results = await transcribe_audio_file(
            b"audio",
            model="inworld/inworld-stt-1",
            language="ru",
            content_type="audio/wav",
            channels=2,
        )

    assert len(results) == 1
    assert results[0].text == "Hello world"
    assert results[0].start_ms == 100
    assert results[0].end_ms == 700
    kwargs = mock_post.await_args.kwargs
    assert kwargs["headers"]["Authorization"].startswith("Basic ")
    payload = kwargs["json"]
    assert payload["transcribe_config"]["model_id"] == "inworld/inworld-stt-1"
    assert payload["transcribe_config"]["language"] == "ru"
    assert payload["transcribe_config"]["audio_encoding"] == "AUTO_DETECT"
    assert payload["transcribe_config"]["number_of_channels"] == 2
    assert payload["audio_data"]["content"] == base64.b64encode(b"audio").decode("ascii")
