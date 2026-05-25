"""Tests for semantic embedding repair jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embedding_backfill import backfill_missing_segment_embeddings
from app.models.recording import Recording, Segment
from app.models.user import User


@pytest.mark.asyncio
async def test_backfill_missing_segment_embeddings_fills_only_null_non_empty_segments(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="embedding-backfill@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title="Ready",
        type="meeting",
        status="ready",
        uploaded_at=datetime.now(timezone.utc),
    )
    db_session.add(recording)
    await db_session.flush()
    needs_embedding = Segment(
        recording_id=recording.id,
        speaker="speaker_0",
        content="repairable segment",
        start_ms=0,
        end_ms=1000,
        embedding=None,
    )
    already_filled = Segment(
        recording_id=recording.id,
        speaker="speaker_0",
        content="already embedded",
        start_ms=1000,
        end_ms=2000,
        embedding=[0.2] * 1536,
    )
    blank = Segment(
        recording_id=recording.id,
        speaker="speaker_0",
        content="   ",
        start_ms=2000,
        end_ms=3000,
        embedding=None,
    )
    db_session.add_all([needs_embedding, already_filled, blank])
    await db_session.commit()

    generate = AsyncMock(return_value=[[0.7] * 1536])
    monkeypatch.setattr("app.core.embedding_backfill.generate_embeddings", generate)

    result = await backfill_missing_segment_embeddings(db_session, batch_size=10, limit=20)

    await db_session.refresh(needs_embedding)
    await db_session.refresh(already_filled)
    await db_session.refresh(blank)
    assert result.as_dict() == {
        "scanned": 1,
        "filled": 1,
        "failed": 0,
        "remaining": 0,
        "batches": 1,
        "isolated_failures": 0,
    }
    generate.assert_awaited_once_with(["repairable segment"])
    assert list(needs_embedding.embedding) == [0.7] * 1536
    assert list(already_filled.embedding) == [0.2] * 1536
    assert blank.embedding is None


@pytest.mark.asyncio
async def test_backfill_missing_segment_embeddings_isolates_poison_rows(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="embedding-backfill-poison@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title="Ready",
        type="meeting",
        status="ready",
        uploaded_at=datetime.now(timezone.utc),
    )
    db_session.add(recording)
    await db_session.flush()
    first = Segment(
        recording_id=recording.id,
        speaker="speaker_0",
        content="good segment",
        start_ms=0,
        end_ms=1000,
        embedding=None,
    )
    second = Segment(
        recording_id=recording.id,
        speaker="speaker_0",
        content="poison segment",
        start_ms=1000,
        end_ms=2000,
        embedding=None,
    )
    db_session.add_all([first, second])
    await db_session.commit()

    async def fake_generate(texts: list[str]) -> list[list[float]]:
        if len(texts) > 1:
            raise RuntimeError("batch failed")
        if texts == ["poison segment"]:
            raise RuntimeError("single failed")
        return [[0.4] * 1536]

    generate = AsyncMock(side_effect=fake_generate)
    monkeypatch.setattr("app.core.embedding_backfill.generate_embeddings", generate)

    result = await backfill_missing_segment_embeddings(db_session, batch_size=10, limit=20)

    await db_session.refresh(first)
    await db_session.refresh(second)
    assert result.filled == 1
    assert result.failed == 1
    assert result.remaining == 1
    assert result.batches == 1
    assert result.isolated_failures == 1
    assert list(first.embedding) == [0.4] * 1536
    assert second.embedding is None


@pytest.mark.asyncio
async def test_backfill_missing_segment_embeddings_can_be_user_scoped(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="embedding-backfill-scope@example.com", password_hash="x")
    other = User(email="embedding-backfill-other@example.com", password_hash="x")
    db_session.add_all([user, other])
    await db_session.flush()
    user_recording = Recording(user_id=user.id, title="Mine", type="meeting", status="ready")
    other_recording = Recording(user_id=other.id, title="Other", type="meeting", status="ready")
    db_session.add_all([user_recording, other_recording])
    await db_session.flush()
    user_segment = Segment(recording_id=user_recording.id, content="mine", embedding=None)
    other_segment = Segment(recording_id=other_recording.id, content="other", embedding=None)
    db_session.add_all([user_segment, other_segment])
    await db_session.commit()

    monkeypatch.setattr(
        "app.core.embedding_backfill.generate_embeddings",
        AsyncMock(return_value=[[0.9] * 1536]),
    )

    result = await backfill_missing_segment_embeddings(
        db_session,
        user_id=user.id,
        batch_size=10,
        limit=20,
    )

    assert result.filled == 1
    await db_session.refresh(user_segment)
    await db_session.refresh(other_segment)
    assert user_segment.embedding is not None
    assert other_segment.embedding is None
