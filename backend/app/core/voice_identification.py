"""Speaker identification via voiceprint matching.

Given a freshly-transcribed recording (audio still on disk) and the user's
voiceprint library, returns a mapping ``raw_label -> (person_id, confidence)``
for clusters that match an existing Person above the cosine-similarity threshold.

Unmatched clusters return ``None`` — segments will save with ``person_id=NULL``
and the user can assign manually via the People API.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import delete, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import format_embedding
from app.core.voice_embedding import (
    MODEL_NAME,
    compute_voice_embedding,
    compute_voice_embedding_spans,
    pick_clean_snippet,
    pick_clean_snippets,
)
from app.models.person import Person, RecordingSpeakerEmbedding, Voiceprint
from app.models.recording import Segment

if TYPE_CHECKING:
    from app.core.transcript_utils import TranscriptResult

logger = logging.getLogger(__name__)

## ECAPA-TDNN VoxCeleb cosine thresholds.
## SpeechBrain's published EER lives around 0.25 cosine for clean speech;
## meeting audio drifts higher. 0.35 is the working baseline that lets a
## genuine same-speaker match through while keeping cross-speaker false-
## positives rare. The previous 0.6 was at the 99th percentile of same-
## speaker similarities and was the dominant cause of the "1 match in
## 1792 segments" production diagnostic.
DEFAULT_MATCH_THRESHOLD = 0.35
# Stricter for the global directory: a stranger's voice carries higher
# consequences than your own enrolled people, and the impostor cohort is
# many orders of magnitude larger.
DIRECTORY_MATCH_THRESHOLD = 0.50
VOICE_EMBEDDING_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class SpeakerVoiceEmbedding:
    """Computed voice embedding for one recording-level diarization cluster."""

    raw_label: str
    embedding: list[float]
    start_ms: int
    end_ms: int

    @property
    def duration_s(self) -> float:
        return (self.end_ms - self.start_ms) / 1000.0


@dataclass(frozen=True)
class SpeakerRematchResult:
    updated_clusters: int
    matched_clusters: int


async def identify_speakers_for_recording(
    *,
    db: AsyncSession,
    user_id: uuid.UUID,
    staged_audio_path: Path | str,
    transcript_results: list["TranscriptResult"],
    threshold: float = DEFAULT_MATCH_THRESHOLD,
    embedding_timeout_seconds: float = VOICE_EMBEDDING_TIMEOUT_SECONDS,
    enabled: bool = True,
    source_recording_id: uuid.UUID | None = None,
) -> dict[str, tuple[uuid.UUID, float] | None]:
    """Match each diarization cluster (``raw_label``) to a known Person.

    Returns a mapping from raw_label to ``(person_id, cosine_similarity)`` when a
    voiceprint above ``threshold`` is found, or ``None`` when no match exists or
    the cluster is too short for reliable identification.
    """
    raw_labels = {tr.speaker for tr in transcript_results if tr.speaker is not None}
    if not raw_labels:
        return {}
    if not enabled:
        return {raw_label: None for raw_label in sorted(raw_labels)}

    assignments: dict[str, tuple[uuid.UUID, float] | None] = {}
    speaker_embeddings: dict[str, SpeakerVoiceEmbedding] = {}

    for raw_label in sorted(raw_labels):
        speaker_embedding = await _compute_speaker_voice_embedding(
            staged_audio_path=staged_audio_path,
            transcript_results=transcript_results,
            raw_label=raw_label,
            embedding_timeout_seconds=embedding_timeout_seconds,
        )
        if speaker_embedding is None:
            assignments[raw_label] = None
            continue

        speaker_embeddings[raw_label] = speaker_embedding

        match = await _best_voiceprint_match(
            db, user_id, speaker_embedding.embedding, threshold
        )
        if match is None:
            directory_match = await _best_public_directory_match(
                db=db,
                receiver_user_id=user_id,
                embedding=speaker_embedding.embedding,
                threshold=DIRECTORY_MATCH_THRESHOLD,
            )
            if directory_match is not None:
                match = directory_match
        assignments[raw_label] = match

    if source_recording_id is not None and speaker_embeddings:
        await replace_recording_speaker_embeddings(
            db=db,
            user_id=user_id,
            recording_id=source_recording_id,
            speaker_embeddings=speaker_embeddings.values(),
        )

    return assignments


async def _compute_speaker_voice_embedding(
    *,
    staged_audio_path: Path | str,
    transcript_results: list["TranscriptResult"],
    raw_label: str,
    embedding_timeout_seconds: float,
) -> SpeakerVoiceEmbedding | None:
    spans = pick_clean_snippets(transcript_results, raw_label)
    if not spans:
        return None

    start_ms = spans[0][0]
    end_ms = spans[-1][1]
    try:
        embedding = await asyncio.wait_for(
            asyncio.to_thread(
                compute_voice_embedding_spans, staged_audio_path, spans
            ),
            timeout=embedding_timeout_seconds,
        )
    except TimeoutError:
        logger.warning(
            "Voice embedding timed out for raw_label=%s; skipping cluster",
            raw_label,
        )
        return None
    except Exception:
        logger.exception(
            "Voice embedding failed for raw_label=%s; skipping cluster", raw_label
        )
        return None

    return SpeakerVoiceEmbedding(
        raw_label=raw_label,
        embedding=embedding,
        start_ms=start_ms,
        end_ms=end_ms,
    )


async def _best_public_directory_match(
    *,
    db: AsyncSession,
    receiver_user_id: uuid.UUID,
    embedding: list[float],
    threshold: float,
) -> tuple[uuid.UUID, float] | None:
    """Search the global voice directory for a match, excluding the caller.

    On a hit, ensure a Person row exists in the receiver's address book whose
    ``directory_user_id`` points at the source user, and return that Person's
    id so the surrounding pipeline behaves identically to a regular
    voiceprint match.
    """
    vector_literal = format_embedding(embedding)
    result = await db.execute(
        text(
            """
            SELECT
                user_id AS source_user_id,
                first_name,
                last_name,
                1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM public_voiceprints
            WHERE user_id != :receiver_user_id
              AND embedding_model = :model
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT 1
            """
        ).bindparams(
            embedding=vector_literal,
            receiver_user_id=receiver_user_id,
            model=MODEL_NAME,
        )
    )
    row = result.first()
    if row is None:
        return None
    source_user_id, first_name, last_name, similarity = row
    if similarity is None or similarity < threshold:
        return None

    person_id = await _ensure_directory_person(
        db=db,
        receiver_user_id=receiver_user_id,
        source_user_id=source_user_id,
        first_name=first_name,
        last_name=last_name,
    )
    return person_id, float(similarity)


async def _ensure_directory_person(
    *,
    db: AsyncSession,
    receiver_user_id: uuid.UUID,
    source_user_id: uuid.UUID,
    first_name: str,
    last_name: str,
) -> uuid.UUID:
    """Return the Person id in receiver's address book linked to the source user.

    Creates the Person on first encounter and rebuilds display_name on every
    subsequent match so renames in the source user's profile propagate.
    """
    existing = (
        await db.execute(
            select(Person).where(
                Person.user_id == receiver_user_id,
                Person.directory_user_id == source_user_id,
            )
        )
    ).scalar_one_or_none()
    display_name = _compose_directory_display_name(first_name, last_name)
    if existing is not None:
        if existing.display_name != display_name:
            existing.display_name = display_name
        return existing.id

    person = Person(
        user_id=receiver_user_id,
        display_name=display_name,
        directory_user_id=source_user_id,
    )
    db.add(person)
    await db.flush()
    return person.id


def _compose_directory_display_name(first_name: str, last_name: str) -> str:
    first = (first_name or "").strip()
    last = (last_name or "").strip()
    composed = " ".join(part for part in (first, last) if part)
    return composed or "WaiComputer user"


async def _best_voiceprint_match(
    db: AsyncSession,
    user_id: uuid.UUID,
    embedding: list[float],
    threshold: float,
) -> tuple[uuid.UUID, float] | None:
    """Run pgvector cosine search; return best (person_id, similarity) over threshold."""
    vector_literal = format_embedding(embedding)
    result = await db.execute(
        text(
            """
            SELECT person_id, 1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM voiceprints
            WHERE user_id = :user_id AND model = :model
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT 1
            """
        ).bindparams(embedding=vector_literal, user_id=user_id, model=MODEL_NAME)
    )
    row = result.first()
    if row is None:
        return None
    person_id, similarity = row
    if similarity is None or similarity < threshold:
        return None
    return person_id, float(similarity)


async def store_voiceprint_from_path(
    *,
    db: AsyncSession,
    user_id: uuid.UUID,
    person_id: uuid.UUID,
    audio_path: Path | str,
    start_ms: int,
    end_ms: int,
    source_recording_id: uuid.UUID | None,
    source_raw_label: str | None = None,
) -> uuid.UUID:
    """Extract an ECAPA embedding from ``audio_path[start_ms:end_ms]`` and persist it
    as a voiceprint attached to ``person_id``.

    Used by both the diarization-side recorder (snippet extracted via
    ``pick_clean_snippet``) and the onboarding voice-enrollment endpoint
    (full uploaded sample, ``start_ms=0`` through total duration).
    """
    embedding = await asyncio.to_thread(
        compute_voice_embedding, audio_path, start_ms, end_ms
    )

    voiceprint_id = uuid.uuid4()
    duration_s = (end_ms - start_ms) / 1000.0
    await db.execute(
        text(
            """
            INSERT INTO voiceprints (
                id, person_id, user_id, embedding, model, source_recording_id,
                source_raw_label, duration_s
            ) VALUES (
                :id, :person_id, :user_id, CAST(:embedding AS vector),
                :model, :source_recording_id, :source_raw_label, :duration_s
            )
            """
        ).bindparams(
            id=voiceprint_id,
            person_id=person_id,
            user_id=user_id,
            embedding=format_embedding(embedding),
            model=MODEL_NAME,
            source_recording_id=source_recording_id,
            source_raw_label=source_raw_label,
            duration_s=duration_s,
        )
    )
    return voiceprint_id


async def store_voiceprint(
    *,
    db: AsyncSession,
    user_id: uuid.UUID,
    person_id: uuid.UUID,
    staged_audio_path: Path | str,
    transcript_results: list["TranscriptResult"],
    raw_label: str,
    source_recording_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Extract a voiceprint for ``raw_label`` and persist it against ``person_id``.

    Returns the new voiceprint id, or ``None`` if no clean snippet was available.
    """
    span = pick_clean_snippet(transcript_results, raw_label)
    if span is None:
        return None

    start_ms, end_ms = span
    return await store_voiceprint_from_path(
        db=db,
        user_id=user_id,
        person_id=person_id,
        audio_path=staged_audio_path,
        start_ms=start_ms,
        end_ms=end_ms,
        source_recording_id=source_recording_id,
        source_raw_label=raw_label,
    )


