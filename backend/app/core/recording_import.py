"""Server-side recording import pipeline shared by external integrations."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
from app.core.media_audio import (
    CONTENT_TYPE_TO_EXTENSION,
    EXTENSION_TO_CONTENT_TYPE,
    EXTRACTED_AUDIO_CONTENT_TYPE,
    EXTRACTED_AUDIO_EXT,
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
    MediaAudioExtractionError,
    extract_audio_to_flac,
    is_video_media,
    media_requires_audio_extraction,
    probe_media_duration_seconds,
)
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
from app.core.transcript_document import build_transcript_document
from app.core.transcript_utils import TranscriptResult
from app.core.transcription import transcribe_audio_file
from app.core.transcription_guard import TranscriptionGuardError
from app.core.transcription_options import DEFAULT_FILE_STT_MODEL
from app.core.voice_identification import identify_speakers_for_recording
from app.models.highlight import Highlight
from app.models.person import Person, RecordingSpeakerEmbedding
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
- meeting / call: open with ONE bold-led context line, e.g.
  **Формат встречи:** еженедельный созвон команды по подготовке к грантам.
  Then thematic sections named after what was actually discussed (e.g.
  **Юридический блок**, **Рынок и метрики (SAM/SOM)**), leading with decisions
  and commitments (who does what by when), then open questions.
- lecture / talk: a short outline of the topics with the key takeaways.
- weekly reflection: the four sections Что понравилось / Что не понравилось /
  Что продолжать / Что изменить.
- note / idea / other: the key points, most important first.

Telegram formatting for `summary`:
- Start each section with a short bold header in Markdown, e.g. **1) Продажи**.
- Put the items under a header on their own lines starting with "- ".
- Inside each bullet, wrap the 1-3 most load-bearing words in **bold** (the
  decision, the deliverable, the name) so the eye can jump between them.
- Wrap every number, amount, date, deadline, and metric in `backticks`:
  `450 руб.`, `60-70 млрд руб.`, `1000 знаков`, `до пятницы`.
- Most actionable content first; no greeting, no preamble, no meta-commentary.
- Length follows the content: a one-line note stays one line — never pad to a
  target length, never invent detail to fill sections. For long recordings
  stay under ~3500 characters by tightening bullets, not by dropping whole
  topics.
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
    # Diarized, timestamped speaker-block rendering of the same transcript —
    # what the Telegram bot attaches as the downloadable .txt.
    transcript_document: str = ""
    # Raw diarization label -> resolved display name (voice directory match or
    # in-transcript introduction). Powers the reply's participants line.
    speaker_names: dict[str, str] | None = None


@dataclass(frozen=True)
class TranscribedMedia:
    """Normalised on-disk media plus its transcript, produced WITHOUT persisting a
    recording. Lets a caller transcribe once to inspect what was said (intent
    routing), then either feed the text to the agent or hand these results back to
    ``import_media_as_recording(precomputed=...)`` so the audio is never transcribed
    twice. The caller owns ``media_path`` cleanup (``discard()``)."""

    transcript_results: list[TranscriptResult]
    media_path: Path
    media_content_type: str
    media_ext: str

    async def discard(self) -> None:
        await _delete_staged_file(self.media_path)

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


async def _normalize_media_file_for_transcription(
    source: Path,
    *,
    ext: str,
    content_type: str,
    dest: Path,
) -> tuple[Path, str, str]:
    """Extract audio from videos and normalize containers STT providers reject.

    File→file via ffmpeg so memory stays flat regardless of source size; returns
    the source untouched when the provider accepts it directly."""
    if not media_requires_audio_extraction(ext, content_type):
        return source, content_type, ext
    try:
        await extract_audio_to_flac(source, dest)
    except MediaAudioExtractionError as exc:
        if exc.code == "no_audio_stream":
            raise RecordingImportError(exc.code, exc.message) from exc
        if is_video_media(ext, content_type):
            raise RecordingImportError(
                "video_audio_extract_failed",
                "Не получилось извлечь звук из видео.",
            ) from exc
        raise RecordingImportError(
            "audio_decode_failed",
            "Не получилось прочитать аудио.",
        ) from exc
    return dest, EXTRACTED_AUDIO_CONTENT_TYPE, EXTRACTED_AUDIO_EXT


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
    media_path: Path,
    content_type: str,
    language: str,
    user: User,
    audio_duration_seconds: float | None = None,
    recording_id: UUID | None = None,
    source_label: str = "upload",
) -> list[TranscriptResult]:
    keyterms = await load_user_keyterms(db, user_id=user.id, purpose="recording")
    replacements = await load_user_replacements(db, user_id=user.id)
    media_size_bytes = media_path.stat().st_size
    deepgram_addons = ["speaker_diarization"]
    if keyterms:
        deepgram_addons.append("keyterm_prompting")
    started_at = time.perf_counter()
    try:
        transcription = await transcribe_audio_file(
            media_path,
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
            audio_bytes=media_size_bytes,
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
            audio_bytes=media_size_bytes,
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
            audio_bytes=media_size_bytes,
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
        audio_bytes=media_size_bytes,
        latency_ms=round((time.perf_counter() - started_at) * 1000),
        billing_mode="pre_recorded",
        language_mode="multilingual",
        addons=deepgram_addons,
        commit=True,
    )
    return transcription.segments


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
    speaker_names = await _resolve_speaker_display_names(
        db,
        speaker_assignments=speaker_assignments,
        extracted_names=extracted_names,
    )
    transcript_document = build_transcript_document(
        transcript_results,
        speaker_display_names=speaker_names,
    )
    return " ".join(transcript_parts), speaker_names, transcript_document


async def _resolve_speaker_display_names(
    db: AsyncSession,
    *,
    speaker_assignments: dict[str, tuple[UUID, float] | None],
    extracted_names: dict,
) -> dict[str, str]:
    """Map raw diarization labels to real display names.

    Voice-directory matches resolve through their Person record; direct
    in-transcript introductions ("меня зовут Аня") win over a directory match
    for the same cluster — they are the recording's own ground truth.
    """
    names: dict[str, str] = {}
    person_ids = {
        assignment[0]
        for assignment in speaker_assignments.values()
        if assignment is not None
    }
    if person_ids:
        rows = await db.execute(select(Person).where(Person.id.in_(person_ids)))
        people = {
            person.id: person.display_name.strip()
            for person in rows.scalars()
            if (person.display_name or "").strip()
        }
        for label, assignment in speaker_assignments.items():
            if assignment is None:
                continue
            display_name = people.get(assignment[0])
            if display_name:
                names[label] = display_name
    for label, assignment in extracted_names.items():
        extracted = getattr(assignment, "name", "").strip()
        if extracted:
            names[label] = extracted
    return names


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
    exactly once whether it ends up filed or answered. The caller owns the returned
    ``media_path`` and must ``discard()`` it when done."""
    if not data:
        raise RecordingImportError("empty_file", "Файл пустой.")
    ext = resolve_import_extension(filename, content_type)
    normalized_content_type = (
        (content_type or "").split(";")[0].strip().lower()
        or EXTENSION_TO_CONTENT_TYPE.get(ext, "application/octet-stream")
    )
    root = Path(settings.upload_staging_dir) / "intent" / str(user.id)
    await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
    stem = uuid4().hex
    source_path = root / f"{stem}.{ext}"
    await asyncio.to_thread(source_path.write_bytes, data)
    media_path: Path | None = None
    try:
        media_path, media_content_type, media_ext = (
            await _normalize_media_file_for_transcription(
                source_path,
                ext=ext,
                content_type=normalized_content_type,
                dest=root / f"{stem}.stt.{EXTRACTED_AUDIO_EXT}",
            )
        )
        transcript_results = await _transcribe(
            db=db,
            media_path=media_path,
            content_type=media_content_type,
            language=_resolve_language(user, language) or "auto",
            user=user,
            audio_duration_seconds=duration_seconds,
            recording_id=None,
            source_label=source_label,
        )
    except BaseException:
        if media_path is not None and media_path != source_path:
            await _delete_staged_file(media_path)
        await _delete_staged_file(source_path)
        raise
    if media_path != source_path:
        # The normalised FLAC replaces the source container; the original is
        # no longer needed for voice-ID or a later import replay.
        await _delete_staged_file(source_path)
    return TranscribedMedia(
        transcript_results=transcript_results,
        media_path=media_path,
        media_content_type=media_content_type,
        media_ext=media_ext,
    )


