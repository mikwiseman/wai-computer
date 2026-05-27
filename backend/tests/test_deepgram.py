"""Tests for Deepgram speech-to-text helpers."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.deepgram import (
    build_realtime_websocket_url,
    create_temporary_token,
    normalize_deepgram_language,
)


def test_normalize_deepgram_language_maps_auto_to_multi() -> None:
    assert normalize_deepgram_language(None) == "multi"
    assert normalize_deepgram_language("  ") == "multi"
    assert normalize_deepgram_language("AUTO") == "multi"
    assert normalize_deepgram_language("ru_RU") == "ru"
    assert normalize_deepgram_language("en_GB") == "en-gb"
    assert normalize_deepgram_language("es_MX") == "es"
    assert normalize_deepgram_language("zz-TEST") == "zz-test"


def test_build_realtime_websocket_url_includes_live_best_practice_params() -> None:
    url = build_realtime_websocket_url(
        language="multi",
        channels=1,
        purpose="recording",
    )

    assert url.startswith("wss://api.deepgram.com/v1/listen?")
    assert "model=nova-3" in url
    assert "encoding=linear16" in url
    assert "sample_rate=16000" in url
    assert "language=multi" in url
    assert "interim_results=true" in url
    assert "smart_format=true" in url
    assert "utterance_end_ms=1000" in url
    assert "endpointing=100" in url
    assert "utterances=true" in url


def test_build_realtime_websocket_url_limits_dictation_to_english() -> None:
    english = build_realtime_websocket_url(
        language="en-US",
        channels=1,
        purpose="dictation",
    )
    russian = build_realtime_websocket_url(
        language="ru",
        channels=1,
        purpose="dictation",
    )

    assert "dictation=true" in english
    assert "punctuate=true" in english
    assert "numerals=true" in english
    assert "dictation=true" not in russian
    assert "punctuate=true" not in russian
    assert "numerals=true" in russian


@pytest.mark.asyncio
async def test_create_temporary_token_posts_auth_grant() -> None:
    response = httpx.Response(
        200,
        json={"access_token": "dg_temp", "expires_in": 60},
        request=httpx.Request("POST", "https://api.deepgram.com/v1/auth/grant"),
    )
    post = AsyncMock(return_value=response)

    with patch("app.core.deepgram.get_settings") as mock_settings, patch(
        "httpx.AsyncClient.post",
        new=post,
    ):
        mock_settings.return_value.deepgram_api_key = "dg-key"
        token, expires_in = await create_temporary_token()

    assert token == "dg_temp"
    assert expires_in == 60
    post.assert_awaited_once()
    _, kwargs = post.await_args
    assert kwargs["headers"] == {"Authorization": "Token dg-key"}
    assert kwargs["json"] == {"ttl_seconds": 60}


@pytest.mark.asyncio
async def test_create_temporary_token_requires_key() -> None:
    with patch("app.core.deepgram.get_settings") as mock_settings:
        mock_settings.return_value.deepgram_api_key = ""
        with pytest.raises(ValueError, match="DEEPGRAM_API_KEY not configured"):
            await create_temporary_token()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "message"),
    [
        (["not-a-dict"], "invalid token grant response"),
        ({"access_token": "", "expires_in": 60}, "invalid temporary token"),
        ({"access_token": "dg_temp", "expires_in": 0}, "invalid token expiration"),
    ],
)
async def test_create_temporary_token_rejects_invalid_grant_payloads(
    body: object,
    message: str,
) -> None:
    response = httpx.Response(
        200,
        json=body,
        request=httpx.Request("POST", "https://api.deepgram.com/v1/auth/grant"),
    )
    post = AsyncMock(return_value=response)

    with patch("app.core.deepgram.get_settings") as mock_settings, patch(
        "httpx.AsyncClient.post",
        new=post,
    ):
        mock_settings.return_value.deepgram_api_key = "dg-key"
        with pytest.raises(RuntimeError, match=message):
            await create_temporary_token()
