"""Server-side recording import pipeline shared by external integrations."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.quota import record_recording_transcript_words
from app.config import get_settings
from app.core.embeddings import generate_embedding
from app.core.summarizer import (
    SummaryResult,
    generate_title,
    resolve_highlight_timestamps,
    summarize_transcript,
)
from app.core.transcript_utils import TranscriptResult
from app.core.transcription import transcribe_audio_file
from app.core.voice_identification import identify_speakers_for_recording
from app.models.highlight import Highlight
from app.models.recording import ActionItem, Recording, RecordingStatus, Segment, Summary
from app.models.user import User

logger = logging.getLogger(__name__)
settings = get_settings()


class RecordingImportError(Exception):
    """Raised when an external media import cannot be processed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ImportedRecordingResult:
    recording: Recording
    transcript: str
    summary: Summary | None


CONTENT_TYPE_TO_EXTENSION = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
    "audio/oga": "oga",
    "audio/opus": "opus",
    "audio/webm": "webm",
    "audio/flac": "flac",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
}
EXTENSION_TO_CONTENT_TYPE = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "m4a": "audio/mp4",
    "aac": "audio/aac",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "opus": "audio/opus",
    "webm": "audio/webm",
    "flac": "audio/flac",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "mkv": "video/x-matroska",
}
SUPPORTED_AUDIO_EXTENSIONS = {"mp3", "wav", "m4a", "aac", "ogg", "oga", "opus", "webm", "flac"}
SUPPORTED_VIDEO_EXTENSIONS = {"mp4", "mov", "webm", "mkv"}
AUDIO_EXTENSIONS_REQUIRING_NORMALIZATION = {"ogg", "oga", "opus", "webm"}


def resolve_import_extension(filename: str | None, content_type: str | None) -> str:
    """Resolve a strict media extension from Telegram/file metadata."""
    name = (filename or "").strip().lower()
    suffix = Path(name).suffix.lstrip(".")
    if suffix in SUPPORTED_AUDIO_EXTENSIONS | SUPPORTED_VIDEO_EXTENSIONS:
        return suffix

    normalized_content_type = (content_type or "").split(";")[0].strip().lower()
    ext = CONTENT_TYPE_TO_EXTENSION.get(normalized_content_type)
    if ext:
        return ext

    raise RecordingImportError(
        "unsupported_file_type",
        "Поддерживаются голосовые, аудиофайлы и видеофайлы.",
    )


def _is_video_media(ext: str, content_type: str | None) -> bool:
    normalized_content_type = (content_type or "").split(";")[0].strip().lower()
    if normalized_content_type.startswith("video/"):
        return True
    if normalized_content_type.startswith("audio/"):
        return False
    return ext in SUPPORTED_VIDEO_EXTENSIONS


def _is_audio_media_requiring_normalization(ext: str, content_type: str | None) -> bool:
    normalized_content_type = (content_type or "").split(";")[0].strip().lower()
    if ext in AUDIO_EXTENSIONS_REQUIRING_NORMALIZATION:
        return True
    return normalized_content_type in {"audio/ogg", "audio/oga", "audio/opus", "audio/webm"}


def _pydub_format(ext: str) -> str | None:
    if ext == "mov":
        return None
    if ext == "oga":
        return "ogg"
    return ext


async def _normalize_media_for_transcription(
    data: bytes,
    *,
    ext: str,
    content_type: str,
) -> tuple[bytes, str, str]:
    """Extract audio from videos and normalize containers STT providers reject."""
    if not _is_video_media(ext, content_type) and not _is_audio_media_requiring_normalization(
        ext,
        content_type,
    ):
        return data, content_type, ext

    def convert() -> bytes:
        from pydub import AudioSegment

        segment = AudioSegment.from_file(BytesIO(data), format=_pydub_format(ext))
        segment = segment.set_frame_rate(16_000).set_channels(1).set_sample_width(2)
        output = BytesIO()
        segment.export(output, format="wav")
        return output.getvalue()

    try:
        wav_data = await asyncio.to_thread(convert)
    except Exception as exc:
        if _is_video_media(ext, content_type):
            raise RecordingImportError(
                "video_audio_extract_failed",
                "Не получилось извлечь звук из видео.",
            ) from exc
        raise RecordingImportError(
            "audio_decode_failed",
            "Не получилось прочитать аудио.",
        ) from exc
    return wav_data, "audio/wav", "wav"


async def _write_staged_file(
    *,
    user_id: UUID,
    recording_id: UUID,
    data: bytes,
    ext: str,
) -> Path:
    root = Path(settings.upload_staging_dir) / str(user_id)
    await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
    path = root / f"{recording_id}.{ext}"
    await asyncio.to_thread(path.write_bytes, data)
    return path


