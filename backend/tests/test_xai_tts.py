"""xAI TTS provider client tests."""

from __future__ import annotations

import httpx
import pytest

from app.core.xai_tts import XaiTTSError, synthesize_xai_tts

pytestmark = pytest.mark.asyncio


async def test_synthesize_xai_tts_posts_expected_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "xai_api_key", "test-xai-key")
    monkeypatch.setattr(settings, "xai_api_base_url", "https://api.x.ai")
    captured: dict = {}
    real_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["json"] = __import__("json").loads(request.content.decode())
        return httpx.Response(
            200,
            headers={"content-type": "audio/mpeg", "x-request-id": "req-1"},
            content=b"ID3",
        )

    transport = httpx.MockTransport(handler)

    def client_factory(*args, **kwargs):
        return real_async_client(transport=transport)

    monkeypatch.setattr("app.core.xai_tts.httpx.AsyncClient", client_factory)

    result = await synthesize_xai_tts(
        text="Hello",
        voice_id="ara",
        language="auto",
        codec="mp3",
        sample_rate=24000,
        bit_rate=128000,
        text_normalization=False,
    )

    assert captured["url"] == "https://api.x.ai/v1/tts"
    assert captured["auth"] == "Bearer test-xai-key"
    assert captured["json"]["voice_id"] == "ara"
    assert captured["json"]["language"] == "auto"
    assert captured["json"]["output_format"] == {
        "codec": "mp3",
        "sample_rate": 24000,
        "bit_rate": 128000,
    }
    assert result.audio_bytes == b"ID3"
    assert result.request_id == "req-1"


async def test_synthesize_xai_tts_surfaces_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "xai_api_key", "test-xai-key")
    real_async_client = httpx.AsyncClient

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            429,
            json={"error": {"code": "rate_limit_exceeded"}},
        )
    )
    monkeypatch.setattr(
        "app.core.xai_tts.httpx.AsyncClient",
        lambda *args, **kwargs: real_async_client(transport=transport),
    )

    with pytest.raises(XaiTTSError) as exc_info:
        await synthesize_xai_tts(
            text="Hello",
            voice_id="ara",
            language="auto",
            codec="mp3",
            sample_rate=24000,
            bit_rate=128000,
            text_normalization=False,
        )

    assert exc_info.value.code == "xai_http_error"
    assert exc_info.value.provider_status_code == 429
    assert exc_info.value.provider_error_code == "rate_limit_exceeded"


async def test_synthesize_xai_tts_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "xai_api_key", "")

    with pytest.raises(XaiTTSError) as exc_info:
        await synthesize_xai_tts(
            text="Hello",
            voice_id="ara",
            language="auto",
            codec="mp3",
            sample_rate=24000,
            bit_rate=128000,
            text_normalization=False,
        )

    assert exc_info.value.code == "xai_api_key_missing"
