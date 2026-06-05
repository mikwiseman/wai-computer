"""Canonical audio-backed recording transcription processing."""

from __future__ import annotations

import logging
import math
import re
import time
import wave
from pathlib import Path
from time import perf_counter
from uuid import UUID

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.quota import record_recording_transcript_words
from app.config import get_settings
from app.core.deepgram_usage import (
    effective_billable_seconds,
    provider_error_code,
    record_deepgram_usage_event,
)
from app.core.embeddings import generate_embedding
from app.core.error_sanitizer import sanitize_failure_message
from app.core.observability import (
    add_sentry_breadcrumb,
    capture_sentry_anomaly,
    capture_sentry_message,
    fingerprint_text,
)
from app.core.personalization import load_user_keyterms
from app.core.retry_policy import is_retryable_exception
from app.core.speaker_name_extraction import (
    apply_extracted_names,
    extract_speaker_names,
)
from app.core.summarizer import generate_title
from app.core.summary_generation import (
    fail_active_summary_generation_jobs,
    start_recording_summary_generation_job,
)
from app.core.transcript_utils import TranscriptResult
from app.core.transcription import transcribe_audio_file
from app.core.transcription_guard import TranscriptionGuardError
from app.core.transcription_options import DEFAULT_FILE_STT_MODEL
from app.core.voice_identification import identify_speakers_for_recording
from app.models.highlight import Highlight
from app.models.person import RecordingSpeakerEmbedding
from app.models.recording import ActionItem, Recording, RecordingStatus, Segment, Summary

logger = logging.getLogger(__name__)
settings = get_settings()

NO_SPEECH_COPY = {
    "en": {
        "title": "No speech detected",
        "message": "We could not detect clear speech in this recording.",
    },
    "ru": {
        "title": "Без речи",
        "message": "Мы не обнаружили разборчивой речи в этой записи.",
    },
}

NO_SPEECH_PLACEHOLDERS = {
    "blank audio",
    "background noise",
    "inaudible",
    "music",
    "no audible speech",
    "no speech",
    "no speech detected",
    "noise",
    "silence",
    "silent audio",
    "typing",
}
EMPTY_TRANSCRIPT_FAILURE_CODE = "transcript_empty"
MIN_FILE_STT_AUDIO_SECONDS = 0.1
PROCESSING_SLOW_MIN_THRESHOLD_MS = 300_000
PROCESSING_AUDIO_DURATION_MULTIPLIER = 4.0


def copy_locale_from_recording_language(
    language: str | None,
    fallback_language: str | None = None,
) -> str:
    normalized = (language or "").strip().lower()
    if normalized in {"", "auto", "multi"}:
        normalized = (fallback_language or "").strip().lower()
    return "ru" if normalized.startswith("ru") else "en"


