"""Dictation benchmark endpoints."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import Database, OptionalUser
from app.config import get_settings
from app.core.rate_limit import get_rate_limiter
from app.core.transcription import transcribe_audio_file
from app.core.transcription_options import (
    TRANSCRIPTION_OPTIONS,
    is_valid_option,
    normalize_model,
    normalize_provider,
    provider_is_configured,
)
from app.models.benchmark import DictationBenchmarkVote

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])
logger = logging.getLogger(__name__)

MAX_BENCHMARK_AUDIO_BYTES = 8 * 1024 * 1024
MAX_BENCHMARK_CANDIDATES = 3
SUPPORTED_BENCHMARK_CONTENT_TYPES = {
    "audio/webm",
    "audio/wav",
    "audio/mpeg",
    "audio/mp4",
    "audio/x-m4a",
    "audio/m4a",
    "audio/ogg",
}
BENCHMARK_RATE_LIMIT_REQUESTS = 10
BENCHMARK_RATE_LIMIT_WINDOW_SECONDS = 60


class DictationBenchmarkCandidate(BaseModel):
    """One model output in a blind benchmark battle."""

    id: str
    provider: str
    model: str
    label: str
    status: str
    transcript: str | None = None
    latency_ms: int | None = None
    word_count: int | None = None
    error: str | None = None


class DictationBenchmarkBattleResponse(BaseModel):
    """Live dictation benchmark result."""

    battle_id: str
    language: str
    candidates: list[DictationBenchmarkCandidate]


class DictationBenchmarkVoteRequest(BaseModel):
    """Selected winner from a blind benchmark battle."""

    battle_id: str = Field(min_length=1, max_length=64)
    selected_candidate_id: str = Field(min_length=1, max_length=64)
    selected_provider: str = Field(min_length=1, max_length=40)
    selected_model: str = Field(min_length=1, max_length=100)
    language: str = Field(default="multi", max_length=16)
    candidate_count: int = Field(ge=1, le=MAX_BENCHMARK_CANDIDATES)


class DictationBenchmarkVoteResponse(BaseModel):
    """Persisted benchmark vote metadata."""

    vote_id: str


def _configured_file_stt_options():
    settings = get_settings()
    return [
        option
        for option in TRANSCRIPTION_OPTIONS["file_stt"]
        if provider_is_configured(option.provider, settings)
    ][:MAX_BENCHMARK_CANDIDATES]


def _check_benchmark_rate_limit(request: Request) -> None:
    limiter = get_rate_limiter()
    client_ip = request.client.host if request.client else "unknown"
    limiter.check(
        key=f"dictation_benchmark:{client_ip}",
        max_requests=BENCHMARK_RATE_LIMIT_REQUESTS,
        window_seconds=BENCHMARK_RATE_LIMIT_WINDOW_SECONDS,
    )


async def _transcribe_candidate(
    *,
    audio_data: bytes,
    content_type: str,
    language: str,
    provider: str,
    model: str,
    label: str,
) -> DictationBenchmarkCandidate:
    started = time.perf_counter()
    candidate_id = uuid4().hex
    try:
        transcription = await transcribe_audio_file(
            audio_data,
            language=language,
            model=model,
            content_type=content_type,
            provider=provider,
        )
    except Exception as exc:
        logger.warning(
            "Dictation benchmark provider failed provider=%s model=%s error=%s",
            provider,
            model,
            exc,
        )
        return DictationBenchmarkCandidate(
            id=candidate_id,
            provider=provider,
            model=model,
            label=label,
            status="error",
            latency_ms=round((time.perf_counter() - started) * 1000),
            error="Provider request failed.",
        )

    transcript = " ".join(
        segment.text.strip() for segment in transcription.segments if segment.text.strip()
    ).strip()
    return DictationBenchmarkCandidate(
        id=candidate_id,
        provider=provider,
        model=model,
        label=label,
        status="ok",
        transcript=transcript,
        latency_ms=round((time.perf_counter() - started) * 1000),
        word_count=len(transcript.split()),
    )


@router.post("/dictation/battle", response_model=DictationBenchmarkBattleResponse)
async def create_dictation_benchmark_battle(
    request: Request,
    user: OptionalUser,
    audio: UploadFile = File(...),
    language: str = Form(default="multi", max_length=16),
) -> DictationBenchmarkBattleResponse:
    """Run the same short dictated audio through configured file STT providers.

    The audio is kept in memory only for this request and is not persisted.
    """
    del user
    _check_benchmark_rate_limit(request)

    content_type = (audio.content_type or "application/octet-stream").split(";")[0].strip().lower()
    if content_type not in SUPPORTED_BENCHMARK_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported benchmark audio type: {content_type}",
        )

    audio_data = await audio.read(MAX_BENCHMARK_AUDIO_BYTES + 1)
    if len(audio_data) > MAX_BENCHMARK_AUDIO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Benchmark audio exceeds 8 MB.",
        )
    if not audio_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Benchmark audio is empty.",
        )

    options = _configured_file_stt_options()
    if not options:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No file transcription providers are configured for benchmark battles.",
        )

    normalized_language = language.strip().lower() or "multi"
    candidates = await asyncio.gather(
        *[
            _transcribe_candidate(
                audio_data=audio_data,
                content_type=content_type,
                language=normalized_language,
                provider=option.provider,
                model=option.model,
                label=option.label,
            )
            for option in options
        ]
    )
    random.SystemRandom().shuffle(candidates)

    return DictationBenchmarkBattleResponse(
        battle_id=uuid4().hex,
        language=normalized_language,
        candidates=list(candidates),
    )


@router.post("/dictation/battle/vote", response_model=DictationBenchmarkVoteResponse)
async def create_dictation_benchmark_vote(
    request: DictationBenchmarkVoteRequest,
    user: OptionalUser,
    db: Database,
) -> DictationBenchmarkVoteResponse:
    """Persist the user's blind benchmark winner without audio or transcript text."""
    provider = normalize_provider(request.selected_provider)
    model = normalize_model(request.selected_model)
    if not (
        is_valid_option("file_stt", provider, model)
        or is_valid_option("dictation_live_stt", provider, model)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported benchmark vote option: {provider}/{model}",
        )

    vote = DictationBenchmarkVote(
        user_id=user.id if user is not None else None,
        battle_id=request.battle_id,
        language=request.language.strip().lower() or "multi",
        selected_candidate_id=request.selected_candidate_id,
        selected_provider=provider,
        selected_model=model,
        candidate_count=request.candidate_count,
    )
    db.add(vote)
    await db.commit()
    return DictationBenchmarkVoteResponse(vote_id=str(vote.id))
