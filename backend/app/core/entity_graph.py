"""Knowledge-graph write helpers: upsert entities + record mentions.

The single path that turns extracted people / topics (from recordings OR items)
into graph nodes (``Entity``) and provenance edges (``EntityMention``). Dedup is
EXACT on the normalised name — per the product decision, only exact matches
merge; fuzzy / embedding-similar duplicates go to the Review queue, never a
silent merge. No fallbacks: a write failure propagates.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.name_moderation import normalise_name
from app.models.entity import Entity, EntityMention

logger = logging.getLogger(__name__)


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
    return count
