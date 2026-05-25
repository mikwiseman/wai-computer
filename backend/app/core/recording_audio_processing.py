"""Canonical audio-backed recording transcription processing."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.quota import record_recording_transcript_words
from app.config import get_settings
from app.core.embeddings import generate_embedding
from app.core.summarizer import generate_title
from app.core.transcript_utils import TranscriptResult
from app.core.transcription import transcribe_audio_file
from app.core.voice_identification import identify_speakers_for_recording
from app.models.highlight import Highlight
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
    recording.failure_message = copy["message"]


def delete_staged_file(path: Path | str | None) -> None:
    if path is None:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except Exception as error:
        logger.warning("Failed to delete staged audio %s: %s", path, error)


async def reset_recording_processing_state(recording_id: UUID, db: AsyncSession) -> None:
    """Replace transcript-derived data before canonical transcript generation."""
    await db.execute(
        delete(ActionItem).where(
            ActionItem.recording_id == recording_id,
            ActionItem.source == "generated",
        )
    )
    await db.execute(delete(Highlight).where(Highlight.recording_id == recording_id))
    await db.execute(delete(Summary).where(Summary.recording_id == recording_id))
    await db.execute(delete(Segment).where(Segment.recording_id == recording_id))


def _speech_results(results: list[TranscriptResult]) -> list[TranscriptResult]:
    return [
        result
        for result in results
        if result.text.strip() and not is_no_speech_placeholder(result.text)
    ]


async def process_staged_recording_upload(
    db: AsyncSession,
    *,
    recording_id: UUID,
    user_id: UUID,
    staged_path: Path,
    content_type: str,
    user_default_language: str | None,
) -> None:
    """Transcribe a staged upload and promote it as the recording's canonical transcript."""
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
        return

    recording.status = RecordingStatus.PROCESSING.value
    recording.failure_code = None
    recording.failure_message = None
    recording.audio_url = None
    recording.duration_seconds = None
    recording_language = recording.language or "en"
    should_generate_title = not recording.title
    await db.commit()

    try:
        await reset_recording_processing_state(recording_id, db)

        with staged_path.open("rb") as staged_file:
            transcript_results = await transcribe_audio_file(
                staged_file.read(),
                language=recording_language,
                content_type=content_type,
            )

        speech_transcript_results = _speech_results(transcript_results)
        if not speech_transcript_results:
            if transcript_results:
                recording.duration_seconds = max(
                    result.end_ms for result in transcript_results
                ) // 1000
            apply_no_speech_result(recording, user_default_language)
            recording.status = RecordingStatus.READY.value
            recording.failure_code = None
            await db.commit()
            delete_staged_file(staged_path)
            logger.info("audio processing completed with no speech")
            return

        speaker_assignments: dict[str, tuple[UUID, float] | None] = {}
        try:
            speaker_assignments = await identify_speakers_for_recording(
                db=db,
                user_id=user_id,
                staged_audio_path=staged_path,
                transcript_results=speech_transcript_results,
                enabled=settings.voice_identification_enabled,
            )
        except Exception:
            logger.exception("Voice identification failed; segments will keep person_id=NULL")

        for transcript in speech_transcript_results:
            text = transcript.text.strip()
            embedding = None
            if text:
                try:
                    embedding = await generate_embedding(text)
                except Exception as exc:
                    logger.warning("Failed to generate embedding: %s", exc)

            assignment = speaker_assignments.get(transcript.speaker) if transcript.speaker else None
            assigned_person_id, match_confidence = (
                assignment if assignment is not None else (None, None)
            )
            db.add(
                Segment(
                    recording_id=recording_id,
                    speaker=transcript.speaker,
                    raw_label=transcript.speaker,
                    person_id=assigned_person_id,
                    auto_assigned=assigned_person_id is not None,
                    match_confidence=match_confidence,
                    content=text,
                    start_ms=transcript.start_ms,
                    end_ms=transcript.end_ms,
                    confidence=transcript.confidence,
                    embedding=embedding,
                )
            )

        max_end_ms = max(transcript.end_ms for transcript in speech_transcript_results)
        recording.duration_seconds = max_end_ms // 1000
        transcript_text = " ".join(
            transcript.text for transcript in speech_transcript_results if transcript.text.strip()
        )

        if should_generate_title and transcript_text.strip():
            try:
                recording.title = await generate_title(
                    transcript_text,
                    language=recording.language or "auto",
                )
            except Exception as exc:
                logger.warning("Title generation failed: %s", exc)
                recording.title = None

        recording.status = RecordingStatus.READY.value
        recording.failure_code = None
        recording.failure_message = None
        await record_recording_transcript_words(db, recording, transcript_text)
        await db.commit()
        delete_staged_file(staged_path)
        logger.info("audio processing completed")
    except Exception as exc:
        logger.exception("Recording processing failed for %s", recording_id)
        await db.rollback()
        failed = await db.get(Recording, recording_id)
        if failed is not None:
            failed.status = RecordingStatus.FAILED.value
            failed.failure_code = "processing_failed"
            failed.failure_message = _processing_failure_message(exc)
            await db.commit()
        delete_staged_file(staged_path)
        raise


def _processing_failure_message(exc: Exception) -> str:
    message = str(exc).strip()
    return (message or "Imported audio processing failed")[:500]
