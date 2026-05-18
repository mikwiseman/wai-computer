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
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import format_embedding
from app.core.voice_embedding import (
    MODEL_NAME,
    compute_voice_embedding,
    pick_clean_snippet,
)

if TYPE_CHECKING:
    from app.core.transcript_utils import TranscriptResult

logger = logging.getLogger(__name__)

DEFAULT_MATCH_THRESHOLD = 0.6


async def identify_speakers_for_recording(
    *,
    db: AsyncSession,
    user_id: uuid.UUID,
    staged_audio_path: Path | str,
    transcript_results: list["TranscriptResult"],
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> dict[str, tuple[uuid.UUID, float] | None]:
    """Match each diarization cluster (``raw_label``) to a known Person.

    Returns a mapping from raw_label to ``(person_id, cosine_similarity)`` when a
    voiceprint above ``threshold`` is found, or ``None`` when no match exists or
    the cluster is too short for reliable identification.
    """
    raw_labels = {tr.speaker for tr in transcript_results if tr.speaker is not None}
    if not raw_labels:
        return {}

    assignments: dict[str, tuple[uuid.UUID, float] | None] = {}

    for raw_label in sorted(raw_labels):
        span = pick_clean_snippet(transcript_results, raw_label)
        if span is None:
            assignments[raw_label] = None
            continue

        start_ms, end_ms = span
        try:
            embedding = await asyncio.to_thread(
                compute_voice_embedding, staged_audio_path, start_ms, end_ms
            )
        except Exception:
            logger.exception(
                "Voice embedding failed for raw_label=%s; skipping cluster", raw_label
            )
            assignments[raw_label] = None
            continue

        match = await _best_voiceprint_match(db, user_id, embedding, threshold)
        assignments[raw_label] = match

    return assignments


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
    embedding = await asyncio.to_thread(
        compute_voice_embedding, staged_audio_path, start_ms, end_ms
    )

    voiceprint_id = uuid.uuid4()
    duration_s = (end_ms - start_ms) / 1000.0
    await db.execute(
        text(
            """
            INSERT INTO voiceprints (
                id, person_id, user_id, embedding, model, source_recording_id, duration_s
            ) VALUES (
                :id, :person_id, :user_id, CAST(:embedding AS vector),
                :model, :source_recording_id, :duration_s
            )
            """
        ).bindparams(
            id=voiceprint_id,
            person_id=person_id,
            user_id=user_id,
            embedding=format_embedding(embedding),
            model=MODEL_NAME,
            source_recording_id=source_recording_id,
            duration_s=duration_s,
        )
    )
    return voiceprint_id
