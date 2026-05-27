"""Realtime transcription session routes and backend provider proxy."""

import asyncio
import inspect
import logging
from time import perf_counter
from typing import Literal

import websockets
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from websockets.exceptions import ConnectionClosed

from app.api.deps import CurrentUser
from app.core.deepgram import require_deepgram_api_key
from app.core.observability import (
    add_sentry_breadcrumb,
    capture_sentry_anomaly,
    capture_sentry_exception,
)
from app.core.realtime_transcription import (
    UnsupportedRealtimeLanguageError,
    build_deepgram_realtime_url_from_proxy_claims,
    create_realtime_transcription_session,
    decode_realtime_proxy_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transcription", tags=["transcription"])


UNAVAILABLE_DETAIL = "Live transcription is temporarily unavailable. Please try again in a moment."
SESSION_MINT_SLOW_THRESHOLD_MS = 2_000
PROXY_ERROR_PAYLOAD = {
    "type": "Error",
    "err_code": "PROVIDER_CONNECTION_FAILED",
    "message": "Live transcription provider connection failed.",
}


class CreateRealtimeTranscriptionSessionRequest(BaseModel):
    language: str = "multi"
    channels: int = Field(default=1, ge=1, le=1)
    purpose: Literal["recording", "dictation"] = "recording"


class RealtimeTranscriptionSessionResponse(BaseModel):
    provider: str
    token: str
    expires_in_seconds: int
    sample_rate: int
    audio_format: str
    language: str
    channels: int
    model: str
    keep_alive_interval_seconds: int | None = None
    commit_strategy: str | None = None
    no_verbatim: bool
    websocket_url: str | None = None
    auth_scheme: str = "bearer"


@router.post("/session", response_model=RealtimeTranscriptionSessionResponse)
async def create_session(
    request: CreateRealtimeTranscriptionSessionRequest,
    http_request: Request,
    user: CurrentUser,
) -> RealtimeTranscriptionSessionResponse:
    """Create a provider-backed realtime speech-to-text session."""
    started_at = perf_counter()
    add_sentry_breadcrumb(
        category="transcription.session",
        message="mint requested",
        data={
            "language": request.language,
            "channels": request.channels,
            "purpose": request.purpose,
        },
    )
    logger.info(
        "creating realtime transcription session user_id=%s language=%s channels=%s purpose=%s",
        user.id,
        request.language,
        request.channels,
        request.purpose,
    )
    try:
        session = await create_realtime_transcription_session(
            language=request.language,
            channels=request.channels,
            purpose=request.purpose,
            user=user,
            websocket_url=_stream_websocket_url(http_request),
        )
    except UnsupportedRealtimeLanguageError as exc:
        latency_ms = round((perf_counter() - started_at) * 1000)
        capture_sentry_anomaly(
            "realtime.session_mint.unsupported_language",
            "Realtime transcription session rejected unsupported language",
            category="transcription.session",
            extras={
                "language": request.language,
                "channels": request.channels,
                "purpose": request.purpose,
                "latency_ms": latency_ms,
                "error_type": type(exc).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported live transcription language.",
        ) from exc
    except ValueError as exc:
        latency_ms = round((perf_counter() - started_at) * 1000)
        capture_sentry_anomaly(
            "realtime.session_mint.failed",
            "Realtime transcription session mint failed",
            category="transcription.session",
            extras={
                "language": request.language,
                "channels": request.channels,
                "purpose": request.purpose,
                "latency_ms": latency_ms,
                "error_type": type(exc).__name__,
            },
        )
        logger.warning(
            "realtime transcription session unavailable user_id=%s reason=%s purpose=%s",
            user.id,
            str(exc),
            request.purpose,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=UNAVAILABLE_DETAIL,
        ) from exc
    except Exception as exc:
        latency_ms = round((perf_counter() - started_at) * 1000)
        capture_sentry_exception(
            exc,
            extras={
                "alert_code": "realtime.session_mint.failed",
                "language": request.language,
                "channels": request.channels,
                "purpose": request.purpose,
                "latency_ms": latency_ms,
            },
        )
        logger.exception(
            "realtime transcription session failed user_id=%s error=%s purpose=%s",
            user.id,
            str(exc),
            request.purpose,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=UNAVAILABLE_DETAIL,
        ) from exc

    latency_ms = round((perf_counter() - started_at) * 1000)
    add_sentry_breadcrumb(
        category="transcription.session",
        message="mint succeeded",
        data={
            "provider": session.provider,
            "model": session.model,
            "language": session.language,
            "purpose": request.purpose,
            "latency_ms": latency_ms,
        },
    )
    if latency_ms >= SESSION_MINT_SLOW_THRESHOLD_MS:
        capture_sentry_anomaly(
            "realtime.session_mint.slow",
            "Realtime transcription session mint latency exceeded threshold",
            category="transcription.session",
            extras={
                "provider": session.provider,
                "model": session.model,
                "language": session.language,
                "purpose": request.purpose,
                "latency_ms": latency_ms,
                "slow_threshold_ms": SESSION_MINT_SLOW_THRESHOLD_MS,
            },
        )
    logger.info(
        "realtime transcription session created user_id=%s provider=%s model=%s purpose=%s",
        user.id,
        session.provider,
        session.model,
        request.purpose,
    )
    return RealtimeTranscriptionSessionResponse(
        provider=session.provider,
        token=session.token,
        expires_in_seconds=session.expires_in_seconds,
        sample_rate=session.sample_rate,
        audio_format=session.audio_format,
        language=session.language,
        channels=session.channels,
        model=session.model,
        keep_alive_interval_seconds=session.keep_alive_interval_seconds,
        commit_strategy=session.commit_strategy,
        no_verbatim=session.no_verbatim,
        websocket_url=session.websocket_url,
        auth_scheme=session.auth_scheme,
    )


@router.websocket("/stream")
async def stream_realtime_transcription(websocket: WebSocket) -> None:
    """Proxy realtime audio frames to Deepgram without exposing the API key."""
    token = _bearer_token(websocket)
    if not token:
        await websocket.close(code=1008)
        return

    try:
        claims = decode_realtime_proxy_token(token)
    except ValueError:
        await websocket.close(code=1008)
        return

    target_url = build_deepgram_realtime_url_from_proxy_claims(claims)
    try:
        deepgram_api_key = require_deepgram_api_key()
    except ValueError:
        await websocket.accept()
        await websocket.send_json(PROXY_ERROR_PAYLOAD)
        await _close_websocket(websocket, code=1011)
        return

    await websocket.accept()
    add_sentry_breadcrumb(
        category="transcription.stream",
        message="proxy opened",
        data={
            "provider": "deepgram",
            "model": claims.model,
            "language": claims.language,
            "purpose": claims.purpose,
        },
    )

    try:
        async with websockets.connect(
            target_url,
            **{
                _websockets_header_kwarg(): {
                    "Authorization": f"Token {deepgram_api_key}",
                }
            },
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            max_size=2 * 1024 * 1024,
        ) as provider:
            upstream = asyncio.create_task(_client_to_provider(websocket, provider))
            downstream = asyncio.create_task(_provider_to_client(websocket, provider))
            done, pending = await asyncio.wait(
                {upstream, downstream},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                if task.cancelled():
                    continue
                exception = task.exception()
                if exception is not None and not isinstance(
                    exception, (WebSocketDisconnect, ConnectionClosed)
                ):
                    raise exception
    except WebSocketDisconnect:
        return
    except ConnectionClosed:
        await _close_websocket(websocket, code=1000)
    except Exception as exc:
        logger.warning(
            "deepgram realtime proxy failed error_type=%s purpose=%s",
            type(exc).__name__,
            claims.purpose,
        )
        capture_sentry_exception(
            exc,
            extras={
                "alert_code": "realtime.stream.failed",
                "provider": "deepgram",
                "model": claims.model,
                "language": claims.language,
                "purpose": claims.purpose,
            },
        )
        try:
            await websocket.send_json(PROXY_ERROR_PAYLOAD)
        except RuntimeError:
            pass
        await _close_websocket(websocket, code=1011)
    else:
        await _close_websocket(websocket, code=1000)


async def _client_to_provider(websocket: WebSocket, provider) -> None:
    while True:
        message = await websocket.receive()
        message_type = message.get("type")
        if message_type == "websocket.disconnect":
            await provider.close()
            return
        if message_type != "websocket.receive":
            continue
        data = message.get("bytes")
        text = message.get("text")
        if data is not None:
            await provider.send(data)
        elif text is not None:
            await provider.send(text)


async def _provider_to_client(websocket: WebSocket, provider) -> None:
    async for message in provider:
        if isinstance(message, bytes):
            await websocket.send_bytes(message)
        else:
            await websocket.send_text(message)


def _bearer_token(websocket: WebSocket) -> str | None:
    authorization = websocket.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


def _stream_websocket_url(request: Request) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto")
    proto = (forwarded_proto or request.url.scheme).split(",", 1)[0].strip().lower()
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
    )
    scheme = "wss" if proto == "https" else "ws"
    return f"{scheme}://{host}/api/transcription/stream"


async def _close_websocket(websocket: WebSocket, *, code: int) -> None:
    try:
        await websocket.close(code=code)
    except RuntimeError:
        pass


def _websockets_header_kwarg() -> str:
    parameters = inspect.signature(websockets.connect).parameters
    if "additional_headers" in parameters:
        return "additional_headers"
    return "extra_headers"
