"""Server-side recording import pipeline shared by external integrations."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import UUID

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.quota import record_recording_transcript_words
from app.config import get_settings
from app.core.content import with_title_context
from app.core.deepgram_usage import (
    effective_billable_seconds,
    provider_error_code,
    record_deepgram_usage_event,
)
from app.core.embeddings import generate_embedding, generate_embeddings
from app.core.error_sanitizer import sanitize_failure_message
from app.core.observability import capture_sentry_anomaly, fingerprint_text
from app.core.personalization import (
    load_user_keyterms,
    load_user_replacements,
    summary_personalization_instructions,
)
from app.core.recording_audio_processing import (
    apply_no_speech_failure,
    voice_identification_enabled_for_audio,
)
from app.core.retry_policy import is_openai_insufficient_quota, is_retryable_exception
from app.core.speaker_name_extraction import (
    apply_extracted_names,
    extract_speaker_names,
)
from app.core.summarizer import (
    SummaryResult,
    resolve_highlight_timestamps,
    summarize_transcript,
)
from app.core.summary_generation import combine_summary_instructions
from app.core.transcript_utils import TranscriptResult
from app.core.transcription import transcribe_audio_file
from app.core.transcription_guard import TranscriptionGuardError
from app.core.transcription_options import DEFAULT_FILE_STT_MODEL
from app.core.voice_identification import identify_speakers_for_recording
from app.models.highlight import Highlight
from app.models.person import RecordingSpeakerEmbedding
from app.models.recording import (
    ACTIVE_RECORDING_STATUSES,
    ActionItem,
    Recording,
    RecordingStatus,
    Segment,
    Summary,
)
from app.models.user import User

logger = logging.getLogger(__name__)
settings = get_settings()
SEGMENT_EMBEDDING_BATCH_SIZE = 256

TELEGRAM_IMPORT_SUMMARY_INSTRUCTIONS = """\
For Telegram voice/audio imports, the `summary` field IS the complete
Telegram-facing message. Make it scannable at a glance — NEVER a prose
paragraph. This overrides any sentence-count style rule for `summary`.

Use the transcript's dominant language. Preserve concrete dates, week numbers,
names, projects, numbers, outcomes, and commitments verbatim.

First decide what KIND of recording this is, then structure `summary` for it:
- plan / to-do: group the tasks under short thematic section headers; LEAD with
  the concrete actions and put any context after them.
- meeting / call: lead with Decisions and Action items (who does what by when),
  then Open questions.
- lecture / talk: a short outline of the topics with the key takeaways.
- weekly reflection: the four sections Что понравилось / Что не понравилось /
  Что продолжать / Что изменить.
- note / idea / other: the key points, most important first.

Telegram formatting for `summary`:
- Start each section with a short bold header in Markdown, e.g. **1) Продажи**.
- Put the items under a header on their own lines starting with "- ".
- Most actionable content first; no greeting, no preamble, no meta-commentary.
- Length follows the content: a one-line note stays one line — never pad to a
  target length, never invent detail to fill sections.
"""

MEDIA_RECORDING_SUMMARY_INSTRUCTIONS = """\
For video recordings, summarize like a detailed media analyst, not like a short
meeting note. This applies to the `summary`, `key_points`, and `highlights`
fields.

Video/media summary quality rules:
- Overall overview: start with the complete source's main topic, purpose, and
  conclusion before listing details.
- Highlight crucial data: preserve important quotes, names, dates, numbers,
  metrics, examples, claims, and conclusions verbatim.
- Identify key points: cover the significant ideas and changes in direction
  across the whole transcript, not only the opening.
- Timestamps and section summaries: when the transcript has time-coded segments,
  describe the main sections in chronological order so highlights can map back
  to the source moments.
- Preserve the source tone, style, and language while keeping the result easy to
  skim.
