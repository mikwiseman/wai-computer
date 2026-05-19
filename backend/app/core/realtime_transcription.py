"""Realtime speech-to-text session minting.

The native apps connect directly to provider WebSockets for low latency, but
they must never receive long-lived provider API keys. Every provider branch
returns either a single-use token, a short-lived bearer token, or an ephemeral
client secret.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.core.deepgram import (
    DEEPGRAM_REALTIME_SAMPLE_RATE,
)
from app.core.deepgram import (
    mint_realtime_session as mint_deepgram_realtime_session,
)
from app.core.deepgram import (
    realtime_websocket_url as deepgram_realtime_websocket_url,
)
from app.core.elevenlabs import ELEVENLABS_API_BASE
from app.core.inworld import build_session as build_inworld_session
from app.core.inworld import mint_client_jwt as mint_inworld_client_jwt
from app.core.openai_transcription import (
    OPENAI_REALTIME_SAMPLE_RATE,
    OPENAI_REALTIME_TOKEN_TTL_SECONDS,
)
from app.core.openai_transcription import (
    create_realtime_client_secret as create_openai_realtime_client_secret,
)
from app.core.openai_transcription import (
    realtime_websocket_url as openai_realtime_websocket_url,
)
from app.core.security import create_access_token
from app.core.soniox import (
    mint_realtime_session as mint_soniox_realtime_session,
)
from app.core.transcription_options import (
    DEFAULT_DICTATION_LIVE_STT_MODEL,
    DEFAULT_DICTATION_LIVE_STT_PROVIDER,
    DEFAULT_RECORDING_LIVE_STT_MODEL,
    DEFAULT_RECORDING_LIVE_STT_PROVIDER,
    validate_option,
)
from app.models.user import User

ELEVENLABS_TOKEN_TTL_SECONDS = 15 * 60
DEFAULT_SAMPLE_RATE = 16_000

DictationProvider = Literal["elevenlabs", "inworld", "openai", "deepgram", "soniox"]


@dataclass(frozen=True)
class RealtimeTranscriptionSession:
    """Provider-backed realtime transcription connection details."""

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
    no_verbatim: bool = True
    websocket_url: str | None = None
    auth_scheme: str = "query_token"


async def _create_elevenlabs_realtime_token() -> tuple[str, int]:
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        raise ValueError("ELEVENLABS_API_KEY not configured")

    async with httpx.AsyncClient(base_url=ELEVENLABS_API_BASE, timeout=15.0) as client:
        response = await client.post(
            "/v1/single-use-token/realtime_scribe",
            headers={"xi-api-key": settings.elevenlabs_api_key},
        )
        response.raise_for_status()
        payload = response.json()

    token = payload.get("token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("ElevenLabs returned an invalid realtime transcription token")

    return token, ELEVENLABS_TOKEN_TTL_SECONDS


async def _build_openai_realtime_session(
    *,
    model: str,
    language: str,
    channels: int,
) -> RealtimeTranscriptionSession:
    token = await create_openai_realtime_client_secret(model=model, language=language)
    return RealtimeTranscriptionSession(
        provider="openai",
        token=token,
        expires_in_seconds=OPENAI_REALTIME_TOKEN_TTL_SECONDS,
        sample_rate=OPENAI_REALTIME_SAMPLE_RATE,
        audio_format="pcm_24000",
        language=language,
        channels=channels,
        model=model,
        keep_alive_interval_seconds=None,
        commit_strategy="manual",
        no_verbatim=False,
        websocket_url=openai_realtime_websocket_url(model),
        auth_scheme="bearer",
    )


async def _build_deepgram_realtime_session(
    *,
    model: str,
    language: str,
    channels: int,
    user: User | None = None,
) -> RealtimeTranscriptionSession:
    settings = get_settings()

    if user is not None and settings.deepgram_api_key:
        token_ttl = int(settings.deepgram_realtime_proxy_token_ttl_seconds)
        token = create_access_token(user.id, expires_delta=timedelta(seconds=token_ttl))
        _, resolved_language, keep_alive_interval_seconds = deepgram_realtime_websocket_url(
            model=model,
            language=language,
            channels=channels,
        )
        websocket_url = _deepgram_proxy_websocket_url(
            model=model,
            language=language,
            channels=channels,
        )
        return RealtimeTranscriptionSession(
            provider="deepgram",
            token=token,
            expires_in_seconds=token_ttl,
            sample_rate=DEEPGRAM_REALTIME_SAMPLE_RATE,
            audio_format=f"linear16_{DEEPGRAM_REALTIME_SAMPLE_RATE}",
            language=resolved_language,
            channels=max(1, channels),
            model=model,
            keep_alive_interval_seconds=keep_alive_interval_seconds,
            commit_strategy="vad",
            no_verbatim=False,
            websocket_url=websocket_url,
            auth_scheme="bearer",
        )

    session = await mint_deepgram_realtime_session(
        model=model,
        language=language,
        channels=channels,
    )
    return RealtimeTranscriptionSession(
        provider="deepgram",
        token=session.access_token,
        expires_in_seconds=session.expires_in_seconds,
        sample_rate=session.sample_rate,
        audio_format=f"linear16_{session.sample_rate}",
        language=session.language,
        channels=session.channels,
        model=session.model,
        keep_alive_interval_seconds=session.keep_alive_interval_seconds,
        commit_strategy="vad",
        no_verbatim=False,
        websocket_url=session.websocket_url,
        auth_scheme="bearer",
    )


def _deepgram_proxy_websocket_url(*, model: str, language: str, channels: int) -> str:
    settings = get_settings()
    base_url = settings.frontend_url.rstrip("/")
    if base_url.startswith("https://"):
        ws_base_url = f"wss://{base_url.removeprefix('https://')}"
    elif base_url.startswith("http://"):
        ws_base_url = f"ws://{base_url.removeprefix('http://')}"
    else:
        ws_base_url = base_url
    return (
        f"{ws_base_url}/api/transcription/deepgram-proxy?"
        f"{urlencode({'model': model, 'language': language, 'channels': max(1, channels)})}"
    )


async def _build_soniox_realtime_session(
    *,
    model: str,
    language: str,
    channels: int,
) -> RealtimeTranscriptionSession:
    session = await mint_soniox_realtime_session(
        model=model,
        language=language,
        channels=channels,
    )
    return RealtimeTranscriptionSession(
        provider="soniox",
        token=session.temporary_api_key,
        expires_in_seconds=session.expires_in_seconds,
        sample_rate=session.sample_rate,
        audio_format=f"linear16_{session.sample_rate}",
        language=session.language,
        channels=session.channels,
        model=session.model,
        keep_alive_interval_seconds=None,
        commit_strategy="vad",
        no_verbatim=False,
        websocket_url=session.websocket_url,
        auth_scheme="message_api_key",
    )


async def _build_inworld_realtime_session(
    language: str,
    channels: int,
    *,
    model: str,
) -> RealtimeTranscriptionSession:
    settings = get_settings()
    if not settings.inworld_api_key:
        raise ValueError("INWORLD_API_KEY not configured")

    jwt = await mint_inworld_client_jwt(
        api_key=settings.inworld_api_key,
        workspace=settings.inworld_workspace,
    )
    inworld = build_inworld_session(
        api_key=settings.inworld_api_key,
        auth_header=f"Bearer {jwt.token}",
        expires_in_seconds=jwt.expires_in_seconds,
        model_id=model,
        language=language,
        sample_rate=DEFAULT_SAMPLE_RATE,
        channels=channels,
    )
    return RealtimeTranscriptionSession(
        provider="inworld",
        token=jwt.token,
        expires_in_seconds=inworld.expires_in_seconds,
        sample_rate=inworld.sample_rate_hertz,
        audio_format="linear16_16000",
        language=inworld.language,
        channels=inworld.number_of_channels,
        model=inworld.model_id,
        keep_alive_interval_seconds=None,
        commit_strategy="vad",
        no_verbatim=False,
        websocket_url=inworld.websocket_url,
        auth_scheme="bearer",
    )


async def create_realtime_transcription_session(
    *,
    language: str = "multi",
    channels: int = 1,
    purpose: Literal["recording", "dictation"] = "recording",
    user: User | None = None,
) -> RealtimeTranscriptionSession:
    """Create a realtime transcription session for the active speech runtime.

    Both dictation and recording routes honor the authenticated user's curated
    provider/model settings and then return provider-specific connection
    details for the native client.
    """
    settings = get_settings()
    resolved_language = language.strip().lower() or "multi"
    resolved_channels = max(1, channels)

    if purpose == "dictation":
        provider = (
            user.dictation_live_stt_provider
            if user is not None
            else DEFAULT_DICTATION_LIVE_STT_PROVIDER
        )
        model = (
            user.dictation_live_stt_model
            if user is not None
            else DEFAULT_DICTATION_LIVE_STT_MODEL
        )
        provider, model = validate_option("dictation_live_stt", provider, model)
        if provider == "openai":
            return await _build_openai_realtime_session(
                model=model,
                language=resolved_language,
                channels=resolved_channels,
            )
        if provider == "deepgram":
            return await _build_deepgram_realtime_session(
                model=model,
                language=resolved_language,
                channels=resolved_channels,
                user=user,
            )
        if provider == "soniox":
            return await _build_soniox_realtime_session(
                model=model,
                language=resolved_language,
                channels=resolved_channels,
            )
        if provider == "elevenlabs":
            token, expires_in_seconds = await _create_elevenlabs_realtime_token()
            return RealtimeTranscriptionSession(
                provider=provider,
                token=token,
                expires_in_seconds=expires_in_seconds,
                sample_rate=DEFAULT_SAMPLE_RATE,
                audio_format="pcm_16000",
                language=resolved_language,
                channels=resolved_channels,
                model=model,
                keep_alive_interval_seconds=None,
                commit_strategy="vad",
                no_verbatim=bool(settings.elevenlabs_no_verbatim),
                websocket_url=None,
                auth_scheme="query_token",
            )
        if provider != "inworld":
            raise ValueError(
                f"Unsupported dictation_live_stt_provider: {provider}."
            )
        return await _build_inworld_realtime_session(
            resolved_language,
            resolved_channels,
            model=model,
        )

    provider = (
        user.recording_live_stt_provider
        if user is not None
        else DEFAULT_RECORDING_LIVE_STT_PROVIDER
    )
    model = (
        user.recording_live_stt_model
        if user is not None
        else DEFAULT_RECORDING_LIVE_STT_MODEL
    )
    provider, model = validate_option("recording_live_stt", provider, model)
    if provider == "openai":
        return await _build_openai_realtime_session(
            model=model,
            language=resolved_language,
            channels=resolved_channels,
        )
    if provider == "deepgram":
        return await _build_deepgram_realtime_session(
            model=model,
            language=resolved_language,
            channels=resolved_channels,
            user=user,
        )
    if provider == "soniox":
        return await _build_soniox_realtime_session(
            model=model,
            language=resolved_language,
            channels=resolved_channels,
        )
    if provider == "inworld":
        return await _build_inworld_realtime_session(
            resolved_language,
            resolved_channels,
            model=model,
        )
    if provider != "elevenlabs":
        raise ValueError(f"Unsupported recording_live_stt_provider: {provider}.")

    token, expires_in_seconds = await _create_elevenlabs_realtime_token()
    return RealtimeTranscriptionSession(
        provider=provider,
        token=token,
        expires_in_seconds=expires_in_seconds,
        sample_rate=DEFAULT_SAMPLE_RATE,
        audio_format="pcm_16000",
        language=resolved_language,
        channels=resolved_channels,
        model=model,
        keep_alive_interval_seconds=None,
        commit_strategy="vad",
        no_verbatim=bool(settings.elevenlabs_no_verbatim),
        websocket_url=None,
        auth_scheme="query_token",
    )
