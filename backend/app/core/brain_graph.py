"""Build the force-graph-ready knowledge graph for the Brain visualization.

Nodes are entities (person/topic/project) plus — when ``include_sources`` —
the items/recordings that mention them ("note" nodes, the Obsidian feel).
Edges are:

- ``cooccurrence``: entity<->entity, when two entities share a source (the
  strongest relevance signal — weight = number of shared sources).
- ``mention``: source->entity (from ``EntityMention``).

``focus`` returns the ego graph around one entity (it + entities sharing a
source with it). ``limit`` caps entity nodes (top by degree) so a growing graph
never ships a hairball. Returns an honest empty graph when there's no data —
never fabricated edges.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brain_space import BrainReviewPack, BrainSpace
from app.models.entity import Entity, EntityMention, EntityPageSnapshot
from app.models.item import Item, ItemSummary
from app.models.recording import ActionItem, Recording, Summary


@dataclass
class GraphNode:
    id: str
    label: str
    kind: str  # person | topic | project | <other entity type> | item | recording
    degree: int


@dataclass
class GraphEdge:
    source: str
    target: str
    type: str  # cooccurrence | mention
    weight: float


@dataclass
class SourceCoverage:
    total: int
    summarized: int
    organized: int
    unorganized: int


@dataclass
class BrainOverviewEntity:
    id: str
    name: str
    type: str
    source_count: int
    recording_count: int
    material_count: int


@dataclass
class BrainOverviewSource:
    id: str
    source_kind: str
    source_id: str
    title: str
    entity_count: int
    organized_at: str | None


@dataclass
class BrainOverview:
    recordings: SourceCoverage
    materials: SourceCoverage
    pending_review_count: int
    top_entities: list[BrainOverviewEntity]
    recent_sources: list[BrainOverviewSource]
    llm_requests: int


@dataclass
class BrainGraph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    stats: dict[str, int]
    overview: BrainOverview


async def build_brain_graph(
    db: AsyncSession,
    user_id: Any,
    *,
    focus: uuid.UUID | None = None,
    include_sources: bool = True,
    limit: int = 200,
) -> BrainGraph:
    entity_rows = (
        await db.execute(
            select(Entity.id, Entity.type, Entity.name).where(Entity.user_id == user_id)
        )
    ).all()
    entity_meta: dict[str, tuple[str, str]] = {
        str(eid): (etype, name) for eid, etype, name in entity_rows
    }

    mention_rows = (
        await db.execute(
            select(
                EntityMention.entity_id,
                EntityMention.source_kind,
                EntityMention.source_id,
                EntityMention.updated_at,
            ).where(EntityMention.user_id == user_id)
        )
    ).all()

    degree: dict[str, int] = {}
    source_entities: dict[tuple[str, uuid.UUID], set[str]] = {}
    entity_sources: dict[str, set[tuple[str, uuid.UUID]]] = {}
    source_organized_at: dict[tuple[str, uuid.UUID], datetime] = {}
    for eid, kind, sid, updated_at in mention_rows:
        e = str(eid)
        if e not in entity_meta:
            continue
        s = (kind, sid)
        degree[e] = degree.get(e, 0) + 1
        source_entities.setdefault(s, set()).add(e)
        entity_sources.setdefault(e, set()).add(s)
        if updated_at is not None:
            current = source_organized_at.get(s)
            if current is None or updated_at > current:
                source_organized_at[s] = updated_at

    # Which entities are in the view.
    if focus is not None:
        f = str(focus)
        included: set[str] = set()
        if f in entity_meta:
            included.add(f)
            for s in entity_sources.get(f, set()):
                included |= source_entities.get(s, set())
            if len(included) > limit:
                included = set(
                    sorted(included, key=lambda e: degree.get(e, 0), reverse=True)[:limit]
                )
    else:
        included = set(
            sorted(entity_meta.keys(), key=lambda e: degree.get(e, 0), reverse=True)[:limit]
        )

    nodes: list[GraphNode] = []
    for e in included:
        etype, name = entity_meta[e]
        nodes.append(GraphNode(id=e, label=name, kind=etype, degree=degree.get(e, 0)))

    # Co-occurrence edges (entity<->entity) among included entities.
    edge_weight: dict[tuple[str, str], int] = {}
    for ents in source_entities.values():
        inc = sorted(e for e in ents if e in included)
        for i in range(len(inc)):
            for j in range(i + 1, len(inc)):
                key = (inc[i], inc[j])
                edge_weight[key] = edge_weight.get(key, 0) + 1
    edges: list[GraphEdge] = [
        GraphEdge(source=a, target=b, type="cooccurrence", weight=float(w))
        for (a, b), w in edge_weight.items()
    ]

    item_ids: set[uuid.UUID] = set()
    rec_ids: set[uuid.UUID] = set()
    if include_sources:
        for e in included:
            for kind, sid in entity_sources.get(e, set()):
                if kind == "item":
                    item_ids.add(sid)
                elif kind == "recording":
                    rec_ids.add(sid)

        present: dict[str, set[uuid.UUID]] = {"item": set(), "recording": set()}
        if item_ids:
            rows = (
                await db.execute(
                    select(Item.id, Item.title, Item.url).where(
                        Item.id.in_(item_ids), Item.deleted_at.is_(None)
                    )
                )
            ).all()
            for iid, title, url in rows:
                present["item"].add(iid)
                nodes.append(
                    GraphNode(
                        id=f"item:{iid}",
                        label=(title or url or "Untitled"),
                        kind="item",
                        degree=0,
                    )
                )
        if rec_ids:
            rows = (
                await db.execute(
                    select(Recording.id, Recording.title).where(
                        Recording.id.in_(rec_ids), Recording.deleted_at.is_(None)
                    )
                )
            ).all()
            for rid, title in rows:
                present["recording"].add(rid)
                nodes.append(
                    GraphNode(
                        id=f"recording:{rid}",
                        label=(title or "Recording"),
                        kind="recording",
                        degree=0,
                    )
                )

        for (kind, sid), ents in source_entities.items():
            if kind not in present or sid not in present[kind]:
                continue
            src_node = f"{kind}:{sid}"
            for e in ents:
                if e in included:
                    edges.append(
                        GraphEdge(source=src_node, target=e, type="mention", weight=1.0)
                    )

    stats = {
        "entities": len(included),
        "people": sum(1 for e in included if entity_meta[e][0] == "person"),
        "topics": sum(1 for e in included if entity_meta[e][0] == "topic"),
        "items": len(item_ids),
        "recordings": len(rec_ids),
        "mentions": len(mention_rows),
    }
    overview = await _build_brain_overview(
        db,
        user_id,
        entity_meta=entity_meta,
        entity_sources=entity_sources,
        source_entities=source_entities,
        source_organized_at=source_organized_at,
    )
    return BrainGraph(nodes=nodes, edges=edges, stats=stats, overview=overview)


async def _build_brain_overview(
    db: AsyncSession,
    user_id: Any,
    *,
    entity_meta: dict[str, tuple[str, str]],
    entity_sources: dict[str, set[tuple[str, uuid.UUID]]],
    source_entities: dict[tuple[str, uuid.UUID], set[str]],
    source_organized_at: dict[tuple[str, uuid.UUID], datetime],
) -> BrainOverview:
    recording_rows = (
        await db.execute(
            select(Recording.id, Recording.title, Recording.created_at, Recording.updated_at)
            .where(Recording.user_id == user_id, Recording.deleted_at.is_(None))
            .order_by(Recording.created_at.desc(), Recording.id.asc())
        )
    ).all()
    item_rows = (
        await db.execute(
            select(Item.id, Item.title, Item.url, Item.occurred_at, Item.created_at)
            .where(Item.user_id == user_id, Item.deleted_at.is_(None))
            .order_by(Item.created_at.desc(), Item.id.asc())
        )
    ).all()

    recording_ids = {rid for rid, _, _, _ in recording_rows}
    item_ids = {iid for iid, _, _, _, _ in item_rows}

    summarized_recording_ids: set[uuid.UUID] = set()
    if recording_ids:
        summarized_recording_ids = {
            rid
            for (rid,) in (
                await db.execute(
                    select(Summary.recording_id).where(
                        Summary.recording_id.in_(recording_ids)
                    )
                )
            ).all()
        }

    summarized_item_ids: set[uuid.UUID] = set()
    if item_ids:
        summarized_item_ids = {
            iid
            for (iid,) in (
                await db.execute(
                    select(ItemSummary.item_id).where(ItemSummary.item_id.in_(item_ids))
                )
            ).all()
        }

    organized_recording_ids = {
        sid
        for (kind, sid), ents in source_entities.items()
        if kind == "recording" and sid in recording_ids and ents
    }
    organized_item_ids = {
        sid
        for (kind, sid), ents in source_entities.items()
        if kind == "item" and sid in item_ids and ents
    }

    pending_review_count = int(
        await db.scalar(
            select(func.count(BrainReviewPack.id))
            .join(BrainSpace, BrainSpace.id == BrainReviewPack.space_id)
            .where(
                BrainSpace.owner_user_id == user_id,
                BrainReviewPack.status == "pending",
            )
        )
        or 0
    )

    top_entities: list[BrainOverviewEntity] = []
    for entity_id, sources in entity_sources.items():
        if entity_id not in entity_meta:
            continue
        recording_count = sum(
            1 for kind, sid in sources if kind == "recording" and sid in recording_ids
        )
        material_count = sum(1 for kind, sid in sources if kind == "item" and sid in item_ids)
        source_count = recording_count + material_count
        if source_count == 0:
            continue
        entity_type, name = entity_meta[entity_id]
        top_entities.append(
            BrainOverviewEntity(
                id=entity_id,
                name=name,
                type=entity_type,
                source_count=source_count,
                recording_count=recording_count,
                material_count=material_count,
            )
        )
    top_entities.sort(
        key=lambda entity: (
            entity.source_count,
            entity.recording_count,
            entity.material_count,
            entity.name.lower(),
        ),
        reverse=True,
    )

    recent_candidates: list[tuple[str, str, BrainOverviewSource]] = []
    for rid, title, created_at, updated_at in recording_rows:
        source_key = ("recording", rid)
        source_id = f"recording:{rid}"
        source_time = updated_at or created_at
        recent_candidates.append(
            (
                source_time.isoformat() if source_time else "",
                source_id,
                BrainOverviewSource(
                    id=source_id,
                    source_kind="recording",
                    source_id=str(rid),
                    title=title or "Recording",
                    entity_count=len(source_entities.get(source_key, set())),
                    organized_at=_isoformat(source_organized_at.get(source_key)),
                ),
            )
        )
    for iid, title, url, occurred_at, created_at in item_rows:
        source_key = ("item", iid)
        source_id = f"item:{iid}"
        source_time = occurred_at or created_at
        recent_candidates.append(
            (
                source_time.isoformat() if source_time else "",
                source_id,
                BrainOverviewSource(
                    id=source_id,
                    source_kind="item",
                    source_id=str(iid),
                    title=title or url or "Untitled",
                    entity_count=len(source_entities.get(source_key, set())),
                    organized_at=_isoformat(source_organized_at.get(source_key)),
                ),
            )
        )
    recent_candidates.sort(key=lambda candidate: (candidate[0], candidate[1]), reverse=True)

    return BrainOverview(
        recordings=SourceCoverage(
            total=len(recording_ids),
            summarized=len(summarized_recording_ids),
            organized=len(organized_recording_ids),
            unorganized=max(0, len(recording_ids) - len(organized_recording_ids)),
        ),
        materials=SourceCoverage(
            total=len(item_ids),
            summarized=len(summarized_item_ids),
            organized=len(organized_item_ids),
            unorganized=max(0, len(item_ids) - len(organized_item_ids)),
        ),
        pending_review_count=pending_review_count,
        top_entities=top_entities[:8],
        recent_sources=[source for _, _, source in recent_candidates[:8]],
        llm_requests=0,
    )


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass
class EntitySource:
    source_kind: str
    source_id: str
    title: str
    context: str | None
    occurred_at: datetime | None


@dataclass
class RelatedEntity:
    id: str
    name: str
    type: str
    shared: int


@dataclass
class EntityPageCitation:
    id: str
    source_kind: str
    source_id: str
    title: str
    context: str | None
    occurred_at: datetime | None


@dataclass
class EntityPageFact:
    id: str
    text: str
    citation_ids: list[str]


@dataclass
class EntityPageTimelineEvent:
    id: str
    title: str
    description: str | None
    occurred_at: datetime | None
    citation_ids: list[str]


@dataclass
class EntityPageRelatedExplanation:
    id: str
    name: str
    type: str
    shared: int
    explanation: str
    citation_ids: list[str]


@dataclass
class EntityPageQuestion:
    id: str
    text: str
    citation_ids: list[str]


@dataclass
class EntityPageAction:
    id: str
    text: str
    owner: str | None
    due_date: str | None
    status: str | None
    citation_ids: list[str]


@dataclass
class EntityPage:
    id: str
    name: str
    type: str
    mention_count: int
    sources: list[EntitySource]
    related: list[RelatedEntity]
    overview: str
    facts: list[EntityPageFact]
    citations: list[EntityPageCitation]
    timeline: list[EntityPageTimelineEvent]
    related_explanations: list[EntityPageRelatedExplanation]
    questions: list[EntityPageQuestion]
    actions: list[EntityPageAction]
    cache_status: str


def _source_label(count: int) -> str:
    return "source" if count == 1 else "sources"


def _entity_page_overview(name: str, mention_count: int) -> str:
    if mention_count == 0:
        return f"{name} has not appeared in any sources yet."
    return f"{name} appears in {mention_count} {_source_label(mention_count)}."


def _citation_id(source_kind: str, source_id: uuid.UUID | str) -> str:
    return f"{source_kind}:{source_id}"


def _source_fingerprint(citation_ids: list[str], entity_updated_at: datetime | None) -> str:
    payload = "\x00".join(sorted(citation_ids))
    if entity_updated_at is not None:
        payload += f"\x00{entity_updated_at.isoformat()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def entity_source_fingerprint(page: EntityPage, entity_updated_at: datetime | None) -> str:
    """Cache key for an entity's compiled dossier — its source set + entity mtime."""
    return _source_fingerprint([c.id for c in page.citations], entity_updated_at)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _facts_from_snapshot(rows: Any) -> list[EntityPageFact]:
    out: list[EntityPageFact] = []
    for i, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        out.append(
            EntityPageFact(
                id=f"fact:{i}", text=text, citation_ids=list(row.get("citation_ids") or [])
            )
        )
    return out