"""


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


@dataclass(frozen=True)
class TranscribedMedia:
    """Normalised media bytes plus their transcript, produced WITHOUT persisting a
    recording. Lets a caller transcribe once to inspect what was said (intent
    routing), then either feed the text to the agent or hand these results back to
    ``import_media_as_recording(precomputed=...)`` so the audio is never transcribed
    twice."""

    transcript_results: list[TranscriptResult]
    media_data: bytes
    media_content_type: str
    media_ext: str

    @property
    def speech_results(self) -> list[TranscriptResult]:
        return [
            tr
            for tr in self.transcript_results
            if tr.text.strip() and not _is_no_speech_placeholder(tr.text)
        ]

    @property
    def has_speech(self) -> bool:
        return bool(self.speech_results)

    @property
    def transcript_text(self) -> str:
        """Plain spoken text (no speaker labels) for classification / chat input."""
        return " ".join(tr.text.strip() for tr in self.speech_results).strip()


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


def _is_video_summary_kind(media_kind: str | None) -> bool:
    return (media_kind or "").strip().lower() == "video"


def _summary_instructions(
    user: User,
    *,
    source_label: str,
    media_kind: str | None = None,
) -> str | None:
    blocks: list[str] = []
    instructions = (user.summary_instructions or "").strip()
    if instructions:
        blocks.append(instructions)
    if source_label == "telegram":
        blocks.append(TELEGRAM_IMPORT_SUMMARY_INSTRUCTIONS)
    if _is_video_summary_kind(media_kind):
        blocks.append(MEDIA_RECORDING_SUMMARY_INSTRUCTIONS)
    return "\n\n".join(blocks) or None


def _summary_style(
    user: User,
    *,
    source_label: str,
    media_kind: str | None = None,
) -> str:
    if source_label == "telegram" or _is_video_summary_kind(media_kind):
        # Structure-first (no sentence-count) so the model groups the summary into
        # scannable sections instead of the prose paragraph short styles produce.
        return "structured"
    return user.summary_style


def _speaker_roster_instructions(speaker_names: dict[str, str]) -> str | None:
    """Instruct the summarizer to attribute owners to the resolved speaker names."""
    names = [name for name in dict.fromkeys(speaker_names.values()) if name]
    if not names:
        return None
    listed = ", ".join(names)
    return (
        f"Named speakers in this recording: {listed}. Use these names verbatim. "
        "For each action item set `owner` to the named speaker who commits to or is "
        "assigned the task; if the owner is genuinely unclear, leave owner null — "
        "never guess. Attribute decisions and highlights to the named speaker when "
        "the transcript makes it clear."
    )


def _labeled_summary_transcript(
    transcript_results: list[TranscriptResult],
    speaker_names: dict[str, str],
) -> str:
    """Diarized transcript with raw speaker labels replaced by resolved names."""
    lines: list[str] = []
    for tr in transcript_results:
        label = speaker_names.get(tr.speaker or "", "") or tr.speaker or "Speaker"
        lines.append(f"{label}: {tr.text}")
    return "\n".join(lines)


def _duration_seconds_from_media_or_transcript(
    *,
    media_duration_seconds: float | None,
    transcript_end_ms: int,
) -> int | None:
    if media_duration_seconds is not None and media_duration_seconds > 0:
        return max(math.ceil(media_duration_seconds), 1)
    if transcript_end_ms > 0:
        return transcript_end_ms // 1000
    return None


async def _transcribe(
    *,
    db: AsyncSession,
    data: bytes,
    content_type: str,
    language: str,
    user: User,
    audio_duration_seconds: float | None = None,
    recording_id: UUID | None = None,
    source_label: str = "upload",
) -> list[TranscriptResult]:
    keyterms = await load_user_keyterms(db, user_id=user.id, purpose="recording")
    replacements = await load_user_replacements(db, user_id=user.id)
    deepgram_addons = ["speaker_diarization"]
    if keyterms:
        deepgram_addons.append("keyterm_prompting")
    started_at = time.perf_counter()
    try:
        results = await transcribe_audio_file(
            data,
            language=language,
            content_type=content_type,
            keyterms=keyterms,
            replacements=replacements,
            user_id=str(user.id),
            audio_duration_seconds=audio_duration_seconds,
            usage_purpose=source_label,
        )
    except TranscriptionGuardError as exc:
        await record_deepgram_usage_event(
            db,
            user_id=user.id,
            recording_id=recording_id,
            operation="file_stt",
            purpose=source_label,
            status="refused",
            model=DEFAULT_FILE_STT_MODEL,
            language=language,
            content_type=content_type,
            audio_seconds=audio_duration_seconds,
            billable_seconds=0,
            channel_count=1,
            audio_bytes=len(data),
            latency_ms=round((time.perf_counter() - started_at) * 1000),
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
            user_id=user.id,
            recording_id=recording_id,
            operation="file_stt",
            purpose=source_label,
            status="failed",
            model=DEFAULT_FILE_STT_MODEL,
            language=language,
            content_type=content_type,
            audio_seconds=audio_duration_seconds,
            billable_seconds=0,
            channel_count=1,
            audio_bytes=len(data),
            latency_ms=round((time.perf_counter() - started_at) * 1000),
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
            user_id=user.id,
            recording_id=recording_id,
            operation="file_stt",
            purpose=source_label,
            status="failed",
            model=DEFAULT_FILE_STT_MODEL,
            language=language,
            content_type=content_type,
            audio_seconds=audio_duration_seconds,
            billable_seconds=0,
            channel_count=1,
            audio_bytes=len(data),
            latency_ms=round((time.perf_counter() - started_at) * 1000),
            error_type=type(exc).__name__,
            billing_mode="pre_recorded",
            language_mode="multilingual",
            addons=deepgram_addons,
            commit=True,
        )
        raise
    await record_deepgram_usage_event(
        db,
        user_id=user.id,
        recording_id=recording_id,
        operation="file_stt",
        purpose=source_label,
        status="succeeded",
        model=DEFAULT_FILE_STT_MODEL,
        language=language,
        content_type=content_type,
        audio_seconds=audio_duration_seconds,
        billable_seconds=effective_billable_seconds(
            audio_seconds=audio_duration_seconds,
            channel_count=1,
        ),
        channel_count=1,
        audio_bytes=len(data),
        latency_ms=round((time.perf_counter() - started_at) * 1000),
        billing_mode="pre_recorded",
        language_mode="multilingual",
        addons=deepgram_addons,
        commit=True,
    )
    return results


async def _persist_segments(
    *,
    db: AsyncSession,
    user_id: UUID,
    recording: Recording,
    staged_path: Path,
    staged_size_bytes: int | None,
    transcript_results: list[TranscriptResult],
    duration_seconds: float | None,
) -> tuple[str, dict[str, str]]:
    max_end_ms = max((tr.end_ms for tr in transcript_results), default=0)
    recording_duration_seconds = _duration_seconds_from_media_or_transcript(
        media_duration_seconds=duration_seconds,
        transcript_end_ms=max_end_ms,
    )
    voice_identification_enabled = voice_identification_enabled_for_audio(
        recording_id=recording.id,
        duration_seconds=recording_duration_seconds,
        staged_size_bytes=staged_size_bytes,
    )
    speaker_assignments: dict[str, tuple[UUID, float] | None] = {}
    try:
        speaker_assignments = await identify_speakers_for_recording(
            db=db,
            user_id=user_id,
            staged_audio_path=staged_path,
            transcript_results=transcript_results,
            enabled=voice_identification_enabled,
            source_recording_id=recording.id,
        )
    except Exception:
        logger.exception("voice identification failed for imported recording")

    extracted_names: dict = {}
    try:
        extracted_names = await extract_speaker_names(
            transcript_results=transcript_results,
            raw_labels=speaker_assignments.keys(),
            usage_user_id=user_id,
            usage_recording_id=recording.id,
        )
        if extracted_names:
            await apply_extracted_names(
                db=db,
                user_id=user_id,
                speaker_assignments=speaker_assignments,
                extracted=extracted_names,
                recording_id=recording.id,
            )
    except Exception:
        logger.exception("speaker name extraction failed for imported recording")

    segment_rows: list[tuple[TranscriptResult, str]] = []
    transcript_parts: list[str] = []
    max_end_ms = 0
    for tr in transcript_results:
        text = tr.text.strip()
        if not text:
            continue
        transcript_parts.append(text)
        max_end_ms = max(max_end_ms, tr.end_ms)
        segment_rows.append((tr, text))

    embeddings = await _generate_imported_segment_embeddings(
        recording=recording,
        user_id=user_id,
        texts=[text for _, text in segment_rows],
    )

    for (tr, text), embedding in zip(segment_rows, embeddings, strict=True):
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

    recording.duration_seconds = recording_duration_seconds
    speaker_names = {
        label: getattr(assignment, "name", "").strip()
        for label, assignment in extracted_names.items()
        if getattr(assignment, "name", "").strip()
    }
    return " ".join(transcript_parts), speaker_names


async def _generate_imported_segment_embeddings(
    *,
    recording: Recording,
    user_id: UUID,
    texts: list[str],
) -> list[list[float] | None]:
    if not texts:
        return []
    if len(texts) == 1:
        try:
            return [
                await generate_embedding(
                    with_title_context(recording.title, texts[0]),
                    usage_user_id=user_id,
                    usage_recording_id=recording.id,
                    usage_feature="recording",
                    usage_operation="embedding.segment",
                )
            ]
        except Exception as exc:
            logger.warning(
                "failed to generate imported segment embedding error_type=%s "
                "error_fingerprint=%s",
                type(exc).__name__,
                fingerprint_text(str(exc)),
            )
            return [None]

    embeddings: list[list[float] | None] = [None] * len(texts)
    for offset in range(0, len(texts), SEGMENT_EMBEDDING_BATCH_SIZE):
        batch_texts = texts[offset : offset + SEGMENT_EMBEDDING_BATCH_SIZE]
        try:
            batch_embeddings = await generate_embeddings(
                [with_title_context(recording.title, text) for text in batch_texts],
                usage_user_id=user_id,
                usage_recording_id=recording.id,
                usage_feature="recording",
                usage_operation="embedding.segment",
            )
        except Exception as exc:
            logger.warning(
                "failed to generate imported segment embedding batch count=%s "
                "error_type=%s error_fingerprint=%s",
                len(batch_texts),
                type(exc).__name__,
                fingerprint_text(str(exc)),
            )
            if _should_stop_import_embedding_batches(exc):
                break
            continue
        if len(batch_embeddings) != len(batch_texts):
            logger.warning(
                "imported segment embedding batch returned unexpected count "
                "expected=%s actual=%s",
                len(batch_texts),
                len(batch_embeddings),
            )
            continue
        embeddings[offset : offset + len(batch_embeddings)] = batch_embeddings
    return embeddings


def _should_stop_import_embedding_batches(exc: BaseException) -> bool:
    return is_retryable_exception(exc) or is_openai_insufficient_quota(exc)


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
        # Flush so the just-persisted segments have ids, then cite each highlight
        # back to the segment it is grounded in (verifiable, attach-not-drop).
        await db.flush()
        seg_rows = (
            await db.execute(
                select(
                    Segment.id, Segment.content, Segment.start_ms, Segment.end_ms
                ).where(Segment.recording_id == recording.id)
            )
        ).all()
        segment_dicts = [
            {"id": str(s.id), "content": s.content, "start_ms": s.start_ms, "end_ms": s.end_ms}
            for s in seg_rows
        ]
        grounded_count = 0
        for hl in resolve_highlight_timestamps(raw_highlights, segment_dicts):
            title = str(hl.get("title", "")).strip()
            if not title:
                continue
            importance = hl.get("importance", "medium")
            if importance not in {"high", "medium", "low"}:
                importance = "medium"
            source_segment_ids = hl.get("source_segment_ids") or None
            if source_segment_ids:
                grounded_count += 1
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
                    source_segment_ids=source_segment_ids,
                )
            )
        logger.info(
            "highlight grounding total=%d grounded=%d",
            len(raw_highlights),
            grounded_count,
        )

    # Seed the knowledge graph from the summary's people + topics (zero extra
    # LLM cost) so imported recordings join the graph too.
    from app.core.entity_graph import seed_entities_from_summary

    await seed_entities_from_summary(
        db,
        recording.user_id,
        source_kind="recording",
        source_id=recording.id,
        people=summary_result.people_mentioned,
        topics=summary_result.topics,
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
    if recording.status not in ACTIVE_RECORDING_STATUSES:
        return recording
    recording.status = RecordingStatus.FAILED.value
    recording.failure_code = code
    recording.failure_message = sanitize_failure_message(message)
    await db.commit()
    return recording


async def _reload_recording(
    db: AsyncSession,
    *,
    recording_id: UUID,
    fallback: Recording,
) -> Recording:
    result = await db.execute(select(Recording).where(Recording.id == recording_id))
    return result.scalar_one_or_none() or fallback


def _capture_import_degraded(
    alert_code: str,
    message: str,
    *,
    recording_id: UUID | None,
    source_label: str,
    exc: Exception,
) -> None:
    capture_sentry_anomaly(
        alert_code,
        message,
        category="recording",
        extras={
            "recording_id": str(recording_id) if recording_id is not None else None,
            "source_label": source_label,
            "error_type": type(exc).__name__,
            "error_fingerprint": fingerprint_text(str(exc)),
        },
        level="warning",
    )


async def transcribe_media_bytes(
    *,
    db: AsyncSession,
    user: User,
    data: bytes,
    filename: str | None,
    content_type: str | None,
    language: str | None = None,
    duration_seconds: float | None = None,
    source_label: str = "telegram_route",
) -> TranscribedMedia:
    """Normalise + transcribe media bytes WITHOUT creating a recording.

    Flows through the same guarded ``_transcribe`` choke point as a real import (so
    the Deepgram cost/abuse guards still apply) but persists nothing. Used to read a
    voice note's content for intent routing; the returned results can be replayed
    into ``import_media_as_recording(precomputed=...)`` so the audio is transcribed
    exactly once whether it ends up filed or answered."""
    if not data:
        raise RecordingImportError("empty_file", "Файл пустой.")
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
    transcript_results = await _transcribe(
        db=db,
        data=media_data,
        content_type=media_content_type,
        language=_resolve_language(user, language) or "auto",
        user=user,
        audio_duration_seconds=duration_seconds,
        recording_id=None,
        source_label=source_label,
    )
    return TranscribedMedia(
        transcript_results=transcript_results,
        media_data=media_data,
        media_content_type=media_content_type,
        media_ext=media_ext,
    )


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
    duration_seconds: float | None = None,
    recording: Recording | None = None,
    precomputed: TranscribedMedia | None = None,
) -> ImportedRecordingResult:
    """Create a library recording from external media bytes and process it.

    When ``precomputed`` is supplied the media has already been normalised and
    transcribed by ``transcribe_media_bytes`` (intent routing): reuse those bytes
    and transcript instead of paying for a second normalise + STT pass."""
    if not data:
        raise RecordingImportError("empty_file", "Файл пустой.")
    logger.info("external recording import started source=%s", source_label)

    recording_id: UUID | None = recording.id if recording is not None else None
    staged_path: Path | None = None

    try:
        ext = resolve_import_extension(filename, content_type)
        normalized_content_type = (
            (content_type or "").split(";")[0].strip().lower()
            or EXTENSION_TO_CONTENT_TYPE.get(ext, "application/octet-stream")
        )
        media_kind = "video" if _is_video_media(ext, normalized_content_type) else "audio"
        explicit_title = bool((title or "").strip())
        if precomputed is not None:
            media_data = precomputed.media_data
            media_content_type = precomputed.media_content_type
            media_ext = precomputed.media_ext
        else:
            media_data, media_content_type, media_ext = await _normalize_media_for_transcription(
                data,
                ext=ext,
                content_type=normalized_content_type,
            )
        now = datetime.now(timezone.utc)
        if recording is None:
            recording = Recording(
                user_id=user.id,
                title=title,
                title_auto_generated=not explicit_title,
                type="note",
                status=RecordingStatus.PROCESSING.value,
                uploaded_at=now,
                language=_resolve_language(user, language),
                audio_url=None,
            )
            db.add(recording)
        else:
            if title is not None:
                recording.title = title
                recording.title_auto_generated = not explicit_title
            recording.status = RecordingStatus.PROCESSING.value
            recording.uploaded_at = now
            recording.language = _resolve_language(user, language)
            recording.audio_url = None
            recording.failure_code = None
            recording.failure_message = None
        await db.flush()
        recording_id = recording.id

        staged_path = await _write_staged_file(
            user_id=user.id,
            recording_id=recording_id,
            data=media_data,
            ext=media_ext,
        )
        await db.commit()

        await db.execute(delete(Summary).where(Summary.recording_id == recording.id))
        await db.execute(delete(Segment).where(Segment.recording_id == recording.id))
        await db.execute(
            delete(RecordingSpeakerEmbedding).where(
                RecordingSpeakerEmbedding.recording_id == recording.id
            )
        )
        await db.execute(delete(ActionItem).where(ActionItem.recording_id == recording.id))
        await db.execute(delete(Highlight).where(Highlight.recording_id == recording.id))

        if precomputed is not None:
            transcript_results = precomputed.transcript_results
        else:
            transcript_results = await _transcribe(
                db=db,
                data=media_data,
                content_type=media_content_type,
                language=recording.language or "auto",
                user=user,
                audio_duration_seconds=duration_seconds,
                recording_id=recording_id,
                source_label=source_label,
            )
        speech_results = [
            tr
            for tr in transcript_results
            if tr.text.strip() and not _is_no_speech_placeholder(tr.text)
        ]
        if not speech_results:
            apply_no_speech_failure(recording, user.default_language)
            await db.commit()
            await _delete_staged_file(staged_path)
            return ImportedRecordingResult(recording=recording, transcript="", summary=None)

        transcript, speaker_names = await _persist_segments(
            db=db,
            user_id=user.id,
            recording=recording,
            staged_path=staged_path,
            staged_size_bytes=len(media_data),
            transcript_results=speech_results,
            duration_seconds=duration_seconds,
        )
        recording.status = RecordingStatus.READY.value
        recording.failure_code = None
        recording.failure_message = None
        await db.commit()
        await db.refresh(recording)
        summary_user_id = user.id
        summary_language = _summary_language(user, recording)
        summary_style = _summary_style(
            user,
            source_label=source_label,
            media_kind=media_kind,
        )
        base_summary_instructions = _summary_instructions(
            user,
            source_label=source_label,
            media_kind=media_kind,
        )

        try:
            await record_recording_transcript_words(db, recording, transcript)
            await db.commit()
            await db.refresh(recording)
        except Exception as exc:
            await db.rollback()
            logger.warning(
                "external recording billing failed after transcript persisted "
                "recording_id=%s source=%s",
                recording_id,
                source_label,
                exc_info=True,
            )
            _capture_import_degraded(
                "recording.import.billing.degraded",
                "Recording import completed with degraded billing ledger",
                recording_id=recording_id,
                source_label=source_label,
                exc=exc,
            )
            if recording_id is not None:
                recording = await _reload_recording(
                    db,
                    recording_id=recording_id,
                    fallback=recording,
                )

        summary: Summary | None = None
        try:
            summary_result = await summarize_transcript(
                _labeled_summary_transcript(speech_results, speaker_names),
                language=summary_language,
                style=summary_style,
                instructions=combine_summary_instructions(
                    base_instructions=base_summary_instructions,
                    personalization_instructions=await summary_personalization_instructions(
                        db,
                        user_id=summary_user_id,
                    ),
                    override_instructions=_speaker_roster_instructions(speaker_names),
                ),
            )
            if not explicit_title:
                generated_title = summary_result.title.strip()
                if generated_title:
                    recording.title = generated_title[:500]
            summary = await _persist_summary(
                db=db,
                recording=recording,
                transcript_results=speech_results,
                summary_result=summary_result,
            )
            await db.commit()
            await db.refresh(recording)
            await db.refresh(summary)
        except Exception as exc:
            await db.rollback()
            logger.warning(
                "external recording summary failed after transcript persisted "
                "recording_id=%s source=%s",
                recording_id,
                source_label,
                exc_info=True,
            )
            _capture_import_degraded(
                "recording.import.summary.degraded",
                "Recording import completed with degraded summary generation",
                recording_id=recording_id,
                source_label=source_label,
                exc=exc,
            )
            if recording_id is not None:
                recording = await _reload_recording(
                    db,
                    recording_id=recording_id,
                    fallback=recording,
                )
        return ImportedRecordingResult(
            recording=recording,
            transcript=transcript,
            summary=summary,
        )
    except RecordingImportError as exc:
        await db.rollback()
        if recording_id is not None:
            await _mark_failed(
                db=db,
                recording_id=recording_id,
                code=exc.code,
                message=exc.message,
            )
        raise RecordingImportError(exc.code, exc.message) from exc
    except asyncio.CancelledError:
        logger.warning("external recording import cancelled")
        await db.rollback()
        if recording_id is not None:
            failed = await _mark_failed(
                db=db,
                recording_id=recording_id,
                code="processing_cancelled",
                message="Обработка была прервана. Отправь файл ещё раз.",
            )
            if failed is not None:
                recording = failed
        raise
    except TranscriptionGuardError as exc:
        logger.warning("external recording import refused by cost/abuse guard code=%s", exc.code)
        await db.rollback()
        if recording_id is not None:
            failed = await _mark_failed(
                db=db,
                recording_id=recording_id,
                code=exc.code,
                message="Транскрипция временно недоступна. Попробуй позже.",
            )
            if failed is not None:
                recording = failed
        raise RecordingImportError(
            exc.code, "Транскрипция временно недоступна. Попробуй позже."
        ) from exc
    except Exception as exc:
        logger.exception("external recording import failed")
        await db.rollback()
        if recording_id is not None:
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
        if staged_path is not None:
            await _delete_staged_file(staged_path)
