"""Realtime transcription session routes and backend provider proxy."""

import asyncio
import base64
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
from app.core.ai_usage import (
    FEATURE_DICTATION,
    FEATURE_RECORDING,
    OPENAI_PROVIDER,
    record_ai_usage_event_standalone,
)
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
from app.core.openai_realtime import (
    OPENAI_REALTIME_WEBSOCKET_URL,
    build_transcription_session_update,
    require_openai_api_key,
)
from app.core.openai_realtime_bridge import (
    FINALIZE_MARKER_FRAME,
    FinalizeAction,
    OpenAIRealtimeBridgeState,
    compile_replacements,
)
from app.core.personalization import load_user_realtime_hints
from app.core.realtime_transcription import (
    RealtimeTranscriptionProxyClaims,
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
    record_provider_result,
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


def _expected_live_stt_provider(purpose: str) -> str:
    from app.core.transcription_options import (
        DEFAULT_DICTATION_LIVE_STT_PROVIDER,
        DEFAULT_RECORDING_LIVE_STT_PROVIDER,
    )

    if purpose == "dictation":
        return DEFAULT_DICTATION_LIVE_STT_PROVIDER
    return DEFAULT_RECORDING_LIVE_STT_PROVIDER


def _ai_usage_feature(purpose: str) -> str:
    return FEATURE_DICTATION if purpose == "dictation" else FEATURE_RECORDING


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
    if _expected_live_stt_provider(purpose) == "openai":
        await record_ai_usage_event_standalone(
            provider=OPENAI_PROVIDER,
            feature=_ai_usage_feature(purpose),
            operation="realtime_session_mint",
            status=status,
            user_id=user_id,
            model=model,
            audio_seconds=0,
            billable_seconds=0,
            channel_count=channels,
            latency_ms=latency_ms,
            guard_code=guard_code,
            error_type=error_type,
            billing_mode="streaming",
            details={"purpose": purpose, "language": language},
        )
        return
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
    if _expected_live_stt_provider(request.purpose) == "deepgram" and await provider_breaker_open():
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

    if claims.provider == "openai":
        target_url = OPENAI_REALTIME_WEBSOCKET_URL
        try:
            provider_api_key = require_openai_api_key()
        except ValueError:
            await _record_stream_refusal(claims, guard_code="missing_api_key")
            await websocket.accept()
            await _send_error_payload(websocket, PROXY_ERROR_MISSING_API_KEY)
            await _close_websocket_with_telemetry(
                websocket,
                code=1011,
                err_code="PROVIDER_UNAVAILABLE",
                extras={
                    "stage": "api_key",
                    "provider": claims.provider,
                    "model": claims.model,
                    "language": claims.language,
                    "purpose": claims.purpose,
                },
            )
            return
    else:
        target_url = build_deepgram_realtime_url_from_proxy_claims(claims)
        try:
            provider_api_key = require_deepgram_api_key()
        except ValueError:
            await _record_stream_refusal(claims, guard_code="missing_api_key")
            await websocket.accept()
            await _send_error_payload(websocket, PROXY_ERROR_MISSING_API_KEY)
            await _close_websocket_with_telemetry(
                websocket,
                code=1011,
                err_code="PROVIDER_UNAVAILABLE",
                extras={
                    "stage": "api_key",
                    "provider": claims.provider,
                    "model": claims.model,
                    "language": claims.language,
                    "purpose": claims.purpose,
                },
            )
            return

    await websocket.accept()

    if await transcription_halted():
        await _record_stream_refusal(claims, guard_code="transcription_halted")
        await _send_error_payload(websocket, PROXY_ERROR_HALTED)
        await _close_websocket_with_telemetry(
            websocket,
            code=1011,
            err_code="TRANSCRIPTION_HALTED",
            extras={"stage": "killswitch", "provider": claims.provider, "purpose": claims.purpose},
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
        await _record_stream_refusal(claims, guard_code="too_many_streams")
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
            extras={"stage": "concurrency", "provider": claims.provider, "purpose": claims.purpose},
        )
        return

    if claims.provider == "openai":
        await _stream_openai_after_slot(
            websocket,
            claims,
            stream_token=stream_token,
            api_key=provider_api_key,
            max_stream_seconds=max_stream_seconds,
        )
        return

    deepgram_api_key = provider_api_key
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
            client_gone = asyncio.Event()
            upstream = asyncio.create_task(
                _client_to_provider(websocket, provider, close_stream_sent, client_gone)
            )
            downstream = asyncio.create_task(
                _provider_to_client(websocket, provider, close_stream_sent, client_gone)
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
        # Feed the circuit breaker for provider-side failures: a refused
        # handshake (Deepgram 402 payment / 401 auth / outage) must trip the
        # breaker and page ops. The 2026-06-27 credits exhaustion failed 9
        # streams here while the breaker — fed only by the batch path — stayed
        # closed and nobody was alerted. Mid-stream anomalies without a status
        # code stay out of the streak: they can be client-side.
        if not provider_opened or stream_provider_status_code is not None:
            try:
                await record_provider_result(
                    success=False, status_code=stream_provider_status_code
                )
            except Exception as guard_exc:  # noqa: BLE001 - guard must not break close-out
                logger.warning(
                    "realtime breaker feed failed error_type=%s",
                    type(guard_exc).__name__,
                )
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
        if provider_opened:
            try:
                await record_provider_result(success=True)
            except Exception as guard_exc:  # noqa: BLE001 - guard must not break close-out
                logger.warning(
                    "realtime breaker feed failed error_type=%s",
                    type(guard_exc).__name__,
                )
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
    client_gone_event: asyncio.Event,
) -> ClientToProviderExit:
    close_stream_sent = False
    while True:
        message = await websocket.receive()
        message_type = message.get("type")
        if message_type == "websocket.disconnect":
            client_gone_event.set()
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
    client_gone_event: asyncio.Event,
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
        if client_gone_event.is_set():
            # The upstream bridge closed the provider because the client hung
            # up; racing that close used to escape here and record a routine
            # abandon as a failed stream (22 of the 49 "failed" streams in the
            # 2026-06 window were this).
            add_sentry_breadcrumb(
                category="transcription.stream",
                message="provider closed after client disconnect",
                data={"provider": "deepgram"},
            )
            return CLIENT_DISCONNECTED
        raise
    return PROVIDER_COMPLETED


async def _record_stream_refusal(
    claims: RealtimeTranscriptionProxyClaims,
    *,
    guard_code: str,
) -> None:
    if claims.provider == "openai":
        await _record_openai_stream_usage(
            claims,
            status="refused",
            guard_code=guard_code,
        )
        return
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
        guard_code=guard_code,
        billing_mode="streaming",
        language_mode="multilingual",
        addons=_realtime_deepgram_addons(
            purpose=claims.purpose,
            keyterms=claims.keyterms,
        ),
    )


