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

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import Entity, EntityMention
from app.models.item import Item
from app.models.recording import Recording


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
class BrainGraph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    stats: dict[str, int]


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
            ).where(EntityMention.user_id == user_id)
        )
    ).all()

    degree: dict[str, int] = {}
    source_entities: dict[tuple[str, uuid.UUID], set[str]] = {}
    entity_sources: dict[str, set[tuple[str, uuid.UUID]]] = {}
    for eid, kind, sid in mention_rows:
        e = str(eid)
        if e not in entity_meta:
            continue
        s = (kind, sid)
        degree[e] = degree.get(e, 0) + 1
        source_entities.setdefault(s, set()).add(e)
        entity_sources.setdefault(e, set()).add(s)

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
    return BrainGraph(nodes=nodes, edges=edges, stats=stats)


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

    return EntityPage(
        id=str(entity.id),
        name=entity.name,
        type=entity.type,
        mention_count=len(mentions),
        sources=sources,
        related=related,
        overview=_entity_page_overview(entity.name, len(sources)),
        facts=[],
        citations=citations,
        timeline=[],
        related_explanations=related_explanations,
        questions=[],
        actions=[],
        cache_status="computed",
    )
