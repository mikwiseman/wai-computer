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
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.entity_reconcile import reconcile_person_entities
from app.core.fact_pipeline import (
    CurrentFact,
    ExtractedFact,
    decide_fact_actions,
    normalize_predicate,
)
from app.core.name_moderation import normalise_name
from app.models.entity import Entity, EntityFact, EntityMention, EntityRelation
from app.models.item import Item, ItemSummary
from app.models.recording import Recording, Segment, Summary

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


def _attach_identity(entity: Entity, key: str) -> None:
    """Record a strong identity key (email/handle) on an entity, dedup-safe.

    Reassigns ``metadata_`` so SQLAlchemy marks the JSONB column dirty.
    """
    md = dict(entity.metadata_ or {})
    keys = list(md.get("identity_keys") or [])
    if key not in keys:
        keys.append(key)
        md["identity_keys"] = keys
        entity.metadata_ = md


async def _find_by_identity(
    db: AsyncSession, user_id: Any, type: str, key: str
) -> Entity | None:
    """Find an existing entity carrying this strong identity key (email/handle)."""
    return (
        await db.execute(
            select(Entity)
            .where(
                Entity.user_id == user_id,
                Entity.type == type,
                Entity.metadata_.contains({"identity_keys": [key]}),
            )
            .limit(1)
        )
    ).scalars().first()


async def upsert_entity(
    db: AsyncSession,
    user_id: Any,
    *,
    type: str,
    name: str,
    identity_key: str | None = None,
) -> Entity | None:
    """Get-or-create an Entity, deduped on a strong identity key then EXACT name.

    ``identity_key`` (an email address or chat handle) is the strong key: the
    same person under a new display name but the same address collapses onto one
    node. Without an identity match we dedup EXACTLY on (user_id, type,
    normalised name); fuzzy / embedding-similar duplicates go to the Review
    queue, never a silent merge. Returns ``None`` when there's nothing to key on.
    Race-safe: a concurrent insert of the same key returns the winning row.
    """
    key = identity_key.lower() if identity_key else None
    if key:
        existing = await _find_by_identity(db, user_id, type, key)
        if existing is not None:
            return existing

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
        if key:
            _attach_identity(found, key)
        return found

    entity = Entity(
        user_id=user_id,
        type=type,
        name=clean,
        metadata_={"identity_keys": [key]} if key else None,
    )
    try:
        async with db.begin_nested():
            db.add(entity)
            await db.flush()
    except IntegrityError:
        winner = (
            await db.execute(
                select(Entity).where(
                    Entity.user_id == user_id, Entity.type == type, Entity.name == clean
                )
            )
        ).scalar_one()
        if key:
            _attach_identity(winner, key)
        return winner
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
    await _mark_dossier_dirty(db, entity_id)
    return mention


async def record_relation(
    db: AsyncSession,
    *,
    source_entity_id: Any,
    target_entity_id: Any,
    relation_type: str | None,
    recording_id: Any | None = None,
    context: str | None = None,
) -> EntityRelation | None:
    """Idempotently record an entity->entity edge.

    This is the edge every extraction path silently dropped until now (the
    extractor returns ``relations`` but no caller persisted them, so entity
    pages always rendered an empty "related" section). ``EntityRelation`` has no
    unique constraint, so dedup is a select-before-insert on
    ``(source_id, target_id, relation_type)``. Self-loops are skipped.
    """
    if source_entity_id == target_entity_id:
        return None
    existing = (
        await db.execute(
            select(EntityRelation).where(
                EntityRelation.source_id == source_entity_id,
                EntityRelation.target_id == target_entity_id,
                EntityRelation.relation_type == relation_type,
            )
        )
    ).scalars().first()
    if existing is not None:
        if recording_id is not None:
            existing.recording_id = recording_id
        if context:
            existing.context = context
        return existing
    relation = EntityRelation(
        source_id=source_entity_id,
        target_id=target_entity_id,
        relation_type=relation_type,
        recording_id=recording_id,
        context=context,
    )
    db.add(relation)
    await db.flush()
    await _mark_dossier_dirty(db, source_entity_id, target_entity_id)
    return relation