def _timeline_from_snapshot(rows: Any) -> list[EntityPageTimelineEvent]:
    out: list[EntityPageTimelineEvent] = []
    for i, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        description = row.get("description")
        out.append(
            EntityPageTimelineEvent(
                id=f"event:{i}",
                title=title,
                description=str(description).strip() if description else None,
                occurred_at=_parse_iso(row.get("occurred_at")),
                citation_ids=list(row.get("citation_ids") or []),
            )
        )
    return out


def _questions_from_snapshot(rows: Any) -> list[EntityPageQuestion]:
    out: list[EntityPageQuestion] = []
    for i, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        out.append(
            EntityPageQuestion(
                id=f"question:{i}", text=text, citation_ids=list(row.get("citation_ids") or [])
            )
        )
    return out


async def build_entity_page(
    db: AsyncSession, user_id: Any, entity_id: uuid.UUID
) -> EntityPage | None:
    """The wiki page for one entity: its source backlinks (items/recordings that
    mention it) + related entities (co-occurrence, ranked by shared sources).
    Returns None if the entity isn't the user's."""
    entity = (
        await db.execute(
            select(Entity).where(Entity.id == entity_id, Entity.user_id == user_id)
        )
    ).scalar_one_or_none()
    if entity is None:
        return None

    mentions = (
        await db.execute(
            select(
                EntityMention.source_kind,
                EntityMention.source_id,
                EntityMention.context,
            ).where(
                EntityMention.user_id == user_id,
                EntityMention.entity_id == entity_id,
            )
        )
    ).all()

    item_ids = {sid for kind, sid, _ in mentions if kind == "item"}
    rec_ids = {sid for kind, sid, _ in mentions if kind == "recording"}
    source_meta: dict[tuple[str, uuid.UUID], tuple[str, datetime | None]] = {}
    if item_ids:
        for iid, title, url, occurred_at, created_at in (
            await db.execute(
                select(
                    Item.id,
                    Item.title,
                    Item.url,
                    Item.occurred_at,
                    Item.created_at,
                ).where(
                    Item.id.in_(item_ids), Item.deleted_at.is_(None)
                )
            )
        ).all():
            source_meta[("item", iid)] = (title or url or "Untitled", occurred_at or created_at)
    if rec_ids:
        for rid, title, uploaded_at, created_at in (
            await db.execute(
                select(
                    Recording.id,
                    Recording.title,
                    Recording.uploaded_at,
                    Recording.created_at,
                ).where(
                    Recording.id.in_(rec_ids), Recording.deleted_at.is_(None)
                )
            )
        ).all():
            source_meta[("recording", rid)] = (title or "Recording", uploaded_at or created_at)

    sources = [
        EntitySource(
            source_kind=kind,
            source_id=str(sid),
            title=source_meta[(kind, sid)][0],
            context=ctx,
            occurred_at=source_meta[(kind, sid)][1],
        )
        for kind, sid, ctx in mentions
        if (kind, sid) in source_meta
    ]
    citations = [
        EntityPageCitation(
            id=_citation_id(source.source_kind, source.source_id),
            source_kind=source.source_kind,
            source_id=source.source_id,
            title=source.title,
            context=source.context,
            occurred_at=source.occurred_at,
        )
        for source in sources
    ]

    related: list[RelatedEntity] = []
    related_source_keys: dict[uuid.UUID, set[tuple[str, uuid.UUID]]] = {}
    source_keys = {(kind, sid) for kind, sid, _ in mentions if (kind, sid) in source_meta}
    source_ids = {sid for _, sid in source_keys}
    if source_keys:
        co_rows = (
            await db.execute(
                select(
                    EntityMention.entity_id,
                    EntityMention.source_kind,
                    EntityMention.source_id,
                ).where(
                    EntityMention.user_id == user_id,
                    EntityMention.source_id.in_(source_ids),
                    EntityMention.entity_id != entity_id,
                )
            )
        ).all()
        for eid, kind, sid in co_rows:
            key = (kind, sid)
            if key in source_keys:
                related_source_keys.setdefault(eid, set()).add(key)
        if related_source_keys:
            for eid, etype, name in (
                await db.execute(
                    select(Entity.id, Entity.type, Entity.name).where(
                        Entity.id.in_(list(related_source_keys.keys()))
                    )
                )
            ).all():
                related.append(
                    RelatedEntity(
                        id=str(eid),
                        name=name,
                        type=etype,
                        shared=len(related_source_keys[eid]),
                    )
                )
            related.sort(key=lambda r: (-r.shared, r.name.lower()))

    related_explanations = [
        EntityPageRelatedExplanation(
            id=rel.id,
            name=rel.name,
            type=rel.type,
            shared=rel.shared,
            explanation=(
                f"Shares {rel.shared} {_source_label(rel.shared)} with {entity.name}."
            ),
            citation_ids=[
                _citation_id(kind, sid)
                for kind, sid in sorted(
                    related_source_keys.get(uuid.UUID(rel.id), set()),
                    key=lambda value: (value[0], str(value[1])),
                )
            ],
        )
        for rel in related
    ]

    # Action items from the recordings that mention this entity, kept only when
    # they actually name it (deterministic — never an LLM guess).
    actions: list[EntityPageAction] = []
    if rec_ids:
        name_l = entity.name.lower()
        ai_rows = (
            await db.execute(select(ActionItem).where(ActionItem.recording_id.in_(rec_ids)))
        ).scalars().all()
        for ai in ai_rows:
            task_text = ai.task or ""
            owner = ai.owner or ""
            relevant = (name_l and name_l in task_text.lower()) or (
                entity.type == "person" and name_l and name_l in owner.lower()
            )
            if not relevant:
                continue
            actions.append(
                EntityPageAction(
                    id=str(ai.id),
                    text=task_text,
                    owner=ai.owner,
                    due_date=ai.due_date.isoformat() if ai.due_date else None,
                    status=ai.status,
                    citation_ids=[_citation_id("recording", ai.recording_id)],
                )
            )

    # Compiled dossier (overview/facts/timeline/questions) from the cached
    # snapshot when it still matches the current source set; otherwise the page
    # is a deterministic skeleton flagged for (re)synthesis ("stale"), or an
    # honest empty when there is nothing to compile ("skeleton").
    fingerprint = _source_fingerprint([c.id for c in citations], entity.updated_at)
    snapshot = (
        await db.execute(
            select(EntityPageSnapshot).where(EntityPageSnapshot.entity_id == entity_id)
        )
    ).scalar_one_or_none()
    template_overview = _entity_page_overview(entity.name, len(sources))
    if snapshot is not None and snapshot.source_fingerprint == fingerprint:
        overview = (snapshot.overview or "").strip() or template_overview
        facts = _facts_from_snapshot(snapshot.facts)
        timeline = _timeline_from_snapshot(snapshot.timeline)
        questions = _questions_from_snapshot(snapshot.questions)
        cache_status = "ready"
    else:
        overview = template_overview
        facts = []
        timeline = []
        questions = []
        cache_status = "stale" if citations else "skeleton"

    return EntityPage(
        id=str(entity.id),
        name=entity.name,
        type=entity.type,
        mention_count=len(mentions),
        sources=sources,
        related=related,
        overview=overview,
        facts=facts,
        citations=citations,
        timeline=timeline,
        related_explanations=related_explanations,
        questions=questions,
        actions=actions,
        cache_status=cache_status,
    )
