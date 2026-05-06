"""Inworld AI realtime STT integration.

Inworld exposes a unified WebSocket endpoint that fans out to multiple
underlying STT engines (`inworld/inworld-stt-1`, `soniox/stt-rt-v4`,
`assemblyai/u3-rt-pro`, etc.) selected via the `transcribe_config.model_id`
field of the first WebSocket message. We use `soniox/stt-rt-v4` for
dictation — best-in-class on Russian per Soniox's published multilingual
benchmarks (human-parity across 60+ languages, semantic endpoint detection,
backward-compatible with v3).

Authentication is HTTP Basic over a base64-encoded `<id>:<secret>` pair
held in a single `INWORLD_API_KEY` env var. Per Inworld docs the WebSocket
accepts the same credential as a `?key=Basic+<base64>` query parameter for
clients that cannot inject custom headers — but our Swift client uses
URLSessionWebSocketTask with proper headers, so we mint a session payload
with the credential and let the client construct its own connect.

We do NOT cache the credential client-side; the backend issues short-lived
session payloads on demand. JWT-based mint can be added later if compliance
needs it.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from urllib.parse import urlencode

INWORLD_STT_WS_URL = "wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional"


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


def normalise_inworld_credential(raw: str) -> str:
    """Return a base64 string suitable for the `Authorization: Basic ...` header.

    Accepts either a `id:secret` pair or an already-base64-encoded value.
    Raises ValueError if the input cannot be coerced into a valid Basic
    credential.
    """
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("Inworld API key is empty")

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


def build_session(
    *,
    api_key: str,
    model_id: str = "soniox/stt-rt-v4",
    language: str = "multi",
    sample_rate: int = 16_000,
    channels: int = 1,
) -> InworldSttSession:
    """Mint an Inworld realtime STT session payload for the Swift client.

    The Swift client uses the auth_header value with URLSessionWebSocketTask
    and sends an initial `transcribe_config` message with the supplied
    parameters.
    """
    base64_key = normalise_inworld_credential(api_key)
    auth_header = f"Basic {base64_key}"

    # Inworld accepts BCP-47 language codes (`en-US`, `ru`) and "multi" for
    # auto-detect. Soniox v4 RT supports the common BCP-47 set.
    resolved_language = language.strip() or "multi"

    return InworldSttSession(
        auth_header=auth_header,
        websocket_url=INWORLD_STT_WS_URL,
        model_id=model_id.strip(),
        language=resolved_language,
        audio_encoding="LINEAR16",
        sample_rate_hertz=sample_rate,
        number_of_channels=max(1, channels),
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