async def replace_recording_speaker_embeddings(
    *,
    db: AsyncSession,
    user_id: uuid.UUID,
    recording_id: uuid.UUID,
    speaker_embeddings: Iterable[SpeakerVoiceEmbedding],
) -> None:
    """Replace retained unlabeled speaker embeddings for a processed recording."""
    await db.execute(
        delete(RecordingSpeakerEmbedding).where(
            RecordingSpeakerEmbedding.recording_id == recording_id
        )
    )
    for item in speaker_embeddings:
        db.add(
            RecordingSpeakerEmbedding(
                user_id=user_id,
                recording_id=recording_id,
                raw_label=item.raw_label,
                embedding=item.embedding,
                model=MODEL_NAME,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                duration_s=item.duration_s,
            )
        )


async def store_voiceprint_from_recording_speaker(
    *,
    db: AsyncSession,
    user_id: uuid.UUID,
    person_id: uuid.UUID,
    recording_id: uuid.UUID,
    raw_label: str,
) -> uuid.UUID | None:
    """Promote a retained recording speaker embedding to a named Person voiceprint."""
    existing = (
        await db.execute(
            select(Voiceprint).where(
                Voiceprint.user_id == user_id,
                Voiceprint.person_id == person_id,
                Voiceprint.source_recording_id == recording_id,
                Voiceprint.source_raw_label == raw_label,
                Voiceprint.model == MODEL_NAME,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id

    sample = (
        await db.execute(
            select(RecordingSpeakerEmbedding).where(
                RecordingSpeakerEmbedding.user_id == user_id,
                RecordingSpeakerEmbedding.recording_id == recording_id,
                RecordingSpeakerEmbedding.raw_label == raw_label,
                RecordingSpeakerEmbedding.model == MODEL_NAME,
            )
        )
    ).scalar_one_or_none()
    if sample is None:
        return None

    voiceprint = Voiceprint(
        user_id=user_id,
        person_id=person_id,
        embedding=list(sample.embedding),
        model=MODEL_NAME,
        source_recording_id=recording_id,
        source_raw_label=raw_label,
        duration_s=sample.duration_s,
        quality_score=None,
    )
    db.add(voiceprint)
    await db.flush()
    return voiceprint.id


async def rematch_recording_speakers(
    *,
    db: AsyncSession,
    user_id: uuid.UUID,
    recording_id: uuid.UUID,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> SpeakerRematchResult | None:
    """Re-apply current voiceprint matches from retained recording speaker embeddings."""
    samples = (
        await db.execute(
            select(RecordingSpeakerEmbedding)
            .where(
                RecordingSpeakerEmbedding.user_id == user_id,
                RecordingSpeakerEmbedding.recording_id == recording_id,
                RecordingSpeakerEmbedding.model == MODEL_NAME,
            )
            .order_by(RecordingSpeakerEmbedding.raw_label.asc())
        )
    ).scalars().all()
    if not samples:
        return None

    updated_clusters = 0
    matched_clusters = 0
    for sample in samples:
        match = await _best_voiceprint_match(
            db, user_id, list(sample.embedding), threshold
        )
        if match is None:
            result = await db.execute(
                update(Segment)
                .where(
                    Segment.recording_id == recording_id,
                    Segment.raw_label == sample.raw_label,
                    Segment.auto_assigned.is_(True),
                )
                .values(person_id=None, auto_assigned=False, match_confidence=None)
            )
            if result.rowcount:
                updated_clusters += 1
            continue

        person_id, confidence = match
        matched_clusters += 1
        result = await db.execute(
            update(Segment)
            .where(
                Segment.recording_id == recording_id,
                Segment.raw_label == sample.raw_label,
                or_(Segment.auto_assigned.is_(True), Segment.person_id.is_(None)),
            )
            .values(
                person_id=person_id,
                auto_assigned=True,
                match_confidence=confidence,
            )
        )
        if result.rowcount:
            updated_clusters += 1

    return SpeakerRematchResult(
        updated_clusters=updated_clusters,
        matched_clusters=matched_clusters,
    )