async def _record_openai_stream_usage(
    claims: RealtimeTranscriptionProxyClaims,
    *,
    status: str,
    audio_seconds: float = 0.0,
    billable_seconds: float | None = None,
    latency_ms: int | None = None,
    guard_code: str | None = None,
    error_type: str | None = None,
    provider_status_code: int | None = None,
    details: dict[str, object] | None = None,
) -> None:
    await record_ai_usage_event_standalone(
        provider=OPENAI_PROVIDER,
        feature=_ai_usage_feature(claims.purpose),
        operation="realtime_stream",
        status=status,
        user_id=claims.subject,
        model=claims.model,
        audio_seconds=audio_seconds,
        billable_seconds=billable_seconds if billable_seconds is not None else audio_seconds,
        channel_count=claims.channels,
        latency_ms=latency_ms,
        guard_code=guard_code,
        error_type=error_type,
        provider_status_code=provider_status_code,
        billing_mode="streaming",
        details={"purpose": claims.purpose, "language": claims.language, **(details or {})},
    )


OPENAI_SESSION_READY_TIMEOUT_SECONDS = 10.0
OPENAI_CLOSE_DRAIN_TIMEOUT_SECONDS = 5.0
_OPENAI_STREAM_ENDED = "provider_stream_ended"
_OPENAI_CLOSE_STREAM = "close_stream"
_OPENAI_DURATION_CAP = "duration_cap"