async def _mark_dossier_dirty(db: AsyncSession, *entity_ids: Any) -> None:
    """Flip touched entities' dossiers dirty so the bounded sweep (P3) refreshes
    them. Cheap UPDATE, no LLM; called only when a NEW mention/relation lands.

    Gated by the recompile flag so the zero-LLM bulk-sync path stays write-cheap
    when the feature is off — entity pages still compile on-demand when viewed
    (``ensure_entity_page``), so nothing goes stale; the sweep is just proactive.
    """
    if not get_settings().brain_dossier_recompile_enabled:
        return
    ids = [eid for eid in entity_ids if eid is not None]
    if not ids:
        return
    await db.execute(
        update(Entity)
        .where(Entity.id.in_(ids))
        .values(dossier_dirty=True, dossier_dirty_at=datetime.now(timezone.utc))
    )


async def seed_entities_from_summary(
    db: AsyncSession,
    user_id: Any,
    *,
    source_kind: str,
    source_id: Any,
    people: list[str] | None,
    topics: list[str] | None,
    projects: list[str] | None = None,
) -> int:
    """Promote a summary's ``people_mentioned`` + ``topics`` (+ optional
    ``projects``) into graph entities and mentions — zero extra LLM cost — so
    the source becomes a graph citizen.

    ``projects`` is only passed by chat linking, where the extractor
    distinguishes projects from generic topics; recordings/items leave it
    ``None`` and the behaviour is unchanged.

    Returns the number of mentions recorded.
    """
    count = 0
    for raw, etype in (
        *[(p, "person") for p in (people or [])],
        *[(pr, "project") for pr in (projects or [])],
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


_EXTRACTION_ENTITY_TYPES = {"person", "topic", "project", "organization"}
# Cap the transcript fed to extraction so the +1 Cerebras call stays bounded.
_EXTRACTION_TRANSCRIPT_CAP = 24000


@dataclass
class ExtractionSeedResult:
    mentions_recorded: int
    relations_recorded: int
    persons_seeded: int

    def as_dict(self) -> dict[str, int]:
        return {
            "mentions_recorded": self.mentions_recorded,
            "relations_recorded": self.relations_recorded,
            "persons_seeded": self.persons_seeded,
        }


async def seed_entities_from_extraction(
    db: AsyncSession,
    user_id: Any,
    *,
    source_kind: str,
    source_id: Any,
    entities: list[Any],
    recording_id: Any | None = None,
) -> ExtractionSeedResult:
    """Promote TYPED extracted entities (and their relations) into the graph.

    Unlike :func:`seed_entities_from_summary` (which collapses organization /
    project into a generic ``topic`` node and drops relations entirely), this
    keeps ``person / project / topic / organization`` DISTINCT and writes
    ``EntityRelation`` edges between co-extracted entities — so entity wiki pages
    finally render a non-empty "related" section.

    ``entities`` is a list of :class:`app.core.summarizer.EntityResult`
    (``name``, ``type``, ``context``, ``relations=[{related_to, relation_type}]``).
    Relations resolve ONLY against the entities seeded in this call — no
    fabricated target nodes.
    """
    name_to_entity: dict[str, Entity] = {}
    mentions = 0
    persons = 0
    for ext in entities:
        name = (getattr(ext, "name", "") or "").strip()
        if not name:
            continue
        etype = (getattr(ext, "type", "") or "").strip().lower()
        if etype not in _EXTRACTION_ENTITY_TYPES:
            etype = "topic"
        context = (getattr(ext, "context", "") or "").strip() or None
        entity = await upsert_entity(db, user_id, type=etype, name=name)
        if entity is None:
            continue
        await record_mention(
            db,
            user_id=user_id,
            entity_id=entity.id,
            source_kind=source_kind,
            source_id=source_id,
            context=context,
        )
        mentions += 1
        if etype == "person":
            persons += 1
        key = normalise_name(name)
        if key:
            name_to_entity[key] = entity

    relations = 0
    for ext in entities:
        src_key = normalise_name((getattr(ext, "name", "") or ""))
        src = name_to_entity.get(src_key) if src_key else None
        if src is None:
            continue
        context = (getattr(ext, "context", "") or "").strip() or None
        for rel in (getattr(ext, "relations", None) or []):
            target_key = normalise_name((rel.get("related_to") or "").strip())
            target = name_to_entity.get(target_key) if target_key else None
            if target is None or target.id == src.id:
                continue
            await record_relation(
                db,
                source_entity_id=src.id,
                target_entity_id=target.id,
                relation_type=rel.get("relation_type"),
                recording_id=recording_id,
                context=context,
            )
            relations += 1

    if persons:
        await reconcile_person_entities(db, user_id)
    return ExtractionSeedResult(
        mentions_recorded=mentions,
        relations_recorded=relations,
        persons_seeded=persons,
    )


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

    recording_has_entities = or_(
        func.coalesce(func.jsonb_array_length(Summary.people_mentioned), 0) > 0,
        func.coalesce(func.jsonb_array_length(Summary.topics), 0) > 0,
    )
    recording_missing_mentions = ~(
        select(EntityMention.id)
        .where(
            EntityMention.user_id == Recording.user_id,
            EntityMention.source_kind == "recording",
            EntityMention.source_id == Summary.recording_id,
        )
        .exists()
    )
    recording_stmt = (
        select(
            Recording.user_id,
            Summary.recording_id,
            Summary.people_mentioned,
            Summary.topics,
        )
        .join(Recording, Recording.id == Summary.recording_id)
        .where(
            Recording.deleted_at.is_(None),
            recording_has_entities,
            recording_missing_mentions,
        )
        .order_by(Summary.updated_at.asc(), Summary.id.asc())
    )
    if user_id is not None:
        recording_stmt = recording_stmt.where(Recording.user_id == user_id)
    if limit is not None:
        recording_stmt = recording_stmt.limit(limit)
    recording_rows = (await db.execute(recording_stmt)).all()

    remaining = None if limit is None else max(limit - len(recording_rows), 0)
    item_has_entities = or_(
        func.coalesce(func.jsonb_array_length(ItemSummary.people_mentioned), 0) > 0,
        func.coalesce(func.jsonb_array_length(ItemSummary.topics), 0) > 0,
    )
    item_missing_mentions = ~(
        select(EntityMention.id)
        .where(
            EntityMention.user_id == Item.user_id,
            EntityMention.source_kind == "item",
            EntityMention.source_id == ItemSummary.item_id,
        )
        .exists()
    )
    item_stmt = (
        select(Item.user_id, ItemSummary.item_id, ItemSummary.people_mentioned, ItemSummary.topics)
        .join(Item, Item.id == ItemSummary.item_id)
        .where(Item.deleted_at.is_(None), item_has_entities, item_missing_mentions)
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

    await db.flush()
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


@dataclass
class EntityExtractionBackfillResult:
    recordings_scanned: int
    recordings_extracted: int
    mentions_recorded: int
    relations_recorded: int
    llm_requests: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "recordings_scanned": self.recordings_scanned,
            "recordings_extracted": self.recordings_extracted,
            "mentions_recorded": self.mentions_recorded,
            "relations_recorded": self.relations_recorded,
            "llm_requests": self.llm_requests,
        }


async def backfill_entity_extraction_for_recordings(
    db: AsyncSession,
    user_id: Any | None = None,
    *,
    limit: int | None = None,
    extractor=None,
) -> EntityExtractionBackfillResult:
    """Run rich entity + relation extraction over EXISTING recordings.

    Targets recordings that have a transcript + summary but no
    ``EntityRelation.recording_id`` yet (relations are the new artifact, so their
    absence marks "not richly extracted"). Operator-gated by ``limit`` — it
    spends one Cerebras call per recording, so it never runs on a beat schedule.
    Per-recording failures are isolated and logged.
    """
    from app.core.summarizer import extract_entities  # lazy: avoid import cycle
    from app.core.summary_generation import build_summary_transcript

    extract = extractor or extract_entities

    has_relation = (
        select(EntityRelation.id)
        .where(EntityRelation.recording_id == Recording.id)
        .exists()
    )
    stmt = (
        select(Recording.id, Recording.user_id)
        .join(Summary, Summary.recording_id == Recording.id)
        .where(Recording.deleted_at.is_(None), ~has_relation)
        .order_by(Recording.created_at.asc(), Recording.id.asc())
    )
    if user_id is not None:
        stmt = stmt.where(Recording.user_id == user_id)
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).all()

    recordings_extracted = 0
    mentions = 0
    relations = 0
    llm_requests = 0
    for rec_id, owner_id in rows:
        segments = (
            await db.execute(
                select(Segment)
                .where(Segment.recording_id == rec_id)
                .order_by(Segment.start_ms.asc())
            )
        ).scalars().all()
        if not segments:
            continue
        transcript = build_summary_transcript(segments)
        if not transcript:
            continue
        try:
            extracted = await extract(transcript[:_EXTRACTION_TRANSCRIPT_CAP])
            llm_requests += 1
        except Exception as exc:  # noqa: BLE001 — per-recording isolation; log + continue
            logger.warning(
                "entity extraction backfill failed recording=%s err=%s", rec_id, exc
            )
            continue
        result = await seed_entities_from_extraction(
            db,
            owner_id,
            source_kind="recording",
            source_id=rec_id,
            entities=extracted,
            recording_id=rec_id,
        )
        mentions += result.mentions_recorded
        relations += result.relations_recorded
        if result.mentions_recorded or result.relations_recorded:
            recordings_extracted += 1
    await db.flush()
    return EntityExtractionBackfillResult(
        recordings_scanned=len(rows),
        recordings_extracted=recordings_extracted,
        mentions_recorded=mentions,
        relations_recorded=relations,
        llm_requests=llm_requests,
    )