async def _delete_staged_file(path: Path) -> None:
    try:
        await asyncio.to_thread(path.unlink, missing_ok=True)
    except Exception:
        logger.warning("failed to delete staged import file")


def _is_no_speech_placeholder(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized in {
        "[no speech detected]",
        "(no speech detected)",
        "no speech detected",
        "[inaudible]",
    }


def _resolve_language(user: User, requested: str | None) -> str:
    language = (requested or user.default_language or "multi").strip().lower()
    if language in {"multi", "auto"}:
        return "auto"
    return language


def _summary_language(user: User, recording: Recording) -> str:
    preferred = (user.summary_language or "auto").strip().lower()
    if preferred not in {"", "auto", "multi"}:
        return preferred
    recording_language = (recording.language or "").strip().lower()
    if recording_language not in {"", "auto", "multi"}:
        return recording_language
    default_language = (user.default_language or "").strip().lower()
    if default_language not in {"", "auto", "multi"}:
        return default_language
    return "auto"


async def _transcribe(
    *,
    data: bytes,
    content_type: str,
    language: str,
    user: User,
) -> list[TranscriptResult]:
    return await transcribe_audio_file(
        data,
        language=language,
        content_type=content_type,
        user=user,
        provider=user.file_stt_provider,
        model=user.file_stt_model,
    )


async def _persist_segments(
    *,
    db: AsyncSession,
    user_id: UUID,
    recording: Recording,
    staged_path: Path,
    transcript_results: list[TranscriptResult],
) -> str:
    speaker_assignments: dict[str, tuple[UUID, float] | None] = {}
    try:
        speaker_assignments = await identify_speakers_for_recording(
            db=db,
            user_id=user_id,
            staged_audio_path=staged_path,
            transcript_results=transcript_results,
        )
    except Exception:
        logger.exception("voice identification failed for imported recording")

    transcript_parts: list[str] = []
    max_end_ms = 0
    for tr in transcript_results:
        text = tr.text.strip()
        if not text:
            continue
        transcript_parts.append(text)
        max_end_ms = max(max_end_ms, tr.end_ms)
        embedding = None
        try:
            embedding = await generate_embedding(text)
        except Exception:
            logger.warning("failed to generate imported segment embedding")

        assignment = speaker_assignments.get(tr.speaker) if tr.speaker else None
        assigned_person_id, match_confidence = (
            assignment if assignment is not None else (None, None)
        )
        db.add(
            Segment(
                recording_id=recording.id,
                speaker=tr.speaker,
                raw_label=tr.speaker,
                person_id=assigned_person_id,
                auto_assigned=assigned_person_id is not None,
                match_confidence=match_confidence,
                content=text,
                start_ms=tr.start_ms,
                end_ms=tr.end_ms,
                confidence=tr.confidence,
                embedding=embedding,
            )
        )

    if max_end_ms > 0:
        recording.duration_seconds = max_end_ms // 1000
    return " ".join(transcript_parts)


async def _persist_summary(
    *,
    db: AsyncSession,
    recording: Recording,
    transcript_results: list[TranscriptResult],
    summary_result: SummaryResult,
) -> Summary:
    summary = Summary(
        recording_id=recording.id,
        summary=summary_result.summary,
        key_points=summary_result.key_points,
        decisions=summary_result.decisions,
        topics=summary_result.topics,
        people_mentioned=summary_result.people_mentioned,
        sentiment=summary_result.sentiment,
    )
    db.add(summary)
    recording.summary = summary

    for item in summary_result.action_items:
        task = str(item.get("task", "")).strip()
        if not task:
            continue
        due_raw = item.get("due")
        due_date: date | None = None
        if isinstance(due_raw, date):
            due_date = due_raw
        elif isinstance(due_raw, str) and due_raw:
            try:
                due_date = date.fromisoformat(due_raw)
            except ValueError:
                due_date = None
        priority = item.get("priority", "medium")
        if priority not in {"high", "medium", "low"}:
            priority = "medium"
        db.add(
            ActionItem(
                recording_id=recording.id,
                task=task,
                owner=item.get("owner"),
                due_date=due_date,
                priority=priority,
                source="generated",
            )
        )

    raw_highlights = summary_result.highlights or []
    if raw_highlights:
        segment_dicts = [
            {"content": tr.text, "start_ms": tr.start_ms, "end_ms": tr.end_ms}
            for tr in transcript_results
        ]
        for hl in resolve_highlight_timestamps(raw_highlights, segment_dicts):
            title = str(hl.get("title", "")).strip()
            if not title:
                continue
            importance = hl.get("importance", "medium")
            if importance not in {"high", "medium", "low"}:
                importance = "medium"
            db.add(
                Highlight(
                    recording_id=recording.id,
                    category=str(hl.get("category", "insight")).strip()[:30],
                    title=title[:500],
                    description=hl.get("description"),
                    speaker=hl.get("speaker"),
                    start_ms=hl.get("start_ms"),
                    end_ms=hl.get("end_ms"),
                    importance=importance,
                )
            )

    return summary


async def _mark_failed(
    *,
    db: AsyncSession,
    recording_id: UUID,
    code: str,
    message: str,
) -> Recording | None:
    result = await db.execute(select(Recording).where(Recording.id == recording_id))
    recording = result.scalar_one_or_none()
    if recording is None:
        return None
    recording.status = RecordingStatus.FAILED.value
    recording.failure_code = code
    recording.failure_message = message
    await db.commit()
    return recording


async def import_media_as_recording(
    *,
    db: AsyncSession,
    user: User,
    data: bytes,
    filename: str | None,
    content_type: str | None,
    title: str | None,
    source_label: str,
    language: str | None = None,
) -> ImportedRecordingResult:
    """Create a library recording from external media bytes and process it."""
    if not data:
        raise RecordingImportError("empty_file", "Файл пустой.")
    logger.info("external recording import started source=%s", source_label)

    ext = resolve_import_extension(filename, content_type)
    normalized_content_type = (
        (content_type or "").split(";")[0].strip().lower()
        or EXTENSION_TO_CONTENT_TYPE.get(ext, "application/octet-stream")
    )
    media_data, media_content_type, media_ext = await _normalize_media_for_transcription(
        data,
        ext=ext,
        content_type=normalized_content_type,
    )
    now = datetime.now(timezone.utc)
    recording = Recording(
        user_id=user.id,
        title=title,
        type="note",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=now,
        language=_resolve_language(user, language),
        audio_url=None,
    )
    db.add(recording)
    await db.flush()
    recording_id = recording.id

    staged_path = await _write_staged_file(
        user_id=user.id,
        recording_id=recording_id,
        data=media_data,
        ext=media_ext,
    )
    await db.commit()

    try:
        await db.execute(delete(Summary).where(Summary.recording_id == recording.id))
        await db.execute(delete(Segment).where(Segment.recording_id == recording.id))
        await db.execute(delete(ActionItem).where(ActionItem.recording_id == recording.id))
        await db.execute(delete(Highlight).where(Highlight.recording_id == recording.id))

        transcript_results = await _transcribe(
            data=media_data,
            content_type=media_content_type,
            language=recording.language or "auto",
            user=user,
        )
        speech_results = [
            tr
            for tr in transcript_results
            if tr.text.strip() and not _is_no_speech_placeholder(tr.text)
        ]
        if not speech_results:
            recording.status = RecordingStatus.READY.value
            recording.failure_code = None
            recording.failure_message = None
            await db.commit()
            await _delete_staged_file(staged_path)
            return ImportedRecordingResult(recording=recording, transcript="", summary=None)

        transcript = await _persist_segments(
            db=db,
            user_id=user.id,
            recording=recording,
            staged_path=staged_path,
            transcript_results=speech_results,
        )
        if not recording.title and transcript.strip():
            try:
                recording.title = await generate_title(
                    transcript,
                    language=recording.language or "auto",
                )
            except Exception:
                logger.exception("title generation failed for imported recording")

        summary_result = await summarize_transcript(
            "\n".join(
                f"{tr.speaker or 'Speaker'}: {tr.text}" for tr in speech_results
            ),
            language=_summary_language(user, recording),
            style=user.summary_style,
            instructions=user.summary_instructions,
        )
        summary = await _persist_summary(
            db=db,
            recording=recording,
            transcript_results=speech_results,
            summary_result=summary_result,
        )
        recording.status = RecordingStatus.READY.value
        recording.failure_code = None
        recording.failure_message = None
        await record_recording_transcript_words(db, recording, transcript)
        await db.commit()
        await db.refresh(recording)
        await db.refresh(summary)
        return ImportedRecordingResult(
            recording=recording,
            transcript=transcript,
            summary=summary,
        )
    except RecordingImportError as exc:
        await db.rollback()
        await _mark_failed(
            db=db,
            recording_id=recording_id,
            code=exc.code,
            message=exc.message,
        )
        raise RecordingImportError(exc.code, exc.message) from exc
    except Exception as exc:
        logger.exception("external recording import failed")
        await db.rollback()
        failed = await _mark_failed(
            db=db,
            recording_id=recording_id,
            code="processing_failed",
            message="Не получилось обработать файл.",
        )
        if failed is not None:
            recording = failed
        raise RecordingImportError("processing_failed", "Не получилось обработать файл.") from exc
    finally:
        await _delete_staged_file(staged_path)