async def import_media_as_recording(
    *,
    db: AsyncSession,
    user: User,
    data: bytes | None = None,
    source_path: Path | None = None,
    filename: str | None,
    content_type: str | None,
    title: str | None,
    source_label: str,
    language: str | None = None,
    duration_seconds: float | None = None,
    recording: Recording | None = None,
    precomputed: TranscribedMedia | None = None,
    on_stage: Callable[[str], Awaitable[None]] | None = None,
) -> ImportedRecordingResult:
    """Create a library recording from external media and process it.

    The media arrives either as ``data`` bytes (small payloads, e.g. voice
    notes), as an on-disk ``source_path`` (large staged uploads/downloads —
    never loaded into memory; the CALLER owns that file's cleanup), or as
    ``precomputed`` — media already normalised and transcribed by
    ``transcribe_media_bytes`` (intent routing), reused so the audio is never
    transcribed twice (the caller owns ``precomputed.media_path`` too).

    ``on_stage`` (optional) is awaited at coarse progress points ("summarizing")
    so a chat frontend can live-update its status message; its failures never
    fail the import."""
    if precomputed is None and source_path is None and not data:
        raise RecordingImportError("empty_file", "Файл пустой.")
    if source_path is not None and (
        not source_path.exists() or source_path.stat().st_size == 0
    ):
        raise RecordingImportError("empty_file", "Файл пустой.")
    logger.info("external recording import started source=%s", source_label)

    recording_id: UUID | None = recording.id if recording is not None else None
    owned_paths: list[Path] = []

    try:
        ext = resolve_import_extension(filename, content_type)
        normalized_content_type = (
            (content_type or "").split(";")[0].strip().lower()
            or EXTENSION_TO_CONTENT_TYPE.get(ext, "application/octet-stream")
        )
        media_kind = "video" if is_video_media(ext, normalized_content_type) else "audio"
        explicit_title = bool((title or "").strip())
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
        # Commit the PROCESSING row before the potentially slow ffmpeg
        # extraction so no transaction stays open for minutes.
        await db.commit()

        if precomputed is not None:
            media_path = precomputed.media_path
            media_content_type = precomputed.media_content_type
        else:
            if source_path is not None:
                raw_path = source_path
            else:
                assert data is not None
                raw_path = await _write_staged_file(
                    user_id=user.id,
                    recording_id=recording_id,
                    data=data,
                    ext=ext,
                )
                owned_paths.append(raw_path)
            extraction_dest = (
                Path(settings.upload_staging_dir)
                / str(user.id)
                / f"{recording_id}.stt.{EXTRACTED_AUDIO_EXT}"
            )
            media_path, media_content_type, _media_ext = (
                await _normalize_media_file_for_transcription(
                    raw_path,
                    ext=ext,
                    content_type=normalized_content_type,
                    dest=extraction_dest,
                )
            )
            if media_path != raw_path:
                owned_paths.append(media_path)

        if duration_seconds is None:
            # Guards and billing estimates need a duration; containers carry it
            # even when the sender's metadata (web upload, forwarded file) doesn't.
            duration_seconds = await probe_media_duration_seconds(media_path)
        media_size_bytes = media_path.stat().st_size

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
                media_path=media_path,
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
            return ImportedRecordingResult(recording=recording, transcript="", summary=None)

        transcript, speaker_names, transcript_document = await _persist_segments(
            db=db,
            user_id=user.id,
            recording=recording,
            staged_path=media_path,
            staged_size_bytes=media_size_bytes,
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

        if on_stage is not None:
            with suppress(Exception):
                await on_stage("summarizing")
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
            transcript_document=transcript_document,
            speaker_names=speaker_names,
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
        for owned_path in owned_paths:
            await _delete_staged_file(owned_path)


async def regenerate_recording_summary(
    db: AsyncSession,
    *,
    recording: Recording,
    user: User,
    source_label: str = "telegram",
) -> tuple[Summary, dict[str, str]]:
    """Re-run summarization for an already-imported recording.

    Backs the Telegram retry button shown when an import finished with a
    degraded (missing) summary. Rebuilds the labeled transcript from the
    persisted segments, regenerates, and replaces the GENERATED summary
    artifacts (manual action items survive). Failures raise — callers surface
    them to the user instead of pretending success.
    """
    seg_result = await db.execute(
        select(Segment)
        .where(Segment.recording_id == recording.id)
        .order_by(Segment.start_ms)
        .options(selectinload(Segment.person))
    )
    segments = list(seg_result.scalars())
    speech_results = [
        TranscriptResult(
            text=(seg.content or "").strip(),
            speaker=seg.speaker,
            is_final=True,
            start_ms=seg.start_ms or 0,
            end_ms=seg.end_ms or 0,
            confidence=seg.confidence or 0.0,
        )
        for seg in segments
        if (seg.content or "").strip()
    ]
    if not speech_results:
        raise RecordingImportError("no_transcript", "У этой записи нет транскрипта.")
    speaker_names = {
        seg.speaker: seg.person.display_name.strip()
        for seg in segments
        if seg.speaker
        and seg.person is not None
        and (seg.person.display_name or "").strip()
    }

    summary_result = await summarize_transcript(
        _labeled_summary_transcript(speech_results, speaker_names),
        language=_summary_language(user, recording),
        style=_summary_style(user, source_label=source_label),
        instructions=combine_summary_instructions(
            base_instructions=_summary_instructions(user, source_label=source_label),
            personalization_instructions=await summary_personalization_instructions(
                db,
                user_id=user.id,
            ),
            override_instructions=_speaker_roster_instructions(speaker_names),
        ),
    )

    if not (recording.title or "").strip():
        generated_title = summary_result.title.strip()
        if generated_title:
            recording.title = generated_title[:500]
    # The recording arrives from a plain select; load the summary relationship
    # explicitly — lazy access in an async session raises MissingGreenlet.
    await db.refresh(recording, attribute_names=["summary"])
    if recording.summary is not None:
        await db.delete(recording.summary)
        recording.summary = None
    await db.execute(
        delete(ActionItem).where(
            ActionItem.recording_id == recording.id,
            ActionItem.source == "generated",
        )
    )
    await db.execute(delete(Highlight).where(Highlight.recording_id == recording.id))
    await db.flush()

    summary = await _persist_summary(
        db=db,
        recording=recording,
        transcript_results=speech_results,
        summary_result=summary_result,
    )
    await db.commit()
    await db.refresh(recording)
    await db.refresh(summary)
    return summary, speaker_names
