"""Inworld AI realtime STT integration.

Inworld supports Basic auth for trusted server-side calls and JWT auth for
client-side/native builds. We never return the long-lived Basic credential to
native apps. The backend derives a short-lived JWT and clients connect with
``Authorization: Bearer <jwt>``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx

INWORLD_STT_WS_URL = "wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional"
INWORLD_API_HOST = "api.inworld.ai"
INWORLD_ENGINE_HOST = "api-engine.inworld.ai"
INWORLD_TOKEN_TTL_SECONDS = 15 * 60


@dataclass(frozen=True)
class InworldSttSession:
    """Realtime STT session payload returned by the backend to a Swift client."""

    auth_header: str  # value for `Authorization` header (e.g. "Basic <base64>")
    websocket_url: str
    model_id: str
    language: str
    audio_encoding: str  # always "LINEAR16" for streaming
    sample_rate_hertz: int
    number_of_channels: int
    expires_in_seconds: int = INWORLD_TOKEN_TTL_SECONDS


def normalise_inworld_credential(raw: str) -> str:
    """Return a base64 string suitable for the `Authorization: Basic ...` header.

    Accepts a `id:secret` pair, an already-base64-encoded value, or the
    `Basic <base64>` header value copied from Inworld docs.
    """
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("Inworld API key is empty")
    if cleaned.lower().startswith("basic "):
        cleaned = cleaned[6:].strip()

    # If the value is already base64, decoding it should yield bytes that
    # contain a colon — that's our heuristic.
    try:
        decoded = base64.b64decode(cleaned, validate=True)
        if b":" in decoded:
            return cleaned
    except (binascii.Error, ValueError):
        pass

    # Otherwise treat as raw `id:secret` and encode it.
    if ":" not in cleaned:
        raise ValueError(
            "Inworld API key must be either base64-encoded or in `id:secret` form"
        )
    return base64.b64encode(cleaned.encode("utf-8")).decode("ascii")


def split_inworld_credential(raw: str) -> tuple[str, str]:
    """Return ``(key, secret)`` from raw or base64 Inworld credentials."""
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("Inworld API key is empty")
    if cleaned.lower().startswith("basic "):
        cleaned = cleaned[6:].strip()

    candidate = cleaned
    try:
        decoded = base64.b64decode(cleaned, validate=True).decode("utf-8")
        if ":" in decoded:
            candidate = decoded
    except (binascii.Error, UnicodeDecodeError, ValueError):
        pass

    if ":" not in candidate:
        raise ValueError(
            "Inworld API key must be either base64-encoded or in `key:secret` form"
        )
    key, secret = candidate.split(":", 1)
    if not key.strip() or not secret.strip():
        raise ValueError("Inworld API key and secret must be non-empty")
    return key.strip(), secret.strip()


def _inworld_datetime(now: datetime | None = None) -> str:
    value = now or datetime.now(UTC)
    return value.strftime("%Y%m%d%H%M%S")


def _signature_key(secret: str, params: list[str]) -> str:
    signature = f"IW1{secret}".encode("utf-8")
    for param in params:
        signature = hmac.new(
            signature,
            param.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    return hmac.new(signature, b"iw1_request", hashlib.sha256).hexdigest()


def build_inworld_jwt_authorization(
    *,
    key: str,
    secret: str,
    now: datetime | None = None,
    nonce: str | None = None,
    engine_host: str = INWORLD_ENGINE_HOST,
) -> str:
    """Build the IW1-HMAC-SHA256 header required to mint a JWT."""
    datetime_value = _inworld_datetime(now)
    nonce_value = nonce or secrets.token_hex(8)
    method = "ai.inworld.engine.WorldEngine/GenerateToken"
    signature = _signature_key(
        secret,
        [
            datetime_value,
            engine_host.replace(":443", ""),
            method,
            nonce_value,
        ],
    )
    return (
        "IW1-HMAC-SHA256 "
        f"ApiKey={key},DateTime={datetime_value},Nonce={nonce_value},Signature={signature}"
    )


@dataclass(frozen=True)
class InworldClientJwt:
    token: str
    expires_in_seconds: int
    session_id: str | None = None


async def mint_client_jwt(
    *,
    api_key: str,
    workspace: str,
) -> InworldClientJwt:
    """Mint a client-safe Inworld JWT from server-side credentials."""
    key, secret = split_inworld_credential(api_key)
    auth_header = build_inworld_jwt_authorization(key=key, secret=secret)
    resources = [workspace.strip()] if workspace.strip() else []
    payload = {"key": key, "resources": resources}

    async with httpx.AsyncClient(base_url=f"https://{INWORLD_API_HOST}", timeout=15.0) as client:
        response = await client.post(
            "/auth/v1/tokens/token:generate",
            headers={
                "Authorization": auth_header,
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                "Inworld JWT mint failed "
                f"status={response.status_code} body={response.text[:512]}"
            )
        body = response.json()

    token = body.get("token") if isinstance(body, dict) else None
    expires_at = body.get("expirationTime") if isinstance(body, dict) else None
    session_id = body.get("sessionId") if isinstance(body, dict) else None
    if not isinstance(token, str) or not token:
        raise RuntimeError("Inworld JWT response missing 'token'")
    if not isinstance(expires_at, str) or not expires_at:
        raise RuntimeError("Inworld JWT response missing 'expirationTime'")
    expiration = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    ttl = int((expiration - datetime.now(UTC)).total_seconds())
    if ttl <= 0:
        raise RuntimeError("Inworld JWT response is already expired")
    return InworldClientJwt(
        token=token,
        expires_in_seconds=ttl,
        session_id=session_id if isinstance(session_id, str) and session_id else None,
    )


def build_session(
    *,
    api_key: str,
    model_id: str = "inworld/inworld-stt-1",
    language: str = "multi",
    sample_rate: int = 16_000,
    channels: int = 1,
    auth_header: str | None = None,
    expires_in_seconds: int = INWORLD_TOKEN_TTL_SECONDS,
) -> InworldSttSession:
    """Mint an Inworld realtime STT session payload for the Swift client.

    The Swift client uses the auth_header value with URLSessionWebSocketTask
    and sends an initial `transcribe_config` message with the supplied
    parameters.
    """
    resolved_auth_header = auth_header
    if resolved_auth_header is None:
        base64_key = normalise_inworld_credential(api_key)
        resolved_auth_header = f"Basic {base64_key}"

    # Inworld accepts BCP-47 language codes (`en-US`, `ru`) and "multi" for
    # auto-detect. Soniox v4 RT supports the common BCP-47 set.
    resolved_language = language.strip() or "multi"

    return InworldSttSession(
        auth_header=resolved_auth_header,
        websocket_url=INWORLD_STT_WS_URL,
        model_id=model_id.strip(),
        language=resolved_language,
        audio_encoding="LINEAR16",
        sample_rate_hertz=sample_rate,
        number_of_channels=max(1, channels),
        expires_in_seconds=expires_in_seconds,
    )


def inline_query_url(session: InworldSttSession) -> str:
    """Return a websocket URL that includes the credential as a query
    parameter — useful for browsers / WebView clients that cannot send
    custom headers. Native macOS clients should prefer the header form.
    """
    params = {
        "key": session.auth_header,
    }
    return f"{session.websocket_url}?{urlencode(params)}"
