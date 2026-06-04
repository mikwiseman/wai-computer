"""Knowledge-graph write helpers: upsert entities + record mentions.

The single path that turns extracted people / topics (from recordings OR items)
into graph nodes (``Entity``) and provenance edges (``EntityMention``). Dedup is
EXACT on the normalised name — per the product decision, only exact matches
merge; fuzzy / embedding-similar duplicates go to the Review queue, never a
silent merge. No fallbacks: a write failure propagates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.entity_reconcile import reconcile_person_entities
from app.core.name_moderation import normalise_name
from app.models.entity import Entity, EntityMention
from app.models.item import Item, ItemSummary
from app.models.recording import Recording, Summary

logger = logging.getLogger(__name__)


@dataclass
class EntitySummaryBackfillResult:
    recording_summaries_scanned: int
    item_summaries_scanned: int
    sources_with_entities: int
    mentions_recorded: int
    entity_mentions_before: int
    entity_mentions_after: int
    created_mentions: int
    llm_requests: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "recording_summaries_scanned": self.recording_summaries_scanned,
            "item_summaries_scanned": self.item_summaries_scanned,
            "sources_with_entities": self.sources_with_entities,
            "mentions_recorded": self.mentions_recorded,
            "entity_mentions_before": self.entity_mentions_before,
            "entity_mentions_after": self.entity_mentions_after,
            "created_mentions": self.created_mentions,
            "llm_requests": self.llm_requests,
        }


async def upsert_entity(
    db: AsyncSession, user_id: Any, *, type: str, name: str
) -> Entity | None:
    """Get-or-create an Entity, deduped EXACTLY on (user_id, type, normalised name).

    Returns ``None`` when the name normalises to empty. Race-safe: a concurrent
    insert of the same key is caught (IntegrityError) and the winning row
    returned, so two tasks extracting the same person never 500 or duplicate.
    """
    clean = normalise_name(name)
    if clean is None:
        return None

    found = (
        await db.execute(
            select(Entity).where(
                Entity.user_id == user_id, Entity.type == type, Entity.name == clean
            )
        )
    ).scalar_one_or_none()
    if found is not None:
        return found

    entity = Entity(user_id=user_id, type=type, name=clean)
    try:
        async with db.begin_nested():
            db.add(entity)
            await db.flush()
    except IntegrityError:
        return (
            await db.execute(
                select(Entity).where(
                    Entity.user_id == user_id, Entity.type == type, Entity.name == clean
                )
            )
        ).scalar_one()
    return entity


async def record_mention(
    db: AsyncSession,
    *,
    user_id: Any,
    entity_id: Any,
    source_kind: str,
    source_id: Any,
    chunk_id: Any | None = None,
    context: str | None = None,
    weight: float = 1.0,
) -> EntityMention:
    """Idempotently record that a source (recording|item) mentions an entity.

    One row per (entity, source); re-processing updates weight/context rather
    than duplicating the edge.
    """
    existing = (
        await db.execute(
            select(EntityMention).where(
                EntityMention.entity_id == entity_id,
                EntityMention.source_kind == source_kind,
                EntityMention.source_id == source_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.weight = weight
        if context:
            existing.context = context
        return existing

    mention = EntityMention(
        user_id=user_id,
        entity_id=entity_id,
        source_kind=source_kind,
        source_id=source_id,
        chunk_id=chunk_id,
        context=context,
        weight=weight,
    )
    try:
        async with db.begin_nested():
            db.add(mention)
            await db.flush()
    except IntegrityError:
        return (
            await db.execute(
                select(EntityMention).where(
                    EntityMention.entity_id == entity_id,
                    EntityMention.source_kind == source_kind,
                    EntityMention.source_id == source_id,
                )
            )
        ).scalar_one()
    return mention


async def seed_entities_from_summary(
    db: AsyncSession,
    user_id: Any,
    *,
    source_kind: str,
    source_id: Any,
    people: list[str] | None,
    topics: list[str] | None,
) -> int:
    """Promote a summary's ``people_mentioned`` + ``topics`` into graph entities
    and mentions — zero extra LLM cost — so the source becomes a graph citizen.

    Returns the number of mentions recorded.
    """
    count = 0
    for raw, etype in (
        *[(p, "person") for p in (people or [])],
        *[(t, "topic") for t in (topics or [])],
    ):
        entity = await upsert_entity(db, user_id, type=etype, name=raw)
        if entity is None:
            continue
        await record_mention(
            db,
            user_id=user_id,
            entity_id=entity.id,
            source_kind=source_kind,
            source_id=source_id,
        )
        count += 1
    # Link any freshly-seeded person entities to known speakers (idempotent,
    # exact-name only — fuzzy stays out of the graph, per the Review-queue rule).
    if people:
        await reconcile_person_entities(db, user_id)
    return count


async def _mention_count(db: AsyncSession, user_id: Any | None) -> int:
    stmt = select(func.count()).select_from(EntityMention)
    if user_id is not None:
        stmt = stmt.where(EntityMention.user_id == user_id)
    return int(await db.scalar(stmt) or 0)


async def backfill_entity_mentions_from_existing_summaries(
    db: AsyncSession,
    user_id: Any | None = None,
    *,
    limit: int | None = None,
) -> EntitySummaryBackfillResult:
    """Repair source->entity provenance from already-generated summaries.

    This is intentionally zero-LLM: it only replays stored ``people_mentioned``
    and ``topics`` into the graph. Ready recordings without summaries are left
    untouched so old content does not create surprise token spend.
    """
    before = await _mention_count(db, user_id)

    recording_stmt = (
        select(
            Recording.user_id,
            Summary.recording_id,
            Summary.people_mentioned,
            Summary.topics,
        )
        .join(Recording, Recording.id == Summary.recording_id)
        .where(Recording.deleted_at.is_(None))
        .order_by(Summary.updated_at.asc(), Summary.id.asc())
    )
    if user_id is not None:
        recording_stmt = recording_stmt.where(Recording.user_id == user_id)
    if limit is not None:
        recording_stmt = recording_stmt.limit(limit)
    recording_rows = (await db.execute(recording_stmt)).all()

    remaining = None if limit is None else max(limit - len(recording_rows), 0)
    item_stmt = (
        select(Item.user_id, ItemSummary.item_id, ItemSummary.people_mentioned, ItemSummary.topics)
        .join(Item, Item.id == ItemSummary.item_id)
        .where(Item.deleted_at.is_(None))
        .order_by(ItemSummary.updated_at.asc(), ItemSummary.id.asc())
    )
    if user_id is not None:
        item_stmt = item_stmt.where(Item.user_id == user_id)
    if remaining is not None:
        item_stmt = item_stmt.limit(remaining)
    item_rows = (await db.execute(item_stmt)).all()

    mentions_recorded = 0
    sources_with_entities = 0
    for owner_id, source_id, people, topics in recording_rows:
        recorded = await seed_entities_from_summary(
            db,
            owner_id,
            source_kind="recording",
            source_id=source_id,
            people=people,
            topics=topics,
        )
        mentions_recorded += recorded
        if recorded > 0:
            sources_with_entities += 1

    for owner_id, source_id, people, topics in item_rows:
        recorded = await seed_entities_from_summary(
            db,
            owner_id,
            source_kind="item",
            source_id=source_id,
            people=people,
            topics=topics,
        )
        mentions_recorded += recorded
        if recorded > 0:
            sources_with_entities += 1

    after = await _mention_count(db, user_id)
    return EntitySummaryBackfillResult(
        recording_summaries_scanned=len(recording_rows),
        item_summaries_scanned=len(item_rows),
        sources_with_entities=sources_with_entities,
        mentions_recorded=mentions_recorded,
        entity_mentions_before=before,
        entity_mentions_after=after,
        created_mentions=max(after - before, 0),
    )
