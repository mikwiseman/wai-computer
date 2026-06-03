"""DB-backed tests for item summary + key-moments generation (Phase 1)."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.item_ingest import ingest_item
from app.core.item_summary import generate_item_summary
from app.core.summarizer import KeyMoment, SummaryResult
from app.models.entity import Entity, EntityMention
from app.models.item import ItemSummary
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"isum-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def _fake_embedder(texts: list[str]) -> list[list[float]]:
    return [[0.01] * 1536 for _ in texts]


def _fake_summary() -> SummaryResult:
    return SummaryResult(
        title="Generated Title",
        summary="A concise summary.",
        key_points=["point one", "point two"],
        decisions=[],
        action_items=[{"task": "do the thing", "owner": None, "due": None, "priority": "high"}],
        topics=["energy"],
        people_mentioned=["Alice"],
        follow_up_questions=[],
        sentiment="neutral",
        highlights=[],
    )


async def test_generate_item_summary_persists_row_and_table(db_session) -> None:
    user = await _make_user(db_session)
    item, _ = await ingest_item(
        db_session, user.id, source="paste", kind="article",
        title="", body="Long article body about solar power and storage.",
        embedder=_fake_embedder,
    )

    async def fake_summarizer(text, **kwargs):
        assert kwargs["content_kind"] == "article"
        return _fake_summary()

    async def fake_moments(text, **kwargs):
        return [
            KeyMoment(
                timestamp=None, moment="Thesis", why_it_matters="frames it",
                quote="solar is cheap", importance="high",
            )
        ]

    summary = await generate_item_summary(
        db_session, item, summarizer=fake_summarizer, moment_extractor=fake_moments
    )

    assert summary.summary == "A concise summary."
    assert summary.key_points == ["point one", "point two"]
    assert summary.action_items[0]["task"] == "do the thing"
    assert summary.key_moments[0]["moment"] == "Thesis"
    assert summary.key_moments[0]["timestamp"] is None
    # Title backfilled onto the item since it had none.
    assert item.title == "Generated Title"

    # Persisted + unique per item.
    rows = (
        (await db_session.execute(select(ItemSummary).where(ItemSummary.item_id == item.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1

    # Phase 2: the item's people + topics seeded graph entities + mentions
    # (Alice -> person, energy -> topic) at zero extra LLM cost.
    entities = (
        (await db_session.execute(select(Entity).where(Entity.user_id == user.id)))
        .scalars()
        .all()
    )
    assert {(e.type, e.name) for e in entities} == {
        ("person", "Alice"),
        ("topic", "energy"),
    }
    mentions = (
        (
            await db_session.execute(
                select(EntityMention).where(EntityMention.source_id == item.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(mentions) == 2
    assert all(m.source_kind == "item" for m in mentions)


async def test_generate_item_summary_upserts(db_session) -> None:
    user = await _make_user(db_session)
    item, _ = await ingest_item(
        db_session, user.id, source="paste", title="T", body="body text here",
        embedder=_fake_embedder,
    )

    async def fake_summarizer(text, **kwargs):
        return _fake_summary()

    async def fake_moments(text, **kwargs):
        return []

    await generate_item_summary(
        db_session, item, summarizer=fake_summarizer, moment_extractor=fake_moments
    )
    await generate_item_summary(
        db_session, item, summarizer=fake_summarizer, moment_extractor=fake_moments
    )

    rows = (
        (await db_session.execute(select(ItemSummary).where(ItemSummary.item_id == item.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1  # upsert, not duplicate


async def test_key_moments_get_timestamps_from_segments(db_session) -> None:
    user = await _make_user(db_session)
    item, _ = await ingest_item(
        db_session, user.id, source="url", kind="video",
        title="Vid", body="full transcript text about the budget approval",
        metadata={
            "segments": [
                {"content": "intro chatter", "start_ms": 0, "end_ms": 1000},
                {"content": "the budget approval happened here", "start_ms": 4000, "end_ms": 9000},
            ]
        },
        embedder=_fake_embedder,
    )

    async def fake_summarizer(text, **kwargs):
        return _fake_summary()

    async def fake_moments(text, **kwargs):
        return [
            KeyMoment(
                timestamp=None, moment="budget approval", why_it_matters="key decision",
                quote="budget approval", importance="high",
            )
        ]

    summary = await generate_item_summary(
        db_session, item, summarizer=fake_summarizer, moment_extractor=fake_moments
    )
    assert summary.key_moments[0]["start_ms"] == 4000
    assert summary.key_moments[0]["end_ms"] == 9000


async def test_generate_item_summary_requires_body(db_session) -> None:
    user = await _make_user(db_session)
    item, _ = await ingest_item(
        db_session, user.id, source="url", kind="video", url="https://x.com/a",
        dedup_key="https://x.com/a", body=None, embed=False,
    )
    with pytest.raises(ValueError):
        await generate_item_summary(db_session, item)
