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

from app.api.deps import CurrentUser, Database
from app.core.deepgram import require_deepgram_api_key
from app.core.observability import (
    add_sentry_breadcrumb,
    capture_sentry_anomaly,
    capture_sentry_exception,
)
from app.core.personalization import load_user_keyterms
from app.core.rate_limit import (
    REALTIME_MINT_SUSTAINED_ALERT,
    check_realtime_session_mint_rate_limit,
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
PROXY_ERROR_MISSING_BEARER = {
    "type": "Error",
    "err_code": "AUTH_MISSING",
    "message": "Realtime transcription requires a bearer token.",
}
PROXY_ERROR_INVALID_TOKEN = {
    "type": "Error",
    "err_code": "AUTH_INVALID",
    "message": "Realtime transcription token is invalid or expired.",
}
PROXY_ERROR_MISSING_API_KEY = {
    "type": "Error",
    "err_code": "PROVIDER_UNAVAILABLE",
    "message": "Live transcription provider is not configured.",
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
    db: Database,
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
        recent_mints = check_realtime_session_mint_rate_limit(str(user.id), request.purpose)
    except HTTPException as exc:
        capture_sentry_anomaly(
            "realtime.session_mint.rate_limited",
            "Realtime session minting blocked (possible runaway/abusive client)",
            category="transcription.session",
            extras={
                "user_id": str(user.id),
                "purpose": request.purpose,
                "status_code": exc.status_code,
            },
            level="warning",
        )
        raise
    if recent_mints > REALTIME_MINT_SUSTAINED_ALERT:
        capture_sentry_anomaly(
            "realtime.session_mint.high_rate",
            "User sustaining a high realtime session-mint rate (watch for runaway)",
            category="transcription.session",
            extras={
                "user_id": str(user.id),
                "purpose": request.purpose,
                "mints_last_15min": recent_mints,
            },
            level="warning",
        )
    try:
        session = await create_realtime_transcription_session(
            language=request.language,
            channels=request.channels,
            purpose=request.purpose,
            user=user,
            websocket_url=_stream_websocket_url(http_request),
            keyterms=await load_user_keyterms(db, user_id=user.id, purpose=request.purpose),
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
    """Proxy realtime audio frames to Deepgram without exposing the API key.

    All early-rejection paths accept the upgrade FIRST, send a structured
    error frame, then close. Closing before accept was the previous default
    for missing/invalid tokens — but URLSession on the client side then
    reported the failure as a generic close with no body, which got swallowed
    by the dictation state machine when it landed during the .connecting
    window. The accept-frame-close pattern is also what makes these failures
    visible in Sentry: `_close_websocket_with_telemetry` always emits a
    breadcrumb so a flat-line dictation flow has a paper trail.
    """
    token = _bearer_token(websocket)
    if not token:
        await websocket.accept()
        await _send_error_payload(websocket, PROXY_ERROR_MISSING_BEARER)
        await _close_websocket_with_telemetry(
            websocket,
            code=1008,
            err_code="AUTH_MISSING",
            extras={"stage": "auth"},
        )
        return

    try:
        claims = decode_realtime_proxy_token(token)
    except ValueError as exc:
        await websocket.accept()
        await _send_error_payload(websocket, PROXY_ERROR_INVALID_TOKEN)
        await _close_websocket_with_telemetry(
            websocket,
            code=1008,
            err_code="AUTH_INVALID",
            extras={
                "stage": "token_decode",
                # str(exc) is safe — decode_realtime_proxy_token raises with
                # bounded fixed strings (no token contents, no user data).
                "reason": str(exc),
            },
        )
        return

    target_url = build_deepgram_realtime_url_from_proxy_claims(claims)
    try:
        deepgram_api_key = require_deepgram_api_key()
    except ValueError:
        await websocket.accept()
        await _send_error_payload(websocket, PROXY_ERROR_MISSING_API_KEY)
        await _close_websocket_with_telemetry(
            websocket,
            code=1011,
            err_code="PROVIDER_UNAVAILABLE",
            extras={
                "stage": "api_key",
                "provider": "deepgram",
                "model": claims.model,
                "language": claims.language,
                "purpose": claims.purpose,
            },
        )
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
        add_sentry_breadcrumb(
            category="transcription.stream",
            message="client disconnected",
            data={
                "provider": "deepgram",
                "purpose": claims.purpose,
            },
        )
        return
    except ConnectionClosed:
        await _close_websocket_with_telemetry(
            websocket,
            code=1000,
            err_code="PROVIDER_CLOSED",
            extras={
                "stage": "provider_closed",
                "provider": "deepgram",
                "model": claims.model,
                "language": claims.language,
                "purpose": claims.purpose,
            },
        )
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
        await _send_error_payload(websocket, PROXY_ERROR_PAYLOAD)
        await _close_websocket_with_telemetry(
            websocket,
            code=1011,
            err_code="PROXY_FAILURE",
            extras={
                "stage": "proxy_exception",
                "provider": "deepgram",
                "model": claims.model,
                "language": claims.language,
                "purpose": claims.purpose,
                "error_type": type(exc).__name__,
            },
        )
    else:
        await _close_websocket_with_telemetry(
            websocket,
            code=1000,
            err_code="NORMAL",
            extras={
                "stage": "normal",
                "provider": "deepgram",
                "model": claims.model,
                "language": claims.language,
                "purpose": claims.purpose,
            },
        )


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


async def _close_websocket_with_telemetry(
    websocket: WebSocket,
    *,
    code: int,
    err_code: str,
    extras: dict[str, object] | None = None,
) -> None:
    """Close the WS and emit a breadcrumb so close paths are observable.

    Previously, the auth-fail close-before-accept and "ConnectionClosed →
    close 1000" paths emitted zero telemetry — the whole "dictation starts
    then immediately stops" class of bug was invisible in Sentry. Every
    close now leaves a breadcrumb keyed by `err_code` so a flat-line user
    flow has a trace.
    """
    payload: dict[str, object] = {"close_code": code, "err_code": err_code}
    if extras:
        payload.update(extras)
    add_sentry_breadcrumb(
        category="transcription.stream",
        message="proxy closed",
        data=payload,
    )
    await _close_websocket(websocket, code=code)


async def _send_error_payload(websocket: WebSocket, payload: dict[str, object]) -> None:
    """Best-effort error frame send. Swallows RuntimeError raised when the
    underlying socket is already closed — the breadcrumb in the close path
    is the authoritative signal.
    """
    try:
        await websocket.send_json(payload)
    except (RuntimeError, WebSocketDisconnect):
        pass


def _websockets_header_kwarg() -> str:
    parameters = inspect.signature(websockets.connect).parameters
    if "additional_headers" in parameters:
        return "additional_headers"
    return "extra_headers"
