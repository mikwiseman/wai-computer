"""xAI Text-to-Speech provider client."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.config import get_settings


@dataclass(frozen=True)
class XaiTTSResult:
    audio_bytes: bytes
    content_type: str
    latency_ms: int
    provider_status_code: int
    request_id: str | None


class XaiTTSError(RuntimeError):
    """Provider-visible xAI TTS failure without raw request content."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        provider_status_code: int | None = None,
        provider_error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.provider_status_code = provider_status_code
        self.provider_error_code = provider_error_code


async def synthesize_xai_tts(
    *,
    text: str,
    voice_id: str,
    language: str,
    codec: str,
    sample_rate: int,
    bit_rate: int,
    text_normalization: bool,
) -> XaiTTSResult:
    """Generate speech bytes through xAI's unary TTS endpoint."""
    settings = get_settings()
    if not settings.xai_api_key:
        raise XaiTTSError(
            code="xai_api_key_missing",
            message="xAI API key is not configured.",
        )

    api_base = settings.xai_api_base_url.rstrip("/")
    body = {
        "text": text,
        "voice_id": voice_id,
        "language": language,
        "output_format": {
            "codec": codec,
            "sample_rate": sample_rate,
            "bit_rate": bit_rate,
        },
        "speed": 1.0,
        "text_normalization": text_normalization,
        "optimize_streaming_latency": 0,
    }
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.summary_audio_timeout_seconds) as client:
            response = await client.post(
                f"{api_base}/v1/tts",
                headers={
                    "Authorization": f"Bearer {settings.xai_api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
    except httpx.TimeoutException as exc:
        raise XaiTTSError(
            code="xai_timeout",
            message="xAI text-to-speech timed out.",
        ) from exc
    except httpx.HTTPError as exc:
        raise XaiTTSError(
            code="xai_transport_error",
            message="xAI text-to-speech request failed.",
        ) from exc

    latency_ms = round((time.perf_counter() - started) * 1000)
    request_id = response.headers.get("x-request-id") or response.headers.get("xai-request-id")
    if not 200 <= response.status_code < 300:
        raise XaiTTSError(
            code="xai_http_error",
            message="xAI text-to-speech failed.",
            provider_status_code=response.status_code,
            provider_error_code=_provider_error_code(response),
        )

    if not response.content:
        raise XaiTTSError(
            code="xai_empty_audio",
            message="xAI text-to-speech returned empty audio.",
            provider_status_code=response.status_code,
        )

    content_type = response.headers.get("content-type", "audio/mpeg").split(";")[0].strip()
    return XaiTTSResult(
        audio_bytes=response.content,
        content_type=content_type or "audio/mpeg",
        latency_ms=latency_ms,
        provider_status_code=response.status_code,
        request_id=request_id,
    )


def _provider_error_code(response: httpx.Response) -> str | None:
    try:
        data = response.json()
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    error = data.get("error")
    if isinstance(error, dict):
        code = error.get("code") or error.get("type")
        return str(code)[:128] if code else None
    code = data.get("code")
    return str(code)[:128] if code else None
