"""Fuzzy entity-merge governance — detect near-duplicate entities + merge on
human confirmation.

Exact-name duplicates never occur (``upsert_entity`` dedups on the normalised
name); what fragments the graph is near-spelling FUZZY duplicates ("Jon"/"John",
"Petrova"/"Petrov", "Anna"/"Ana"). Per the product rule those are NEVER silently
merged — they're surfaced for human confirmation, then merged here. (Semantic
aliases like "Bob"/"Robert" or "ML"/"Machine Learning" are NOT string-similar;
catching those needs the deferred entity-embedding pass — out of scope here.)

``merge_entities`` is destructive (re-points provenance + deletes the dropped
entity), so it is careful with the ``EntityMention`` unique constraint
(entity_id, source_kind, source_id) and never leaves self-loop relations.
"""

from __future__ import annotations

import difflib
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import Entity, EntityMention, EntityRelation

logger = logging.getLogger(__name__)

# Cap the O(n²) within-type comparison so a pathological library can't stall.
_MAX_ENTITIES_PER_TYPE = 400


@dataclass
class MergeCandidate:
    keep_id: str
    keep_name: str
    drop_id: str
    drop_name: str
    type: str
    score: float
    keep_mentions: int
    drop_mentions: int


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.casefold(), b.casefold()).ratio()


async def find_duplicate_entity_candidates(
    db: AsyncSession, user_id: Any, *, threshold: float = 0.86, limit: int = 50
) -> list[MergeCandidate]:
    """Surface near-duplicate same-type entity pairs (fuzzy, not exact).

    The more-mentioned entity is suggested to KEEP (ties → the longer, more
    specific name). Capped O(n²) within each type; highest score first.
    """
    entities = (
        await db.execute(
            select(Entity).where(Entity.user_id == user_id).order_by(Entity.name)
        )
    ).scalars().all()

    counts = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(EntityMention.entity_id, func.count())
                .where(EntityMention.user_id == user_id)
                .group_by(EntityMention.entity_id)
            )
        ).all()
    }

    by_type: dict[str, list[Entity]] = defaultdict(list)
    for entity in entities:
        by_type[entity.type].append(entity)

    candidates: list[MergeCandidate] = []
    for etype, ents in by_type.items():
        if len(ents) > _MAX_ENTITIES_PER_TYPE:
            logger.warning(
                "entity dedup: type=%s has %d entities, capping at %d",
                etype, len(ents), _MAX_ENTITIES_PER_TYPE,
            )
            ents = ents[:_MAX_ENTITIES_PER_TYPE]
        for i in range(len(ents)):
            for j in range(i + 1, len(ents)):
                # Same-(type, name) can't coexist (uq_entities_user_type_name),
                # so names within a type bucket always differ.
                a, b = ents[i], ents[j]
                score = _similarity(a.name, b.name)
                if score < threshold:
                    continue
                ca, cb = counts.get(a.id, 0), counts.get(b.id, 0)
                # Keep the more-mentioned entity; tie-break on the longer name.
                if (ca, len(a.name)) >= (cb, len(b.name)):
                    keep, drop, keep_c, drop_c = a, b, ca, cb
                else:
                    keep, drop, keep_c, drop_c = b, a, cb, ca
                candidates.append(
                    MergeCandidate(
                        keep_id=str(keep.id), keep_name=keep.name,
                        drop_id=str(drop.id), drop_name=drop.name,
                        type=etype, score=round(score, 3),
                        keep_mentions=keep_c, drop_mentions=drop_c,
                    )
                )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:limit]


async def merge_entities(
    db: AsyncSession, *, user_id: Any, keep_id: Any, drop_id: Any
) -> bool:
    """Merge ``drop`` into ``keep``: re-point provenance, then delete ``drop``.

    Returns ``False`` when the ids are equal or either entity isn't found/owned
    (so a double-submit is a safe no-op once ``drop`` is gone). Re-points
    EntityMention (dropping rows that would collide with an existing keep mention
    on the unique constraint) and EntityRelation (deleting edges that would
    become self-loops), then deletes the dropped entity.
    """
    if str(keep_id) == str(drop_id):
        return False

    keep = (
        await db.execute(
            select(Entity).where(Entity.id == keep_id, Entity.user_id == user_id)
        )
    ).scalar_one_or_none()
    drop = (
        await db.execute(
            select(Entity).where(Entity.id == drop_id, Entity.user_id == user_id)
        )
    ).scalar_one_or_none()
    if keep is None or drop is None:
        return False

    # 1) Mentions — re-point to keep, but delete any that would violate the
    #    unique (entity_id, source_kind, source_id) constraint (keep already has
    #    a mention from that source).
    keep_keys = {
        (m.source_kind, str(m.source_id))
        for m in (
            await db.execute(
                select(EntityMention).where(EntityMention.entity_id == keep.id)
            )
        ).scalars().all()
    }
    drop_mentions = (
        await db.execute(
            select(EntityMention).where(EntityMention.entity_id == drop.id)
        )
    ).scalars().all()
    for mention in drop_mentions:
        key = (mention.source_kind, str(mention.source_id))
        if key in keep_keys:
            await db.delete(mention)
        else:
            mention.entity_id = keep.id
            keep_keys.add(key)

    # 2) Relations — delete edges fully inside {keep, drop} (they'd become
    #    self-loops), then re-point remaining drop edges to keep.
    await db.execute(
        delete(EntityRelation).where(
            EntityRelation.source_id.in_([keep.id, drop.id]),
            EntityRelation.target_id.in_([keep.id, drop.id]),
        )
    )
    await db.execute(
        update(EntityRelation)
        .where(EntityRelation.source_id == drop.id)
        .values(source_id=keep.id)
    )
    await db.execute(
        update(EntityRelation)
        .where(EntityRelation.target_id == drop.id)
        .values(target_id=keep.id)
    )

    # 3) Drop the merged-away entity.
    await db.delete(drop)
    await db.flush()
    return True
