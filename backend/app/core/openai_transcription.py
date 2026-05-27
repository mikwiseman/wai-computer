"""OpenAI realtime speech-to-text helpers."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings

OPENAI_API_BASE = "https://api.openai.com"
OPENAI_REALTIME_WS_URL = "wss://api.openai.com/v1/realtime"
OPENAI_REALTIME_SAMPLE_RATE = 24_000
OPENAI_REALTIME_TOKEN_TTL_SECONDS = 60


def _require_api_key() -> str:
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")
    return settings.openai_api_key


def build_realtime_transcription_session_update(
    *,
    model: str,
    language: str,
    turn_detection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the OpenAI realtime transcription session update payload."""
    transcription: dict[str, Any] = {"model": model}
    if language and language != "multi":
        transcription["language"] = language

    return {
        "type": "session.update",
        "session": {
            "type": "transcription",
            "audio": {
                "input": {
                    "format": {
                        "type": "audio/pcm",
                        "rate": OPENAI_REALTIME_SAMPLE_RATE,
                    },
                    "transcription": transcription,
                    "turn_detection": turn_detection,
                }
            },
        },
    }


async def create_realtime_client_secret(*, model: str, language: str) -> str:
    """Create an ephemeral client secret for OpenAI Realtime transcription."""
    api_key = _require_api_key()
    session_update = build_realtime_transcription_session_update(
        model=model,
        language=language,
        turn_detection=None,
    )
    payload = {"session": session_update["session"]}

    async with httpx.AsyncClient(base_url=OPENAI_API_BASE, timeout=15.0) as client:
        response = await client.post(
            "/v1/realtime/client_secrets",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        response.raise_for_status()
        body = response.json()

    value = None
    if isinstance(body, dict):
        client_secret = body.get("client_secret")
        if isinstance(client_secret, dict):
            value = client_secret.get("value")
        if value is None:
            value = body.get("value") or body.get("secret")

    if not isinstance(value, str) or not value:
        raise RuntimeError("OpenAI returned an invalid realtime client secret")
    return value


def realtime_websocket_url() -> str:
    return f"{OPENAI_REALTIME_WS_URL}?intent=transcription"