@dataclass
class FactReconcileResult:
    added: int
    superseded: int
    noop: int
    # (new_fact_id, conflicting_existing_id) pairs the caller routes to review.
    conflicts: list[tuple[str, str]]


async def apply_fact_reconcile(
    db: AsyncSession,
    user_id: Any,
    subject_entity_id: Any,
    facts: list[ExtractedFact],
    *,
    source_kind: str | None = None,
    source_id: Any | None = None,
    now: datetime | None = None,
) -> FactReconcileResult:
    """Reconcile extracted facts for one subject into ``entity_facts`` —
    supersede, never delete.

    Loads the subject's currently-valid facts, classifies each new fact
    (NOOP/ADD/SUPERSEDE/CONFLICT via :func:`decide_fact_actions`), writes new rows,
    and CLOSES superseded windows (sets ``invalid_at`` + ``superseded_by_id``).
    Returns counts plus the conflicts to route to a review proposal. Pure
    persistence of the decision — no LLM, no extraction here.
    """
    now = now or datetime.now(timezone.utc)
    current_rows = (
        await db.execute(
            select(EntityFact).where(
                EntityFact.user_id == user_id,
                EntityFact.subject_entity_id == subject_entity_id,
                EntityFact.invalid_at.is_(None),
            )
        )
    ).scalars().all()
    current = [
        CurrentFact(
            id=str(row.id),
            predicate=row.predicate,
            object_text=row.object_text,
            content_hash=row.content_hash,
        )
        for row in current_rows
    ]
    by_id = {str(row.id): row for row in current_rows}

    added = superseded = noop = 0
    conflicts: list[tuple[str, str]] = []
    for decision in decide_fact_actions(facts, current):
        if decision.action == "noop":
            noop += 1
            continue
        new_fact = EntityFact(
            user_id=user_id,
            subject_entity_id=subject_entity_id,
            predicate=normalize_predicate(decision.fact.predicate),
            object_text=decision.fact.object_text.strip(),
            source_kind=source_kind,
            source_id=source_id,
            confidence=decision.fact.confidence,
            importance=decision.fact.importance,
            valid_at=decision.fact.valid_at,
            content_hash=decision.fact.content_hash,
        )
        db.add(new_fact)
        await db.flush()
        added += 1
        if decision.action == "supersede" and decision.supersedes_id in by_id:
            old = by_id[decision.supersedes_id]
            old.invalid_at = decision.fact.valid_at or now
            old.superseded_by_id = new_fact.id
            superseded += 1
        elif decision.action == "conflict":
            conflicts.append((str(new_fact.id), decision.supersedes_id or ""))
    await db.flush()
    return FactReconcileResult(
        added=added, superseded=superseded, noop=noop, conflicts=conflicts
    )
