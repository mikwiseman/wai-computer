"""Realtime transcription session routes and backend provider proxy."""

import asyncio
import inspect
import json
import logging
from time import perf_counter
from typing import Literal

import websockets
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from websockets.exceptions import ConnectionClosed

from app.api.deps import CurrentUser, Database
from app.config import get_settings
from app.core.deepgram import require_deepgram_api_key
from app.core.deepgram_usage import (
    effective_billable_seconds,
    record_deepgram_usage_event,
    record_deepgram_usage_event_standalone,
)
from app.core.observability import (
    add_sentry_breadcrumb,
    capture_sentry_anomaly,
    capture_sentry_exception,
)
from app.core.personalization import load_user_realtime_hints
from app.core.realtime_transcription import (
    UnsupportedRealtimeLanguageError,
    build_deepgram_realtime_url_from_proxy_claims,
    create_realtime_transcription_session,
    decode_realtime_proxy_token,
)
from app.core.transcription_guard import (
    TranscriptionGuardError,
    acquire_stream_slot,
    check_minutes_budget,
    provider_breaker_open,
    record_minutes,
    register_mint,
    release_stream_slot,
    transcription_halted,
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
PROXY_ERROR_HALTED = {
    "type": "Error",
    "err_code": "TRANSCRIPTION_HALTED",
    "message": "Live transcription is temporarily disabled.",
}
PROXY_ERROR_TOO_MANY_STREAMS = {
    "type": "Error",
    "err_code": "TOO_MANY_STREAMS",
    "message": "Too many simultaneous live transcription streams.",
}
PROXY_ERROR_SESSION_EXPIRED = {
    "type": "Error",
    "err_code": "SESSION_EXPIRED",
    "message": "Live transcription session reached its maximum duration.",
}
CLIENT_DISCONNECTED = "client_disconnected"
PROVIDER_FINALIZING = "provider_finalizing"
PROVIDER_COMPLETED = "provider_completed"
PROVIDER_CLOSED_AFTER_CLOSE_STREAM = "provider_closed_after_close_stream"
ClientToProviderExit = Literal["client_disconnected", "provider_finalizing"]
ProviderToClientExit = Literal[
    "client_disconnected",
    "provider_completed",
    "provider_closed_after_close_stream",
]


class RealtimeReplacementHintRequest(BaseModel):
    find: str
    replace: str


class CreateRealtimeTranscriptionSessionRequest(BaseModel):
    language: str = "multi"
    channels: int = Field(default=1, ge=1, le=1)
    purpose: Literal["recording", "dictation"] = "recording"
    keyterms: list[str] = Field(default_factory=list, max_length=100)
    replacements: list[RealtimeReplacementHintRequest] = Field(
        default_factory=list,
        max_length=200,
    )


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


async def _record_realtime_mint_event(
    db: Database,
    *,
    user_id: str,
    purpose: str,
    status: str,
    language: str,
    channels: int,
    model: str | None = None,
    latency_ms: int | None = None,
    guard_code: str | None = None,
    error_type: str | None = None,
    keyterms: list[str] | None = None,
) -> None:
    await record_deepgram_usage_event(
        db,
        user_id=user_id,
        operation="realtime_session_mint",
        purpose=purpose,
        status=status,
        model=model,
        language=language,
        audio_seconds=0,
        billable_seconds=0,
        channel_count=channels,
        latency_ms=latency_ms,
        guard_code=guard_code,
        error_type=error_type,
        billing_mode="streaming",
        language_mode="multilingual",
        addons=_realtime_deepgram_addons(purpose=purpose, keyterms=keyterms or []),
        commit=True,
    )


def _realtime_deepgram_addons(*, purpose: str, keyterms: list[str]) -> list[str]:
    addons: list[str] = []
    if purpose == "recording":
        addons.append("speaker_diarization")
    if keyterms:
        addons.append("keyterm_prompting")
    return addons


def _client_dictation_hints(
    request: CreateRealtimeTranscriptionSessionRequest,
) -> tuple[list[str], list[tuple[str, str]]]:
    if request.purpose != "dictation":
        return [], []

    keyterms = [term.strip() for term in request.keyterms if term.strip()]
    replacements = [
        (replacement.find.strip(), replacement.replace.strip())
        for replacement in request.replacements
        if replacement.find.strip()
        and replacement.replace.strip()
        and replacement.find.strip().casefold() != replacement.replace.strip().casefold()
    ]
    return keyterms, replacements


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
    if await transcription_halted():
        latency_ms = round((perf_counter() - started_at) * 1000)
        await _record_realtime_mint_event(
            db,
            user_id=str(user.id),
            purpose=request.purpose,
            status="refused",
            language=request.language,
            channels=request.channels,
            latency_ms=latency_ms,
            guard_code="transcription_halted",
        )
        capture_sentry_anomaly(
            "realtime.session_mint.halted",
            "Realtime session mint refused: transcription kill-switch engaged",
            category="transcription.session",
            extras={"user_id": str(user.id), "purpose": request.purpose},
            level="warning",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=UNAVAILABLE_DETAIL,
        )
    if await provider_breaker_open():
        latency_ms = round((perf_counter() - started_at) * 1000)
        await _record_realtime_mint_event(
            db,
            user_id=str(user.id),
            purpose=request.purpose,
            status="refused",
            language=request.language,
            channels=request.channels,
            latency_ms=latency_ms,
            guard_code="provider_unavailable",
        )
        capture_sentry_anomaly(
            "realtime.session_mint.breaker_open",
            "Realtime session mint refused: Deepgram circuit breaker is open",
            category="transcription.session",
            extras={"user_id": str(user.id), "purpose": request.purpose},
            level="warning",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=UNAVAILABLE_DETAIL,
        )
    try:
        recent_mints = await register_mint(str(user.id), request.purpose)
    except TranscriptionGuardError as exc:
        latency_ms = round((perf_counter() - started_at) * 1000)
        await _record_realtime_mint_event(
            db,
            user_id=str(user.id),
            purpose=request.purpose,
            status="refused",
            language=request.language,
            channels=request.channels,
            latency_ms=latency_ms,
            guard_code=exc.code,
        )
        capture_sentry_anomaly(
            "realtime.session_mint.rate_limited",
            "Realtime session minting blocked (possible runaway/abusive client)",
            category="transcription.session",
            extras={
                "user_id": str(user.id),
                "purpose": request.purpose,
                "guard_code": exc.code,
            },
            level="warning",
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.message,
            headers={"Retry-After": str(exc.retry_after)} if exc.retry_after else None,
        ) from exc
    try:
        await check_minutes_budget(str(user.id))
    except TranscriptionGuardError as exc:
        latency_ms = round((perf_counter() - started_at) * 1000)
        await _record_realtime_mint_event(
            db,
            user_id=str(user.id),
            purpose=request.purpose,
            status="refused",
            language=request.language,
            channels=request.channels,
            latency_ms=latency_ms,
            guard_code=exc.code,
        )
        capture_sentry_anomaly(
            "realtime.session_mint.minutes_capped",
            "Realtime session mint refused: daily transcription-minute ceiling reached",
            category="transcription.session",
            extras={
                "user_id": str(user.id),
                "purpose": request.purpose,
                "guard_code": exc.code,
            },
            level="warning",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Daily transcription capacity reached. Please try again later.",
        ) from exc
    if recent_mints > get_settings().realtime_mint_sustained_alert:
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
        realtime_hints = await load_user_realtime_hints(
            db,
            user_id=user.id,
            purpose=request.purpose,
        )
        client_keyterms, client_replacements = _client_dictation_hints(request)
        keyterms = [*realtime_hints.keyterms, *client_keyterms]
        replacements = [*realtime_hints.replacements, *client_replacements]
        session = await create_realtime_transcription_session(
            language=request.language,
            channels=request.channels,
            purpose=request.purpose,
            user=user,
            websocket_url=_stream_websocket_url(http_request),
            keyterms=keyterms,
            replacements=replacements,
        )
    except UnsupportedRealtimeLanguageError as exc:
        latency_ms = round((perf_counter() - started_at) * 1000)
        await _record_realtime_mint_event(
            db,
            user_id=str(user.id),
            purpose=request.purpose,
            status="refused",
            language=request.language,
            channels=request.channels,
            latency_ms=latency_ms,
            guard_code="unsupported_language",
            error_type=type(exc).__name__,
        )
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
        await _record_realtime_mint_event(
            db,
            user_id=str(user.id),
            purpose=request.purpose,
            status="failed",
            language=request.language,
            channels=request.channels,
            latency_ms=latency_ms,
            error_type=type(exc).__name__,
        )
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
        await _record_realtime_mint_event(
            db,
            user_id=str(user.id),
            purpose=request.purpose,
            status="failed",
            language=request.language,
            channels=request.channels,
            latency_ms=latency_ms,
            error_type=type(exc).__name__,
        )
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
    await _record_realtime_mint_event(
        db,
        user_id=str(user.id),
        purpose=request.purpose,
        status="succeeded",
        language=session.language,
        channels=session.channels,
        model=session.model,
        latency_ms=latency_ms,
        keyterms=keyterms,
    )
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
        await record_deepgram_usage_event_standalone(
            user_id=claims.subject,
            operation="realtime_stream",
            purpose=claims.purpose,
            status="refused",
            model=claims.model,
            language=claims.language,
            audio_seconds=0,
            billable_seconds=0,
            channel_count=claims.channels,
            guard_code="missing_api_key",
            billing_mode="streaming",
            language_mode="multilingual",
            addons=_realtime_deepgram_addons(
                purpose=claims.purpose,
                keyterms=claims.keyterms,
            ),
        )
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

    if await transcription_halted():
        await record_deepgram_usage_event_standalone(
            user_id=claims.subject,
            operation="realtime_stream",
            purpose=claims.purpose,
            status="refused",
            model=claims.model,
            language=claims.language,
            audio_seconds=0,
            billable_seconds=0,
            channel_count=claims.channels,
            guard_code="transcription_halted",
            billing_mode="streaming",
            language_mode="multilingual",
            addons=_realtime_deepgram_addons(
                purpose=claims.purpose,
                keyterms=claims.keyterms,
            ),
        )
        await _send_error_payload(websocket, PROXY_ERROR_HALTED)
        await _close_websocket_with_telemetry(
            websocket,
            code=1011,
            err_code="TRANSCRIPTION_HALTED",
            extras={"stage": "killswitch", "provider": "deepgram", "purpose": claims.purpose},
        )
        return

    settings = get_settings()
    max_stream_seconds = (
        settings.realtime_stream_max_seconds_recording
        if claims.purpose == "recording"
        else settings.realtime_stream_max_seconds_dictation
    )
    # Lease lives a little past the wall-clock cap so a crashed socket (no clean
    # release) is reclaimed by stale-eviction rather than leaking a slot forever.
    lease_ttl_seconds = (max_stream_seconds if max_stream_seconds > 0 else 21600) + 300
    stream_token = await acquire_stream_slot(claims.subject, lease_ttl_seconds=lease_ttl_seconds)
    if stream_token is None:
        await record_deepgram_usage_event_standalone(
            user_id=claims.subject,
            operation="realtime_stream",
            purpose=claims.purpose,
            status="refused",
            model=claims.model,
            language=claims.language,
            audio_seconds=0,
            billable_seconds=0,
            channel_count=claims.channels,
            guard_code="too_many_streams",
            billing_mode="streaming",
            language_mode="multilingual",
            addons=_realtime_deepgram_addons(
                purpose=claims.purpose,
                keyterms=claims.keyterms,
            ),
        )
        capture_sentry_anomaly(
            "realtime.stream.too_many_concurrent",
            "Realtime stream refused: per-user/global concurrent-stream cap reached",
            category="transcription.stream",
            extras={"user_id": claims.subject, "purpose": claims.purpose},
            level="warning",
        )
        await _send_error_payload(websocket, PROXY_ERROR_TOO_MANY_STREAMS)
        await _close_websocket_with_telemetry(
            websocket,
            code=1008,
            err_code="TOO_MANY_STREAMS",
            extras={"stage": "concurrency", "provider": "deepgram", "purpose": claims.purpose},
        )
        return

    stream_started = perf_counter()
    provider_opened = False
    stream_status = "succeeded"
    stream_guard_code: str | None = None
    stream_error_type: str | None = None
    stream_provider_status_code: int | None = None
    try:
        # Breadcrumb lives INSIDE the try so a raise here still reaches the
        # finally that releases the stream slot — otherwise a throw in the
        # post-acquire gap would leak the slot for the full lease TTL (up to
        # ~65 min for dictation), locking the user out behind TOO_MANY_STREAMS.
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
            provider_opened = True
            close_stream_sent = asyncio.Event()
            upstream = asyncio.create_task(
                _client_to_provider(websocket, provider, close_stream_sent)
            )
            downstream = asyncio.create_task(
                _provider_to_client(websocket, provider, close_stream_sent)
            )
            done, pending = await asyncio.wait(
                {upstream, downstream},
                timeout=max_stream_seconds if max_stream_seconds > 0 else None,
                return_when=asyncio.FIRST_COMPLETED,
            )
            provider_finalization_timed_out = False
            if done:
                _raise_unexpected_bridge_exceptions(done)
                if (
                    upstream in done
                    and not upstream.cancelled()
                    and upstream.exception() is None
                    and upstream.result() == PROVIDER_FINALIZING
                    and downstream in pending
                ):
                    downstream_done, downstream_pending = await asyncio.wait(
                        {downstream},
                        timeout=_remaining_stream_timeout(
                            stream_started=stream_started,
                            max_stream_seconds=max_stream_seconds,
                        ),
                    )
                    done |= downstream_done
                    pending = (pending - {downstream}) | downstream_pending
                    provider_finalization_timed_out = downstream in pending

            if not done or provider_finalization_timed_out:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                stream_guard_code = "duration_cap"
                # Wall-clock cap reached: bound a stuck/over-long paid stream so a
                # single minted token cannot bill Deepgram indefinitely.
                capture_sentry_anomaly(
                    "realtime.stream.duration_capped",
                    "Realtime stream force-closed at maximum duration",
                    category="transcription.stream",
                    extras={
                        "user_id": claims.subject,
                        "purpose": claims.purpose,
                        "max_seconds": max_stream_seconds,
                    },
                    level="warning",
                )
                await _send_error_payload(websocket, PROXY_ERROR_SESSION_EXPIRED)
                await _close_websocket_with_telemetry(
                    websocket,
                    code=1000,
                    err_code="SESSION_EXPIRED",
                    extras={
                        "stage": "duration_cap",
                        "provider": "deepgram",
                        "purpose": claims.purpose,
                        "max_seconds": max_stream_seconds,
                    },
                )
                return
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            _raise_unexpected_bridge_exceptions(done)
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
        stream_status = "failed"
        stream_error_type = "ConnectionClosed"
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
        stream_status = "failed"
        stream_error_type = type(exc).__name__
        stream_provider_status_code = _provider_exception_status_code(exc)
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
    finally:
        # Always release the concurrency slot and meter the streamed minutes
        # toward the daily ceilings, on every exit path (normal, disconnect,
        # error, or duration cap).
        elapsed_seconds = perf_counter() - stream_started
        billable_seconds = effective_billable_seconds(
            audio_seconds=elapsed_seconds,
            channel_count=claims.channels,
            provider_opened=provider_opened,
        )
        try:
            await release_stream_slot(claims.subject, stream_token)
        except Exception as exc:  # noqa: BLE001 - keep minute accounting and usage logging moving
            logger.warning("realtime stream slot release failed error_type=%s", type(exc).__name__)
        if provider_opened:
            try:
                await record_minutes(claims.subject, elapsed_seconds / 60.0)
            except Exception as exc:  # noqa: BLE001 - analytics should still record the provider usage
                logger.warning(
                    "realtime minute accounting failed error_type=%s",
                    type(exc).__name__,
                )
        await record_deepgram_usage_event_standalone(
            user_id=claims.subject,
            operation="realtime_stream",
            purpose=claims.purpose,
            status=stream_status,
            model=claims.model,
            language=claims.language,
            audio_seconds=elapsed_seconds,
            billable_seconds=billable_seconds,
            channel_count=claims.channels,
            latency_ms=round(elapsed_seconds * 1000),
            provider_status_code=stream_provider_status_code,
            guard_code=stream_guard_code,
            error_type=stream_error_type,
            billing_mode="streaming",
            language_mode="multilingual",
            addons=_realtime_deepgram_addons(
                purpose=claims.purpose,
                keyterms=claims.keyterms,
            ),
            details={"provider_opened": provider_opened},
        )


async def _client_to_provider(
    websocket: WebSocket,
    provider,
    close_stream_sent_event: asyncio.Event,
) -> ClientToProviderExit:
    close_stream_sent = False
    while True:
        message = await websocket.receive()
        message_type = message.get("type")
        if message_type == "websocket.disconnect":
            if close_stream_sent:
                return PROVIDER_FINALIZING
            await provider.close()
            return CLIENT_DISCONNECTED
        if message_type != "websocket.receive":
            continue
        data = message.get("bytes")
        text = message.get("text")
        if data is not None:
            await provider.send(data)
        elif text is not None:
            await provider.send(text)
            if _is_close_stream_message(text):
                close_stream_sent = True
                close_stream_sent_event.set()


async def _provider_to_client(
    websocket: WebSocket,
    provider,
    close_stream_sent_event: asyncio.Event,
) -> ProviderToClientExit:
    try:
        async for message in provider:
            try:
                if isinstance(message, bytes):
                    await websocket.send_bytes(message)
                else:
                    await websocket.send_text(message)
            except (RuntimeError, WebSocketDisconnect):
                add_sentry_breadcrumb(
                    category="transcription.stream",
                    message="client send closed",
                    data={"provider": "deepgram"},
                )
                return CLIENT_DISCONNECTED
    except ConnectionClosed:
        if close_stream_sent_event.is_set():
            add_sentry_breadcrumb(
                category="transcription.stream",
                message="provider closed after client close_stream",
                data={"provider": "deepgram"},
            )
            return PROVIDER_CLOSED_AFTER_CLOSE_STREAM
        raise
    return PROVIDER_COMPLETED


def _raise_unexpected_bridge_exceptions(tasks: set[asyncio.Task]) -> None:
    for task in tasks:
        if task.cancelled():
            continue
        exception = task.exception()
        if exception is not None and not isinstance(exception, WebSocketDisconnect):
            raise exception


def _remaining_stream_timeout(*, stream_started: float, max_stream_seconds: float) -> float | None:
    if max_stream_seconds <= 0:
        return None
    return max(max_stream_seconds - (perf_counter() - stream_started), 0)


def _is_close_stream_message(text: str) -> bool:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("type") == "CloseStream"


def _bearer_token(websocket: WebSocket) -> str | None:
    authorization = websocket.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    # Browsers cannot set the Authorization header on a WebSocket handshake, so
    # also accept the short-lived session proxy token via the `token` query
    # param (the connection is WSS-encrypted). Native clients keep using the
    # header; this is an additive fallback for the web client.
    query_token = websocket.query_params.get("token", "")
    if query_token.strip():
        return query_token.strip()
    return None


def _provider_exception_status_code(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    if isinstance(value, int):
        return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


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
