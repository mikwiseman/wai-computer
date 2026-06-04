"""Repair missing semantic embeddings without exposing transcript text."""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import generate_embeddings
from app.core.observability import fingerprint_text
from app.models.recording import Recording, Segment

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingBackfillResult:
    scanned: int = 0
    filled: int = 0
    failed: int = 0
    remaining: int = 0
    batches: int = 0
    isolated_failures: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def _candidate_filters(user_id: UUID | None) -> list:
    filters = [
        Recording.deleted_at.is_(None),
        Segment.embedding.is_(None),
        Segment.content.is_not(None),
        func.length(func.trim(Segment.content)) > 0,
    ]
    if user_id is not None:
        filters.append(Recording.user_id == user_id)
    return filters


async def _remaining_candidate_count(db: AsyncSession, *, user_id: UUID | None) -> int:
    return int(
        (
            await db.execute(
                select(func.count(Segment.id))
                .join(Recording, Recording.id == Segment.recording_id)
                .where(*_candidate_filters(user_id))
            )
        ).scalar_one()
    )


async def _generate_checked_embeddings(
    texts: list[str],
    *,
    user_id: UUID | None,
) -> list[list[float]]:
    embeddings = await generate_embeddings(
        texts,
        usage_user_id=user_id,
        usage_feature="embeddings",
        usage_operation="embedding.backfill",
    )
    if len(embeddings) != len(texts):
        raise RuntimeError(
            f"embedding_count_mismatch expected={len(texts)} actual={len(embeddings)}"
        )
    return embeddings


async def backfill_missing_segment_embeddings(
    db: AsyncSession,
    *,
    user_id: UUID | None = None,
    batch_size: int = 64,
    limit: int = 512,
) -> EmbeddingBackfillResult:
    """Fill NULL segment embeddings in bounded batches.

    The repair key is ``embedding IS NULL``. Transcript text is passed only to
    OpenAI and is never written to logs, Sentry extras, or the admin response.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if limit < 1:
        raise ValueError("limit must be positive")

    started = time.perf_counter()
    rows = (
        (
            await db.execute(
                select(Segment)
                .join(Recording, Recording.id == Segment.recording_id)
                .where(*_candidate_filters(user_id))
                .order_by(
                    Recording.created_at.asc(),
                    Segment.start_ms.asc().nulls_last(),
                    Segment.id.asc(),
                )
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return EmbeddingBackfillResult(
            remaining=await _remaining_candidate_count(db, user_id=user_id)
        )

    scanned = 0
    filled = 0
    failed = 0
    batches = 0
    isolated_failures = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        texts = [segment.content.strip() for segment in batch]
        scanned += len(batch)
        batches += 1
        try:
            embeddings = await _generate_checked_embeddings(texts, user_id=user_id)
        except Exception as exc:
            logger.warning(
                "embedding backfill batch failed batch_size=%s error_type=%s "
                "error_fingerprint=%s",
                len(batch),
                type(exc).__name__,
                fingerprint_text(str(exc)),
            )
            for segment, text in zip(batch, texts, strict=True):
                try:
                    embedding = (
                        await _generate_checked_embeddings([text], user_id=user_id)
                    )[0]
                except Exception as single_exc:
                    failed += 1
                    isolated_failures += 1
                    logger.warning(
                        "embedding backfill segment failed segment_id=%s recording_id=%s "
                        "error_type=%s error_fingerprint=%s",
                        segment.id,
                        segment.recording_id,
                        type(single_exc).__name__,
                        fingerprint_text(str(single_exc)),
                    )
                    continue
                segment.embedding = embedding
                filled += 1
            continue

        for segment, embedding in zip(batch, embeddings, strict=True):
            segment.embedding = embedding
            filled += 1

    await db.commit()
    remaining = await _remaining_candidate_count(db, user_id=user_id)
    logger.info(
        "embedding backfill completed scanned=%s filled=%s failed=%s remaining=%s "
        "batches=%s latency_ms=%s",
        scanned,
        filled,
        failed,
        remaining,
        batches,
        round((time.perf_counter() - started) * 1000),
    )
    return EmbeddingBackfillResult(
        scanned=scanned,
        filled=filled,
        failed=failed,
        remaining=remaining,
        batches=batches,
        isolated_failures=isolated_failures,
    )
