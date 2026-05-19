"""Realtime transcription session routes."""

import asyncio
import json
import logging
from typing import Literal

import websockets
from fastapi import APIRouter, HTTPException, WebSocket, status
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect

from app.api.deps import CurrentUser
from app.config import get_settings
from app.core.deepgram import realtime_websocket_url as deepgram_realtime_websocket_url
from app.core.observability import add_sentry_breadcrumb, capture_sentry_exception
from app.core.realtime_transcription import create_realtime_transcription_session
from app.core.security import decode_access_token
from app.core.transcription_options import is_valid_option

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transcription", tags=["transcription"])


UNAVAILABLE_DETAIL = "Live transcription is temporarily unavailable. Please try again in a moment."


class CreateRealtimeTranscriptionSessionRequest(BaseModel):
    language: str = "multi"
    channels: int = Field(default=1, ge=1, le=2)
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
    auth_scheme: str = "query_token"


def _bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


@router.post("/session", response_model=RealtimeTranscriptionSessionResponse)
async def create_session(
    request: CreateRealtimeTranscriptionSessionRequest,
    user: CurrentUser,
) -> RealtimeTranscriptionSessionResponse:
    """Create a provider-backed realtime speech-to-text session."""
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
        )
    except ValueError as exc:
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
        capture_sentry_exception(
            exc,
            extras={
                "language": request.language,
                "channels": request.channels,
                "purpose": request.purpose,
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

    add_sentry_breadcrumb(
        category="transcription.session",
        message="mint succeeded",
        data={
            "provider": session.provider,
            "model": session.model,
            "language": session.language,
            "purpose": request.purpose,
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


@router.websocket("/deepgram-proxy")
async def deepgram_realtime_proxy(
    websocket: WebSocket,
    model: str,
    language: str = "multi",
    channels: int = 1,
) -> None:
    """Server-side Deepgram realtime proxy for clients without grant-capable keys."""
    token = _bearer_token(websocket.headers.get("authorization"))
    if token is None or decode_access_token(token) is None:
        await websocket.close(code=1008)
        return

    if not (
        is_valid_option("dictation_live_stt", "deepgram", model)
        or is_valid_option("recording_live_stt", "deepgram", model)
    ):
        await websocket.close(code=1008)
        return

    settings = get_settings()
    if not settings.deepgram_api_key:
        await websocket.close(code=1011)
        return

    upstream_url, _, _ = deepgram_realtime_websocket_url(
        model=model,
        language=language,
        channels=channels,
    )
    await websocket.accept()

    try:
        async with websockets.connect(
            upstream_url,
            additional_headers={"Authorization": f"Token {settings.deepgram_api_key}"},
        ) as upstream:

            async def client_to_upstream() -> None:
                while True:
                    message = await websocket.receive()
                    if message.get("bytes") is not None:
                        await upstream.send(message["bytes"])
                        continue
                    text = message.get("text")
                    if text is not None and _is_deepgram_control_message(text):
                        await upstream.send(text)

            async def upstream_to_client() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(str(message))

            tasks = {
                asyncio.create_task(client_to_upstream()),
                asyncio.create_task(upstream_to_client()),
            }
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                exception = task.exception()
                if exception is not None:
                    raise exception
            for task in pending:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        logger.warning("Deepgram realtime proxy failed error=%s", exc)
        try:
            await websocket.close(code=1011)
        except RuntimeError:
            return


def _is_deepgram_control_message(text: str) -> bool:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("type") in {"CloseStream", "KeepAlive"}
