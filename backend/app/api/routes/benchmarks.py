"""Dictation benchmark endpoints."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.config import get_settings
from app.core.transcription import transcribe_audio_file
from app.core.transcription_options import TRANSCRIPTION_OPTIONS, provider_is_configured

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


def _configured_file_stt_options():
    settings = get_settings()
    return [
        option
        for option in TRANSCRIPTION_OPTIONS["file_stt"]
        if provider_is_configured(option.provider, settings)
    ][:MAX_BENCHMARK_CANDIDATES]


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
        segments = await transcribe_audio_file(
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
        segment.text.strip() for segment in segments if segment.text.strip()
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
    user: CurrentUser,
    audio: UploadFile = File(...),
    language: str = Form(default="multi", max_length=16),
) -> DictationBenchmarkBattleResponse:
    """Run the same short dictated audio through configured file STT providers.

    The audio is kept in memory only for this request and is not persisted.
    """
    del user

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