class OpenAISessionRejectedError(RuntimeError):
    """The OpenAI realtime session refused our session.update config."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"OpenAI realtime session rejected: {code}: {message}")
        self.code = code


async def _await_openai_session_ready(provider, timeout: float) -> None:
    """Wait for ``session.updated`` before bridging audio.

    Audio appended before the session config lands would be transcribed with
    the default (model-less) session and silently produce no text — the exact
    class of quiet failure this product forbids.
    """
    deadline = perf_counter() + timeout
    while True:
        remaining = deadline - perf_counter()
        if remaining <= 0:
            raise TimeoutError("Timed out waiting for OpenAI realtime session.updated")
        raw = await asyncio.wait_for(provider.recv(), timeout=remaining)
        event = json.loads(raw)
        event_type = event.get("type")
        if event_type == "session.updated":
            return
        if event_type == "error":
            error = event.get("error")
            error = error if isinstance(error, dict) else {}
            raise OpenAISessionRejectedError(
                str(error.get("code") or "unknown"),
                str(error.get("message") or "no message"),
            )


async def _openai_reader(
    provider,
    state: OpenAIRealtimeBridgeState,
    outbound: asyncio.Queue,
    drained_event: asyncio.Event,
) -> None:
    """Pump OpenAI server events into downstream frames on the outbound queue."""
    try:
        async for raw in provider:
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", errors="replace")
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            for frame in state.handle_upstream_event(event):
                outbound.put_nowait(frame)
            if state.drained:
                drained_event.set()
    except ConnectionClosed:
        if not (state.close_requested or state.client_gone):
            raise
    finally:
        outbound.put_nowait(None)


async def _openai_writer(websocket: WebSocket, outbound: asyncio.Queue) -> str:
    """Send translated frames to the client; ends on provider-stream end."""
    while True:
        frame = await outbound.get()
        if frame is None:
            return _OPENAI_STREAM_ENDED
        try:
            await websocket.send_json(frame)
        except (RuntimeError, WebSocketDisconnect):
            add_sentry_breadcrumb(
                category="transcription.stream",
                message="client send closed",
                data={"provider": "openai"},
            )
            return CLIENT_DISCONNECTED


async def _openai_client_loop(
    websocket: WebSocket,
    provider,
    state: OpenAIRealtimeBridgeState,
    outbound: asyncio.Queue,
    drained_event: asyncio.Event,
) -> str:
    """Pump client audio/control messages into OpenAI events."""
    while True:
        message = await websocket.receive()
        message_type = message.get("type")
        if message_type == "websocket.disconnect":
            state.client_gone = True
            return CLIENT_DISCONNECTED
        if message_type != "websocket.receive":
            continue
        data = message.get("bytes")
        text = message.get("text")
        if data is not None:
            state.note_audio(len(data))
            await provider.send(
                json.dumps(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(data).decode("ascii"),
                    }
                )
            )
            continue
        if text is None:
            continue
        try:
            control = json.loads(text)
        except json.JSONDecodeError:
            continue
        control_type = control.get("type") if isinstance(control, dict) else None
        if control_type == "KeepAlive":
            continue
        if control_type == "Finalize":
            if state.finalize_action() == FinalizeAction.COMMIT:
                drained_event.clear()
                await provider.send(json.dumps({"type": "input_audio_buffer.commit"}))
            else:
                outbound.put_nowait(dict(FINALIZE_MARKER_FRAME))
            continue
        if control_type == "CloseStream":
            if state.close_flush_needs_commit():
                drained_event.clear()
                await provider.send(json.dumps({"type": "input_audio_buffer.commit"}))
            if not state.drained:
                # Bounded wait so a lost `completed` cannot wedge the close;
                # whatever arrived is already flushed downstream by the writer.
                try:
                    await asyncio.wait_for(
                        drained_event.wait(),
                        timeout=OPENAI_CLOSE_DRAIN_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    add_sentry_breadcrumb(
                        category="transcription.stream",
                        message="openai close drain timed out",
                        data={"provider": "openai"},
                    )
            return _OPENAI_CLOSE_STREAM


async def _bridge_openai_realtime(
    websocket: WebSocket,
    provider,
    claims: RealtimeTranscriptionProxyClaims,
    *,
    max_stream_seconds: float,
) -> str:
    """Run the translated bridge; returns the exit reason."""
    state = OpenAIRealtimeBridgeState(
        replacements=compile_replacements(claims.replacements),
    )
    outbound: asyncio.Queue = asyncio.Queue()
    drained_event = asyncio.Event()
    drained_event.set()

    reader_task = asyncio.create_task(
        _openai_reader(provider, state, outbound, drained_event)
    )
    writer_task = asyncio.create_task(_openai_writer(websocket, outbound))
    client_task = asyncio.create_task(
        _openai_client_loop(websocket, provider, state, outbound, drained_event)
    )
    tasks: set[asyncio.Task] = {reader_task, writer_task, client_task}

    try:
        done, pending = await asyncio.wait(
            {client_task, writer_task},
            timeout=max_stream_seconds if max_stream_seconds > 0 else None,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            return _OPENAI_DURATION_CAP

        if client_task in done:
            exit_reason = client_task.result()
            if exit_reason == _OPENAI_CLOSE_STREAM:
                # Everything committed is drained (bounded). Close upstream so
                # the reader finishes and the writer flushes its sentinel.
                await provider.close()
                await asyncio.wait({writer_task}, timeout=OPENAI_CLOSE_DRAIN_TIMEOUT_SECONDS)
                return PROVIDER_CLOSED_AFTER_CLOSE_STREAM
            await provider.close()
            return CLIENT_DISCONNECTED

        # Writer finished first: either the client socket rejected a send or
        # the provider stream ended on its own (server close / session cap).
        writer_exit = writer_task.result()
        if writer_exit == CLIENT_DISCONNECTED:
            state.client_gone = True
            await provider.close()
            return CLIENT_DISCONNECTED
        if reader_task.done() and (reader_error := reader_task.exception()) is not None:
            raise reader_error
        raise ConnectionClosed(None, None)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _stream_openai_after_slot(
    websocket: WebSocket,
    claims: RealtimeTranscriptionProxyClaims,
    *,
    stream_token: str,
    api_key: str,
    max_stream_seconds: float,
) -> None:
    """OpenAI-side twin of the Deepgram stream flow, past slot acquisition.

    Owns connect + session config + bridge + close-out, and mirrors the
    Deepgram path's accounting contract: the stream slot is always released,
    streamed minutes are metered, and every exit leaves a usage event and a
    close breadcrumb.
    """
    stream_started = perf_counter()
    provider_opened = False
    stream_status = "succeeded"
    stream_guard_code: str | None = None
    stream_error_type: str | None = None
    stream_provider_status_code: int | None = None
    try:
        add_sentry_breadcrumb(
            category="transcription.stream",
            message="proxy opened",
            data={
                "provider": "openai",
                "model": claims.model,
                "language": claims.language,
                "purpose": claims.purpose,
            },
        )
        session_update = build_transcription_session_update(
            model=claims.model,
            language=claims.language,
        )
        async with websockets.connect(
            OPENAI_REALTIME_WEBSOCKET_URL,
            **{
                _websockets_header_kwarg(): {
                    "Authorization": f"Bearer {api_key}",
                }
            },
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            max_size=8 * 1024 * 1024,
        ) as provider:
            await provider.send(json.dumps(session_update))
            await _await_openai_session_ready(
                provider, timeout=OPENAI_SESSION_READY_TIMEOUT_SECONDS
            )
            provider_opened = True
            exit_reason = await _bridge_openai_realtime(
                websocket,
                provider,
                claims,
                max_stream_seconds=max_stream_seconds,
            )
            if exit_reason == _OPENAI_DURATION_CAP:
                stream_guard_code = "duration_cap"
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
                        "provider": "openai",
                        "purpose": claims.purpose,
                        "max_seconds": max_stream_seconds,
                    },
                )
                return
            if exit_reason == CLIENT_DISCONNECTED:
                add_sentry_breadcrumb(
                    category="transcription.stream",
                    message="client disconnected",
                    data={"provider": "openai", "purpose": claims.purpose},
                )
                return
    except WebSocketDisconnect:
        add_sentry_breadcrumb(
            category="transcription.stream",
            message="client disconnected",
            data={"provider": "openai", "purpose": claims.purpose},
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
                "provider": "openai",
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
            "openai realtime proxy failed error_type=%s purpose=%s",
            type(exc).__name__,
            claims.purpose,
        )
        capture_sentry_exception(
            exc,
            extras={
                "alert_code": "realtime.stream.failed",
                "provider": "openai",
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
                "provider": "openai",
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
                "provider": "openai",
                "model": claims.model,
                "language": claims.language,
                "purpose": claims.purpose,
            },
        )
    finally:
        elapsed_seconds = perf_counter() - stream_started
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
        await _record_openai_stream_usage(
            claims,
            status=stream_status,
            audio_seconds=elapsed_seconds,
            billable_seconds=elapsed_seconds if provider_opened else 0.0,
            latency_ms=round(elapsed_seconds * 1000),
            guard_code=stream_guard_code,
            error_type=stream_error_type,
            provider_status_code=stream_provider_status_code,
            details={"provider_opened": provider_opened},
        )


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