def is_no_speech_placeholder(text: str) -> bool:
    normalized = re.sub(r"[\[\]\(\)\{\}_\-.!?:;\"'`]+", " ", text.strip().lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized in NO_SPEECH_PLACEHOLDERS


def apply_no_speech_result(
    recording: Recording,
    fallback_language: str | None = None,
) -> None:
    if recording.title:
        recording.failure_message = None
        return
    copy = NO_SPEECH_COPY[
        copy_locale_from_recording_language(recording.language, fallback_language)
    ]
    recording.title = copy["title"]
    recording.failure_message = sanitize_failure_message(copy["message"])


def apply_no_speech_failure(
    recording: Recording,
    fallback_language: str | None = None,
) -> None:
    copy = NO_SPEECH_COPY[
        copy_locale_from_recording_language(recording.language, fallback_language)
    ]
    if not recording.title:
        recording.title = copy["title"]
    recording.status = RecordingStatus.FAILED.value
    recording.failure_code = EMPTY_TRANSCRIPT_FAILURE_CODE
    recording.failure_message = sanitize_failure_message(copy["message"])


def delete_staged_file(path: Path | str | None) -> None:
    if path is None:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except Exception as error:
        logger.warning("Failed to delete staged audio %s: %s", path, error)


def _enqueue_recording_summary_generation(job_id: UUID) -> str:
    from app.tasks.celery_app import celery_app

    result = celery_app.send_task(
        "app.tasks.summary_generation.generate_recording_summary",
        kwargs={"job_id": str(job_id)},
    )
    return str(result.id)


async def reset_recording_processing_state(recording_id: UUID, db: AsyncSession) -> None:
    """Replace transcript-derived data before canonical transcript generation."""
    await fail_active_summary_generation_jobs(
        db,
        recording_id=recording_id,
        error_code="transcript_replaced",
        error_message="Transcript was replaced before summary generation completed.",
    )
    await db.execute(
        delete(ActionItem).where(
            ActionItem.recording_id == recording_id,
            ActionItem.source == "generated",
        )
    )
    await db.execute(delete(Highlight).where(Highlight.recording_id == recording_id))
    await db.execute(delete(Summary).where(Summary.recording_id == recording_id))
    await db.execute(
        delete(RecordingSpeakerEmbedding).where(
            RecordingSpeakerEmbedding.recording_id == recording_id
        )
    )
    await db.execute(delete(Segment).where(Segment.recording_id == recording_id))


async def mark_recording_processing_failed(
    db: AsyncSession,
    *,
    recording_id: UUID,
    failure_code: str,
    failure_message: str,
) -> None:
    failed = await db.get(Recording, recording_id)
    if failed is None:
        return
    failed.status = RecordingStatus.FAILED.value
    failed.failure_code = failure_code
    failed.failure_message = sanitize_failure_message(failure_message)
    await db.commit()


def _speech_results(results: list[TranscriptResult]) -> list[TranscriptResult]:
    return [
        result
        for result in results
        if result.text.strip() and not is_no_speech_placeholder(result.text)
    ]


def _wav_duration_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            if frame_rate <= 0:
                return None
            return wav_file.getnframes() / frame_rate
    except (wave.Error, EOFError, OSError):
        return None


def _audio_duration_seconds(path: Path, content_type: str) -> float | None:
    normalized_content_type = content_type.split(";", 1)[0].strip().lower()
    if normalized_content_type in {"audio/wav", "audio/x-wav"} or path.suffix.lower() == ".wav":
        return _wav_duration_seconds(path)
    return None


def _audio_is_too_short_for_file_stt(audio_duration_seconds: float | None) -> bool:
    return (
        audio_duration_seconds is not None
        and audio_duration_seconds < MIN_FILE_STT_AUDIO_SECONDS
    )


def recording_processing_slow_threshold_ms(duration_seconds: int | float | None) -> int:
    """Return the alert threshold for end-to-end recording processing latency."""
    if duration_seconds is None or duration_seconds <= 0:
        return PROCESSING_SLOW_MIN_THRESHOLD_MS
    duration_based_threshold = math.ceil(
        duration_seconds * PROCESSING_AUDIO_DURATION_MULTIPLIER * 1000
    )
    return max(PROCESSING_SLOW_MIN_THRESHOLD_MS, duration_based_threshold)


def _effective_duration_seconds(
    *,
    audio_duration_seconds: float | None,
    client_duration_seconds: int | None,
    transcript_end_ms: int | None = None,
) -> int | float | None:
    if audio_duration_seconds is not None and audio_duration_seconds > 0:
        return audio_duration_seconds
    if client_duration_seconds is not None and client_duration_seconds > 0:
        return client_duration_seconds
    if transcript_end_ms is not None and transcript_end_ms > 0:
        return transcript_end_ms / 1000
    return None


def _provider_audio_seconds(
    *,
    audio_duration_seconds: float | None,
    client_duration_seconds: int | None,
) -> float | None:
    if audio_duration_seconds is not None and audio_duration_seconds > 0:
        return audio_duration_seconds
    if client_duration_seconds is not None and client_duration_seconds > 0:
        return float(client_duration_seconds)
    return None


def voice_identification_enabled_for_audio(
    *,
    recording_id: UUID,
    duration_seconds: int | float | None,
    staged_size_bytes: int | None,
) -> bool:
    if not settings.voice_identification_enabled:
        return False
    skip_reasons: list[str] = []
    max_seconds = settings.voice_identification_max_audio_seconds
    if (
        max_seconds > 0
        and duration_seconds is not None
        and duration_seconds > max_seconds
    ):
        skip_reasons.append("duration_limit")
    max_bytes = settings.voice_identification_max_audio_bytes
    if (
        max_bytes > 0
        and staged_size_bytes is not None
        and staged_size_bytes > max_bytes
    ):
        skip_reasons.append("size_limit")
    if not skip_reasons:
        return True
    logger.warning(
        "voice identification skipped by audio guard recording_id=%s "
        "duration_seconds=%s staged_size_bytes=%s reasons=%s",
        recording_id,
        duration_seconds,
        staged_size_bytes,
        ",".join(skip_reasons),
    )
    capture_sentry_anomaly(
        "recording.voice_identification.skipped_size_guard",
        "Recording voice identification skipped by audio size guard",
        category="recording",
        extras={
            "recording_id": str(recording_id),
            "duration_seconds": duration_seconds,
            "staged_size_bytes": staged_size_bytes,
            "max_audio_seconds": max_seconds,
            "max_audio_bytes": max_bytes,
            "reasons": skip_reasons,
        },
        level="warning",
    )
    return False


def _recording_lifecycle_breadcrumb(
    message: str,
    *,
    recording_id: UUID,
    data: dict[str, object] | None = None,
    level: str = "info",
) -> None:
    add_sentry_breadcrumb(
        category="recording",
        message=message,
        level=level,
        data={"recording_id": str(recording_id), **(data or {})},
    )


def _capture_processing_slow_if_needed(
    *,
    recording_id: UUID,
    latency_ms: int,
    audio_duration_seconds: float | None,
    client_duration_seconds: int | None,
    staged_size_bytes: int | None,
    segment_count: int,
    transcript_end_ms: int | None = None,
) -> None:
    effective_duration = _effective_duration_seconds(
        audio_duration_seconds=audio_duration_seconds,
        client_duration_seconds=client_duration_seconds,
        transcript_end_ms=transcript_end_ms,
    )
    threshold_ms = recording_processing_slow_threshold_ms(effective_duration)
    if latency_ms < threshold_ms:
        return
    capture_sentry_anomaly(
        "recording.processing.slow",
        "Recording processing latency exceeded threshold",
        category="recording",
        extras={
            "recording_id": str(recording_id),
            "latency_ms": latency_ms,
            "slow_threshold_ms": threshold_ms,
            "audio_duration_seconds": audio_duration_seconds,
            "client_duration_seconds": client_duration_seconds,
            "effective_duration_seconds": effective_duration,
            "staged_size_bytes": staged_size_bytes,
            "segment_count": segment_count,
        },
    )


def _provider_reported_audio_too_short(exc: Exception) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    if exc.response.status_code != 400:
        return False
    try:
        payload = exc.response.json()
    except ValueError:
        return False
    if not isinstance(payload, dict):
        return False
    detail = payload.get("detail")
    if not isinstance(detail, dict):
        return False
    return any(
        detail.get(key) == "audio_too_short"
        for key in ("code", "type", "status")
    )


def _duration_seconds_from_sources(
    *,
    audio_duration_seconds: float | None,
    client_duration_seconds: int | None,
    transcript_end_ms: int | None,
) -> int | None:
    if (
        audio_duration_seconds is not None
        and audio_duration_seconds >= MIN_FILE_STT_AUDIO_SECONDS
    ):
        return max(math.ceil(audio_duration_seconds), 1)
    if client_duration_seconds is not None and client_duration_seconds > 0:
        return client_duration_seconds
    if transcript_end_ms is not None:
        return transcript_end_ms // 1000
    return None


def _log_transcript_coverage(
    *,
    recording_id: UUID,
    audio_duration_seconds: float | None,
    client_duration_seconds: int | None,
    transcript_end_ms: int | None,
    segment_count: int,
) -> None:
    source_duration = audio_duration_seconds or client_duration_seconds
    transcript_duration = transcript_end_ms // 1000 if transcript_end_ms is not None else None
    coverage_ratio = (
        round(transcript_duration / source_duration, 4)
        if source_duration and transcript_duration is not None
        else None
    )
    logger.info(
        "audio processing coverage recording_id=%s audio_duration_seconds=%s "
        "client_duration_seconds=%s transcript_duration_seconds=%s segment_count=%s "
        "coverage_ratio=%s",
        recording_id,
        audio_duration_seconds,
        client_duration_seconds,
        transcript_duration,
        segment_count,
        coverage_ratio,
    )
    if coverage_ratio is not None and coverage_ratio < 0.8:
        logger.warning(
            "audio transcript coverage below threshold recording_id=%s coverage_ratio=%s",
            recording_id,
            coverage_ratio,
        )
        alert_data = {
            "alert_code": "recording.transcript.low_coverage",
            "recording_id": str(recording_id),
            "audio_duration_seconds": audio_duration_seconds,
            "client_duration_seconds": client_duration_seconds,
            "transcript_duration_seconds": transcript_duration,
            "segment_count": segment_count,
            "coverage_ratio": coverage_ratio,
        }
        add_sentry_breadcrumb(
            category="recording",
            message="Audio transcript coverage below threshold",
            level="warning",
            data=alert_data,
        )
        capture_sentry_message(
            "Audio transcript coverage below threshold",
            level="warning",
            extras=alert_data,
        )


async def process_staged_recording_upload(
    db: AsyncSession,
    *,
    recording_id: UUID,
    user_id: UUID,
    staged_path: Path,
    content_type: str,
    user_default_language: str | None,
    client_duration_seconds: int | None = None,
    client_file_size_bytes: int | None = None,
    staged_size_bytes: int | None = None,
) -> None:
    """Transcribe a staged upload and promote it as the recording's canonical transcript."""
    processing_started_at = perf_counter()
    result = await db.execute(
        select(Recording).where(
            Recording.id == recording_id,
            Recording.user_id == user_id,
            Recording.deleted_at.is_(None),
        )
    )
    recording = result.scalar_one_or_none()
    if recording is None:
        delete_staged_file(staged_path)
        return
    if recording.status != RecordingStatus.PROCESSING.value:
        logger.info("skipping audio processing for recording in status=%s", recording.status)
        _recording_lifecycle_breadcrumb(
            "Recording processing skipped",
            recording_id=recording_id,
            data={"status": recording.status},
        )
        delete_staged_file(staged_path)
        return

    recording.status = RecordingStatus.PROCESSING.value
    recording.failure_code = None
    recording.failure_message = None
    recording.audio_url = None
    recording.duration_seconds = None
    recording_language = recording.language or "en"
    should_generate_title = not recording.title
    audio_duration_seconds = _audio_duration_seconds(staged_path, content_type)
    logger.info(
        "audio processing started recording_id=%s content_type=%s staged_size_bytes=%s "
        "client_file_size_bytes=%s audio_duration_seconds=%s client_duration_seconds=%s",
        recording_id,
        content_type,
        staged_size_bytes,
        client_file_size_bytes,
        audio_duration_seconds,
        client_duration_seconds,
    )
    if _audio_is_too_short_for_file_stt(audio_duration_seconds):
        recording.duration_seconds = _duration_seconds_from_sources(
            audio_duration_seconds=audio_duration_seconds,
            client_duration_seconds=client_duration_seconds,
            transcript_end_ms=None,
        )
        apply_no_speech_failure(recording, user_default_language)
        await db.commit()
        delete_staged_file(staged_path)
        logger.warning(
            "audio processing rejected too-short audio before provider call "
            "recording_id=%s audio_duration_seconds=%s staged_size_bytes=%s",
            recording_id,
            audio_duration_seconds,
            staged_size_bytes,
        )
        _recording_lifecycle_breadcrumb(
            "Recording processing rejected too-short audio",
            recording_id=recording_id,
            level="warning",
            data={
                "audio_duration_seconds": audio_duration_seconds,
                "staged_size_bytes": staged_size_bytes,
            },
        )
        return
    _recording_lifecycle_breadcrumb(
        "Recording processing started",
        recording_id=recording_id,
        data={
            "content_type": content_type,
            "staged_size_bytes": staged_size_bytes,
            "client_file_size_bytes": client_file_size_bytes,
            "audio_duration_seconds": audio_duration_seconds,
            "client_duration_seconds": client_duration_seconds,
        },
    )
    await db.commit()

    if not staged_path.exists():
        logger.error(
            "audio processing staged file missing recording_id=%s staged_size_bytes=%s",
            recording_id,
            staged_size_bytes,
        )
        await mark_recording_processing_failed(
            db,
            recording_id=recording_id,
            failure_code="staged_file_missing",
            failure_message="Uploaded audio file was missing before processing.",
        )
        capture_sentry_anomaly(
            "recording.staged_file.missing",
            "Recording staged audio file was missing before processing",
            category="recording",
            extras={
                "recording_id": str(recording_id),
                "staged_size_bytes": staged_size_bytes,
                "content_type": content_type,
            },
            level="error",
        )
        return

    # Idempotency: if a prior run already transcribed this recording (segments
    # exist), a requeued / retried / duplicate-delivered task must NOT re-call
    # Deepgram for the same audio. This is the primary guard against the
    # 2026-05-31 batch cost incident (worker-loss requeue + visibility-timeout
    # redelivery re-transcribing the same long recordings many times).
    already_transcribed = await db.execute(
        select(Segment.id).where(Segment.recording_id == recording_id).limit(1)
    )
    if already_transcribed.first() is not None:
        logger.info(
            "skipping re-transcription; recording already has segments recording_id=%s",
            recording_id,
        )
        capture_sentry_anomaly(
            "recording.transcription.duplicate_skipped",
            "Skipped re-transcription of an already-transcribed recording",
            category="recording",
            extras={"recording_id": str(recording_id)},
            level="warning",
        )
        recording.status = RecordingStatus.READY.value
        recording.failure_code = None
        recording.failure_message = None
        await db.commit()
        await start_recording_summary_generation_job(
            db,
            recording_id=recording_id,
            user_id=user_id,
            enqueue=_enqueue_recording_summary_generation,
            skip_if_summary_exists=True,
            raise_on_enqueue_error=False,
        )
        delete_staged_file(staged_path)
        return

    try:
        await reset_recording_processing_state(recording_id, db)

        # NOTE: reads the full staged file into memory for the multipart
        # upload. Bounded by the 200 MB upload cap — safe for a single-task
        # Celery worker with ≥1 GB RAM.
        with staged_path.open("rb") as staged_file:
            _recording_lifecycle_breadcrumb(
                "Recording file transcription started",
                recording_id=recording_id,
                data={
                    "content_type": content_type,
                    "audio_duration_seconds": audio_duration_seconds,
                    "client_duration_seconds": client_duration_seconds,
                    "staged_size_bytes": staged_size_bytes,
                },
            )
            keyterms = await load_user_keyterms(db, user_id=user_id, purpose="recording")
            deepgram_addons = ["speaker_diarization"]
            if keyterms:
                deepgram_addons.append("keyterm_prompting")
            audio_data = staged_file.read()
            provider_audio_seconds = _provider_audio_seconds(
                audio_duration_seconds=audio_duration_seconds,
                client_duration_seconds=client_duration_seconds,
            )
            file_stt_started_at = time.perf_counter()
            try:
                transcript_results = await transcribe_audio_file(
                    audio_data,
                    language=recording_language,
                    content_type=content_type,
                    audio_duration_seconds=provider_audio_seconds,
                    keyterms=keyterms,
                    user_id=str(user_id),
                    usage_purpose="recording",
                )
            except TranscriptionGuardError as exc:
                await record_deepgram_usage_event(
                    db,
                    user_id=user_id,
                    recording_id=recording_id,
                    operation="file_stt",
                    purpose="recording",
                    status="refused",
                    model=DEFAULT_FILE_STT_MODEL,
                    language=recording_language,
                    content_type=content_type,
                    audio_seconds=provider_audio_seconds,
                    billable_seconds=0,
                    channel_count=1,
                    audio_bytes=len(audio_data),
                    latency_ms=round((time.perf_counter() - file_stt_started_at) * 1000),
                    guard_code=exc.code,
                    billing_mode="pre_recorded",
                    language_mode="multilingual",
                    addons=deepgram_addons,
                    commit=True,
                )
                raise
            except httpx.HTTPStatusError as exc:
                await record_deepgram_usage_event(
                    db,
                    user_id=user_id,
                    recording_id=recording_id,
                    operation="file_stt",
                    purpose="recording",
                    status="failed",
                    model=DEFAULT_FILE_STT_MODEL,
                    language=recording_language,
                    content_type=content_type,
                    audio_seconds=provider_audio_seconds,
                    billable_seconds=0,
                    channel_count=1,
                    audio_bytes=len(audio_data),
                    latency_ms=round((time.perf_counter() - file_stt_started_at) * 1000),
                    provider_status_code=exc.response.status_code,
                    provider_error_code=provider_error_code(exc),
                    error_type=type(exc).__name__,
                    billing_mode="pre_recorded",
                    language_mode="multilingual",
                    addons=deepgram_addons,
                    commit=True,
                )
                raise
            except Exception as exc:
                await record_deepgram_usage_event(
                    db,
                    user_id=user_id,
                    recording_id=recording_id,
                    operation="file_stt",
                    purpose="recording",
                    status="failed",
                    model=DEFAULT_FILE_STT_MODEL,
                    language=recording_language,
                    content_type=content_type,
                    audio_seconds=provider_audio_seconds,
                    billable_seconds=0,
                    channel_count=1,
                    audio_bytes=len(audio_data),
                    latency_ms=round((time.perf_counter() - file_stt_started_at) * 1000),
                    error_type=type(exc).__name__,
                    billing_mode="pre_recorded",
                    language_mode="multilingual",
                    addons=deepgram_addons,
                    commit=True,
                )
                raise
            else:
                await record_deepgram_usage_event(
                    db,
                    user_id=user_id,
                    recording_id=recording_id,
                    operation="file_stt",
                    purpose="recording",
                    status="succeeded",
                    model=DEFAULT_FILE_STT_MODEL,
                    language=recording_language,
                    content_type=content_type,
                    audio_seconds=provider_audio_seconds,
                    billable_seconds=effective_billable_seconds(
                        audio_seconds=provider_audio_seconds,
                        channel_count=1,
                    ),
                    channel_count=1,
                    audio_bytes=len(audio_data),
                    latency_ms=round((time.perf_counter() - file_stt_started_at) * 1000),
                    billing_mode="pre_recorded",
                    language_mode="multilingual",
                    addons=deepgram_addons,
                    commit=True,
                )
        _recording_lifecycle_breadcrumb(
            "Recording file transcription completed",
            recording_id=recording_id,
            data={
                "segment_count": len(transcript_results),
                "content_type": content_type,
                "audio_duration_seconds": audio_duration_seconds,
                "client_duration_seconds": client_duration_seconds,
            },
        )

        speech_transcript_results = _speech_results(transcript_results)
        if not speech_transcript_results:
            max_end_ms = max((result.end_ms for result in transcript_results), default=None)
            recording.duration_seconds = _duration_seconds_from_sources(
                audio_duration_seconds=audio_duration_seconds,
                client_duration_seconds=client_duration_seconds,
                transcript_end_ms=max_end_ms,
            )
            _log_transcript_coverage(
                recording_id=recording_id,
                audio_duration_seconds=audio_duration_seconds,
                client_duration_seconds=client_duration_seconds,
                transcript_end_ms=max_end_ms,
                segment_count=0,
            )
            apply_no_speech_failure(recording, user_default_language)
            await db.commit()
            delete_staged_file(staged_path)
            logger.warning("audio processing failed with empty transcript")
            effective_duration = _effective_duration_seconds(
                audio_duration_seconds=audio_duration_seconds,
                client_duration_seconds=client_duration_seconds,
                transcript_end_ms=max_end_ms,
            )
            if effective_duration is not None and effective_duration >= 10:
                capture_sentry_anomaly(
                    "recording.transcript.empty",
                    "Recording processing produced an empty transcript",
                    category="recording",
                    extras={
                        "recording_id": str(recording_id),
                        "audio_duration_seconds": audio_duration_seconds,
                        "client_duration_seconds": client_duration_seconds,
                        "effective_duration_seconds": effective_duration,
                        "segment_count": len(transcript_results),
                    },
                )
            return

        max_end_ms = max(transcript.end_ms for transcript in speech_transcript_results)
        effective_duration = _effective_duration_seconds(
            audio_duration_seconds=audio_duration_seconds,
            client_duration_seconds=client_duration_seconds,
            transcript_end_ms=max_end_ms,
        )
        transcript_text = " ".join(
            transcript.text for transcript in speech_transcript_results if transcript.text.strip()
        )

        persisted_segments: list[Segment] = []
        for transcript in speech_transcript_results:
            text = transcript.text.strip()
            segment = Segment(
                recording_id=recording_id,
                speaker=transcript.speaker,
                raw_label=transcript.speaker,
                content=text,
                start_ms=transcript.start_ms,
                end_ms=transcript.end_ms,
                confidence=transcript.confidence,
            )
            db.add(segment)
            persisted_segments.append(segment)

        recording.duration_seconds = _duration_seconds_from_sources(
            audio_duration_seconds=audio_duration_seconds,
            client_duration_seconds=client_duration_seconds,
            transcript_end_ms=max_end_ms,
        )
        _log_transcript_coverage(
            recording_id=recording_id,
            audio_duration_seconds=audio_duration_seconds,
            client_duration_seconds=client_duration_seconds,
            transcript_end_ms=max_end_ms,
            segment_count=len(speech_transcript_results),
        )
        recording.status = RecordingStatus.READY.value
        recording.failure_code = None
        recording.failure_message = None
        await record_recording_transcript_words(db, recording, transcript_text)
        await db.commit()
        await start_recording_summary_generation_job(
            db,
            recording_id=recording_id,
            user_id=user_id,
            enqueue=_enqueue_recording_summary_generation,
            skip_if_summary_exists=True,
            raise_on_enqueue_error=False,
        )
        _recording_lifecycle_breadcrumb(
            "Recording transcript persisted",
            recording_id=recording_id,
            data={
                "duration_seconds": recording.duration_seconds,
                "segment_count": len(speech_transcript_results),
            },
        )

        voice_identification_enabled = voice_identification_enabled_for_audio(
            recording_id=recording_id,
            duration_seconds=effective_duration,
            staged_size_bytes=(
                staged_size_bytes
                if staged_size_bytes is not None
                else client_file_size_bytes
            ),
        )
        speaker_assignments: dict[str, tuple[UUID, float] | None] = {}
        try:
            speaker_assignments = await identify_speakers_for_recording(
                db=db,
                user_id=user_id,
                staged_audio_path=staged_path,
                transcript_results=speech_transcript_results,
                enabled=voice_identification_enabled,
                source_recording_id=recording_id,
            )
            _recording_lifecycle_breadcrumb(
                "Recording voice identification completed",
                recording_id=recording_id,
                data={
                    "speaker_count": len(speaker_assignments),
                    "enabled": voice_identification_enabled,
                },
            )
        except Exception as exc:
            logger.warning(
                "Voice identification failed; segments will keep person_id=NULL "
                "error_type=%s error_fingerprint=%s",
                type(exc).__name__,
                fingerprint_text(str(exc)),
            )
            capture_sentry_anomaly(
                "recording.voice_identification.degraded",
                "Recording completed with degraded voice identification",
                category="recording",
                extras={
                    "recording_id": str(recording_id),
                    "error_type": type(exc).__name__,
                    "error_fingerprint": fingerprint_text(str(exc)),
                    "segment_count": len(speech_transcript_results),
                },
            )

        # Name-introduction parsing runs after voice ID so that clusters which
        # voice-matched against an existing Person keep that match and only
        # gain the introduced name as an alias. Clusters with no voice match
        # get a fresh Person created from the introduction.
        try:
            raw_labels = {
                transcript.speaker
                for transcript in speech_transcript_results
                if transcript.speaker
            }
            extracted_names = await extract_speaker_names(
                transcript_results=speech_transcript_results,
                raw_labels=raw_labels,
            )
            if extracted_names:
                applied = await apply_extracted_names(
                    db=db,
                    user_id=user_id,
                    speaker_assignments=speaker_assignments,
                    extracted=extracted_names,
                    recording_id=recording_id,
                )
                _recording_lifecycle_breadcrumb(
                    "Recording name extraction applied",
                    recording_id=recording_id,
                    data={"applied_count": len(applied)},
                )
        except Exception as exc:
            logger.warning(
                "Speaker name extraction failed error_type=%s",
                type(exc).__name__,
            )

        for segment in persisted_segments:
            assignment = (
                speaker_assignments.get(segment.raw_label) if segment.raw_label else None
            )
            if assignment is None:
                continue
            assigned_person_id, match_confidence = assignment
            segment.person_id = assigned_person_id
            segment.auto_assigned = assigned_person_id is not None
            segment.match_confidence = match_confidence

        if should_generate_title and transcript_text.strip():
            try:
                recording.title = await generate_title(
                    transcript_text,
                    language=recording.language or "auto",
                )
            except Exception as exc:
                logger.warning("Title generation failed: %s", exc)
                capture_sentry_anomaly(
                    "recording.title_generation.degraded",
                    "Recording completed with degraded title generation",
                    category="recording",
                    extras={
                        "recording_id": str(recording_id),
                        "error_type": type(exc).__name__,
                        "error_fingerprint": fingerprint_text(str(exc)),
                    },
                )
                recording.title = None

        await db.commit()
        delete_staged_file(staged_path)

        embedding_failure_count = 0
        for segment in persisted_segments:
            text = segment.content.strip()
            if not text:
                continue
            try:
                segment.embedding = await generate_embedding(
                    text,
                    usage_user_id=user_id,
                    usage_recording_id=recording_id,
                    usage_feature="recording",
                    usage_operation="embedding.segment",
                )
            except Exception as exc:
                embedding_failure_count += 1
                logger.warning(
                    "Failed to generate embedding error_type=%s error_fingerprint=%s",
                    type(exc).__name__,
                    fingerprint_text(str(exc)),
                )

        await db.commit()
        if embedding_failure_count:
            alert_data = {
                "alert_code": "recording.embeddings.degraded",
                "recording_id": str(recording_id),
                "failed_segments": embedding_failure_count,
                "segment_count": len(speech_transcript_results),
            }
            add_sentry_breadcrumb(
                category="recording",
                message="Recording completed with degraded semantic embeddings",
                level="warning",
                data=alert_data,
            )
            capture_sentry_message(
                "Recording completed with degraded semantic embeddings",
                level="warning",
                extras=alert_data,
            )
        processing_latency_ms = round((perf_counter() - processing_started_at) * 1000)
        _recording_lifecycle_breadcrumb(
            "Recording processing completed",
            recording_id=recording_id,
            data={
                "latency_ms": processing_latency_ms,
                "audio_duration_seconds": audio_duration_seconds,
                "client_duration_seconds": client_duration_seconds,
                "duration_seconds": recording.duration_seconds,
                "segment_count": len(speech_transcript_results),
                "embedding_failure_count": embedding_failure_count,
            },
        )
        _capture_processing_slow_if_needed(
            recording_id=recording_id,
            latency_ms=processing_latency_ms,
            audio_duration_seconds=audio_duration_seconds,
            client_duration_seconds=client_duration_seconds,
            staged_size_bytes=staged_size_bytes,
            segment_count=len(speech_transcript_results),
            transcript_end_ms=max_end_ms,
        )
        logger.info("audio processing completed latency_ms=%s", processing_latency_ms)
    except TranscriptionGuardError as exc:
        await db.rollback()
        logger.warning(
            "recording transcription refused by cost/abuse guard recording_id=%s code=%s",
            recording_id,
            exc.code,
        )
        capture_sentry_anomaly(
            "recording.transcription.guard_refused",
            "Batch transcription refused by a Deepgram cost/abuse guard",
            category="recording",
            extras={"recording_id": str(recording_id), "guard_code": exc.code},
            level="warning",
        )
        await mark_recording_processing_failed(
            db,
            recording_id=recording_id,
            failure_code=exc.code,
            failure_message=exc.message,
        )
        delete_staged_file(staged_path)
        return
    except Exception as exc:
        await db.rollback()
        if _provider_reported_audio_too_short(exc):
            failed = await db.get(Recording, recording_id)
            if failed is not None:
                failed.duration_seconds = _duration_seconds_from_sources(
                    audio_duration_seconds=audio_duration_seconds,
                    client_duration_seconds=client_duration_seconds,
                    transcript_end_ms=None,
                )
                apply_no_speech_failure(failed, user_default_language)
                await db.commit()
            delete_staged_file(staged_path)
            logger.warning(
                "audio processing marked too-short provider rejection as no speech "
                "recording_id=%s audio_duration_seconds=%s staged_size_bytes=%s",
                recording_id,
                audio_duration_seconds,
                staged_size_bytes,
            )
            _recording_lifecycle_breadcrumb(
                "Recording processing mapped provider audio-too-short to no speech",
                recording_id=recording_id,
                level="warning",
                data={
                    "audio_duration_seconds": audio_duration_seconds,
                    "staged_size_bytes": staged_size_bytes,
                },
            )
            return
        if is_retryable_exception(exc):
            logger.warning(
                "Recording processing hit retryable error recording_id=%s error_type=%s "
                "error_fingerprint=%s",
                recording_id,
                type(exc).__name__,
                fingerprint_text(str(exc)),
            )
            raise
        logger.exception(
            "Recording processing failed recording_id=%s error_type=%s error_fingerprint=%s",
            recording_id,
            type(exc).__name__,
            fingerprint_text(str(exc)),
        )
        capture_sentry_anomaly(
            "recording.processing.failed",
            "Recording processing failed",
            category="recording",
            extras={
                "recording_id": str(recording_id),
                "error_type": type(exc).__name__,
                "error_fingerprint": fingerprint_text(str(exc)),
                "content_type": content_type,
                "staged_size_bytes": staged_size_bytes,
            },
            level="error",
        )
        await mark_recording_processing_failed(
            db,
            recording_id=recording_id,
            failure_code="processing_failed",
            failure_message=_processing_failure_message(exc),
        )
        delete_staged_file(staged_path)
        raise


def _processing_failure_message(exc: Exception) -> str:
    del exc
    return "Imported audio processing failed"
