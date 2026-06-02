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
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import Entity, EntityMention, EntityPageSnapshot
from app.models.highlight import Highlight
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
    occurred_at: str | None = None


@dataclass
class RelatedEntity:
    id: str
    name: str
    type: str
    shared: int


@dataclass
class EntityCitation:
    id: str
    source_kind: str
    source_id: str
    title: str
    context: str | None
    occurred_at: str | None


@dataclass
class EntityPageFact:
    id: str
    text: str
    citation_ids: list[str]


@dataclass
class EntityTimelineEvent:
    id: str
    title: str
    description: str | None
    occurred_at: str | None
    citation_ids: list[str]


@dataclass
class RelatedEntityExplanation:
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
    citations: list[EntityCitation]
    timeline: list[EntityTimelineEvent]
    related_explanations: list[RelatedEntityExplanation]
    questions: list[EntityPageQuestion]
    actions: list[EntityPageAction]
    cache_status: str


@dataclass
class _SourceMaterial:
    source_kind: str
    source_id: uuid.UUID
    title: str
    context: str | None
    occurred_at: datetime | None
    updated_at: datetime | None
    summary: str | None
    key_points: list[Any]
    decisions: list[Any]
    action_items: list[Any]
    highlights: list[Any]
    key_moments: list[Any]

    @property
    def citation_id(self) -> str:
        return f"{self.source_kind}:{self.source_id}"


def _iso(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _first_text(value: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, dict):
        for key in keys:
            text = _clean_text(value.get(key))
            if text:
                return text
    return None


def _json_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_sentence(value: str | None) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    for delimiter in (". ", "? ", "! "):
        if delimiter in text:
            head = text.split(delimiter, 1)[0].strip()
            if head:
                return f"{head}{delimiter[0]}"
    return text[:280]


def _append_unique_text(
    rows: list[tuple[str, list[str]]],
    seen: set[str],
    text: str | None,
    citation_id: str,
    *,
    limit: int,
) -> None:
    clean = _clean_text(text)
    if not clean or clean.lower() in seen or len(rows) >= limit:
        return
    seen.add(clean.lower())
    rows.append((clean, [citation_id]))


def _action_from_value(value: Any, citation_id: str, index: int) -> EntityPageAction | None:
    if isinstance(value, str):
        text = _clean_text(value)
        owner = due_date = status = None
    elif isinstance(value, dict):
        text = _first_text(value, ("task", "action", "title", "text", "description"))
        owner = _clean_text(value.get("owner"))
        due_date = _clean_text(value.get("due_date") or value.get("due"))
        status = _clean_text(value.get("status"))
    else:
        return None
    if not text:
        return None
    return EntityPageAction(
        id=f"action-{index}",
        text=text,
        owner=owner,
        due_date=due_date,
        status=status,
        citation_ids=[citation_id],
    )


def _compile_overview(entity: Entity, sources: list[_SourceMaterial]) -> str:
    if not sources:
        return f"{entity.name} has no linked sources yet."
    newest = max(
        sources,
        key=lambda source: source.occurred_at or source.updated_at or datetime.min.replace(
            tzinfo=timezone.utc
        ),
    )
    summary = _first_sentence(newest.summary) or _clean_text(newest.context)
    source_word = "source" if len(sources) == 1 else "sources"
    overview = (
        f"{entity.name} appears in {len(sources)} {source_word}. "
        f"Latest source: {newest.title}."
    )
    if summary:
        overview = f"{overview} {summary}"
    return overview


def _compile_snapshot_payload(
    entity: Entity,
    sources: list[_SourceMaterial],
    related_explanations: list[RelatedEntityExplanation],
) -> dict[str, Any]:
    citations = [
        EntityCitation(
            id=source.citation_id,
            source_kind=source.source_kind,
            source_id=str(source.source_id),
            title=source.title,
            context=source.context,
            occurred_at=_iso(source.occurred_at),
        )
        for source in sources
    ]

    fact_rows: list[tuple[str, list[str]]] = []
    seen_facts: set[str] = set()
    for source in sources:
        for point in source.key_points:
            _append_unique_text(
                fact_rows,
                seen_facts,
                _first_text(point, ("text", "point", "title", "summary", "description")),
                source.citation_id,
                limit=12,
            )
        for decision in source.decisions:
            _append_unique_text(
                fact_rows,
                seen_facts,
                _first_text(decision, ("decision", "text", "title", "summary")),
                source.citation_id,
                limit=12,
            )
        if not source.key_points and source.context:
            _append_unique_text(
                fact_rows,
                seen_facts,
                source.context,
                source.citation_id,
                limit=12,
            )
    facts = [
        EntityPageFact(id=f"fact-{index + 1}", text=text, citation_ids=citation_ids)
        for index, (text, citation_ids) in enumerate(fact_rows)
    ]

    timeline: list[EntityTimelineEvent] = []
    seen_events: set[str] = set()
    for source in sources:
        for moment in [*source.key_moments, *source.highlights]:
            title = _first_text(moment, ("title", "event", "text", "summary"))
            if not title or title.lower() in seen_events:
                continue
            seen_events.add(title.lower())
            description = None
            if isinstance(moment, dict):
                description = _first_text(moment, ("summary", "description", "detail"))
            timeline.append(
                EntityTimelineEvent(
                    id=f"event-{len(timeline) + 1}",
                    title=title,
                    description=description,
                    occurred_at=_iso(source.occurred_at),
                    citation_ids=[source.citation_id],
                )
            )
            if len(timeline) >= 10:
                break
        if len(timeline) >= 10:
            break
    for source in sources:
        if len(timeline) >= 10:
            break
        title = f"Mentioned in {source.title}"
        key = title.lower()
        if key in seen_events:
            continue
        seen_events.add(key)
        timeline.append(
            EntityTimelineEvent(
                id=f"event-{len(timeline) + 1}",
                title=title,
                description=source.context,
                occurred_at=_iso(source.occurred_at),
                citation_ids=[source.citation_id],
            )
        )

    questions: list[EntityPageQuestion] = []
    seen_questions: set[str] = set()
    for source in sources:
        question_candidates: list[str | None] = []
        for highlight in source.highlights:
            category = highlight.get("category") if isinstance(highlight, dict) else None
            if category == "question":
                question_candidates.append(
                    _first_text(highlight, ("title", "question", "text", "description"))
                )
        for text in (source.context, source.summary):
            clean = _clean_text(text)
            if clean and "?" in clean:
                question_candidates.extend(
                    f"{part.strip()}?" for part in clean.split("?") if part.strip()
                )
        for question in question_candidates:
            clean = _clean_text(question)
            if not clean or clean.lower() in seen_questions:
                continue
            seen_questions.add(clean.lower())
            questions.append(
                EntityPageQuestion(
                    id=f"question-{len(questions) + 1}",
                    text=clean,
                    citation_ids=[source.citation_id],
                )
            )
            if len(questions) >= 8:
                break
        if len(questions) >= 8:
            break

    actions: list[EntityPageAction] = []
    seen_actions: set[str] = set()
    for source in sources:
        for action_value in source.action_items:
            action = _action_from_value(action_value, source.citation_id, len(actions) + 1)
            if action is None or action.text.lower() in seen_actions:
                continue
            seen_actions.add(action.text.lower())
            actions.append(action)
            if len(actions) >= 12:
                break
        if len(actions) >= 12:
            break

    return {
        "overview": _compile_overview(entity, sources),
        "facts": [fact.__dict__ for fact in facts],
        "citations": [citation.__dict__ for citation in citations],
        "timeline": [event.__dict__ for event in timeline],
        "related_explanations": [
            explanation.__dict__ for explanation in related_explanations
        ],
        "questions": [question.__dict__ for question in questions],
        "actions": [action.__dict__ for action in actions],
    }


def _fingerprint_payload(
    entity: Entity,
    sources: list[_SourceMaterial],
    related_explanations: list[RelatedEntityExplanation],
) -> str:
    payload = {
        "entity": {
            "id": str(entity.id),
            "name": entity.name,
            "type": entity.type,
            "updated_at": _iso(entity.updated_at),
        },
        "sources": [
            {
                "kind": source.source_kind,
                "id": str(source.source_id),
                "title": source.title,
                "context": source.context,
                "occurred_at": _iso(source.occurred_at),
                "updated_at": _iso(source.updated_at),
                "summary": source.summary,
                "key_points": source.key_points,
                "decisions": source.decisions,
                "action_items": source.action_items,
                "highlights": source.highlights,
                "key_moments": source.key_moments,
            }
            for source in sources
        ],
        "related": [explanation.__dict__ for explanation in related_explanations],
    }
    encoded = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _page_sections_from_snapshot(snapshot: EntityPageSnapshot) -> dict[str, Any]:
    return {
        "overview": snapshot.overview,
        "facts": snapshot.facts,
        "citations": snapshot.citations,
        "timeline": snapshot.timeline,
        "related_explanations": snapshot.related_explanations,
        "questions": snapshot.questions,
        "actions": snapshot.actions,
    }


async def _source_materials(
    db: AsyncSession,
    mentions: list[tuple[str, uuid.UUID, str | None]],
) -> dict[tuple[str, uuid.UUID], _SourceMaterial]:
    item_ids = {sid for kind, sid, _ in mentions if kind == "item"}
    rec_ids = {sid for kind, sid, _ in mentions if kind == "recording"}
    materials: dict[tuple[str, uuid.UUID], _SourceMaterial] = {}
    contexts = {(kind, sid): ctx for kind, sid, ctx in mentions}

    if item_ids:
        for item, summary in (
            await db.execute(
                select(Item, ItemSummary)
                .outerjoin(ItemSummary, ItemSummary.item_id == Item.id)
                .where(Item.id.in_(item_ids), Item.deleted_at.is_(None))
            )
        ).all():
            materials[("item", item.id)] = _SourceMaterial(
                source_kind="item",
                source_id=item.id,
                title=item.title or item.url or "Untitled",
                context=contexts.get(("item", item.id)),
                occurred_at=item.occurred_at or item.created_at,
                updated_at=max(
                    item.updated_at,
                    summary.updated_at if summary is not None else item.updated_at,
                ),
                summary=summary.summary if summary is not None else None,
                key_points=_json_list(summary.key_points if summary is not None else None),
                decisions=_json_list(summary.decisions if summary is not None else None),
                action_items=_json_list(
                    summary.action_items if summary is not None else None
                ),
                highlights=_json_list(summary.highlights if summary is not None else None),
                key_moments=_json_list(
                    summary.key_moments if summary is not None else None
                ),
            )

    recording_actions: dict[uuid.UUID, list[dict[str, Any]]] = {}
    recording_highlights: dict[uuid.UUID, list[dict[str, Any]]] = {}
    if rec_ids:
        for action in (
            await db.execute(
                select(ActionItem).where(ActionItem.recording_id.in_(rec_ids))
            )
        ).scalars():
            recording_actions.setdefault(action.recording_id, []).append(
                {
                    "task": action.task,
                    "owner": action.owner,
                    "due_date": _iso(action.due_date),
                    "status": action.status,
                    "updated_at": _iso(action.updated_at),
                }
            )
        for highlight in (
            await db.execute(select(Highlight).where(Highlight.recording_id.in_(rec_ids)))
        ).scalars():
            recording_highlights.setdefault(highlight.recording_id, []).append(
                {
                    "category": highlight.category,
                    "title": highlight.title,
                    "description": highlight.description,
                    "speaker": highlight.speaker,
                    "start_ms": highlight.start_ms,
                    "end_ms": highlight.end_ms,
                }
            )

        for recording, summary in (
            await db.execute(
                select(Recording, Summary)
                .outerjoin(Summary, Summary.recording_id == Recording.id)
                .where(Recording.id.in_(rec_ids), Recording.deleted_at.is_(None))
            )
        ).all():
            materials[("recording", recording.id)] = _SourceMaterial(
                source_kind="recording",
                source_id=recording.id,
                title=recording.title or "Recording",
                context=contexts.get(("recording", recording.id)),
                occurred_at=recording.uploaded_at or recording.created_at,
                updated_at=max(
                    recording.updated_at,
                    summary.updated_at if summary is not None else recording.updated_at,
                ),
                summary=summary.summary if summary is not None else None,
                key_points=_json_list(summary.key_points if summary is not None else None),
                decisions=_json_list(summary.decisions if summary is not None else None),
                action_items=recording_actions.get(recording.id, []),
                highlights=recording_highlights.get(recording.id, []),
                key_moments=recording_highlights.get(recording.id, []),
            )
    return materials


def _snapshot_sections_to_dataclasses(sections: dict[str, Any]) -> tuple[
    list[EntityPageFact],
    list[EntityCitation],
    list[EntityTimelineEvent],
    list[RelatedEntityExplanation],
    list[EntityPageQuestion],
    list[EntityPageAction],
]:
    return (
        [EntityPageFact(**row) for row in sections["facts"]],
        [EntityCitation(**row) for row in sections["citations"]],
        [EntityTimelineEvent(**row) for row in sections["timeline"]],
        [RelatedEntityExplanation(**row) for row in sections["related_explanations"]],
        [EntityPageQuestion(**row) for row in sections["questions"]],
        [EntityPageAction(**row) for row in sections["actions"]],
    )


async def build_entity_page(
    db: AsyncSession, user_id: Any, entity_id: uuid.UUID
) -> EntityPage | None:
    """Build one cached wiki page.

    This deliberately uses already-stored summaries, highlights, mentions, and
    action items. Opening a Wiki page must not create a new LLM spend path.
    """
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
            ).order_by(
                EntityMention.created_at,
                EntityMention.source_kind,
                EntityMention.source_id,
                EntityMention.id,
            )
        )
    ).all()

    material_by_key = await _source_materials(db, mentions)
    source_materials = [
        material_by_key[(kind, sid)]
        for kind, sid, _ in mentions
        if (kind, sid) in material_by_key
    ]

    sources = [
        EntitySource(
            source_kind=source.source_kind,
            source_id=str(source.source_id),
            title=source.title,
            context=source.context,
            occurred_at=_iso(source.occurred_at),
        )
        for source in source_materials
    ]

    related: list[RelatedEntity] = []
    related_shared_sources: dict[uuid.UUID, set[tuple[str, uuid.UUID]]] = {}
    source_keys = [(kind, sid) for kind, sid, _ in mentions]
    if source_keys:
        co_rows = (
            await db.execute(
                select(
                    EntityMention.entity_id,
                    EntityMention.source_kind,
                    EntityMention.source_id,
                ).where(
                    EntityMention.user_id == user_id,
                    tuple_(EntityMention.source_kind, EntityMention.source_id).in_(
                        source_keys
                    ),
                    EntityMention.entity_id != entity_id,
                )
            )
        ).all()
        for eid, kind, sid in co_rows:
            related_shared_sources.setdefault(eid, set()).add((kind, sid))
        if related_shared_sources:
            for eid, etype, name in (
                await db.execute(
                    select(Entity.id, Entity.type, Entity.name).where(
                        Entity.id.in_(list(related_shared_sources.keys()))
                    )
                )
            ).all():
                related.append(
                    RelatedEntity(
                        id=str(eid),
                        name=name,
                        type=etype,
                        shared=len(related_shared_sources[eid]),
                    )
                )
            related.sort(key=lambda r: (-r.shared, r.name.casefold(), r.id))

    related_explanations: list[RelatedEntityExplanation] = []
    material_titles = {
        (source.source_kind, source.source_id): source.title for source in source_materials
    }
    for rel in related:
        rel_id = uuid.UUID(rel.id)
        shared_keys = sorted(
            related_shared_sources.get(rel_id, set()),
            key=lambda key: material_titles.get(key, ""),
        )
        titles = [material_titles[key] for key in shared_keys if key in material_titles]
        title_list = ", ".join(titles[:3])
        source_word = "source" if rel.shared == 1 else "sources"
        explanation = f"Shares {rel.shared} {source_word}"
        if title_list:
            explanation = f"{explanation}: {title_list}"
        if len(titles) > 3:
            explanation = f"{explanation}, +{len(titles) - 3} more"
        related_explanations.append(
            RelatedEntityExplanation(
                id=rel.id,
                name=rel.name,
                type=rel.type,
                shared=rel.shared,
                explanation=f"{explanation}.",
                citation_ids=[f"{kind}:{sid}" for kind, sid in shared_keys],
            )
        )

    fingerprint = _fingerprint_payload(entity, source_materials, related_explanations)
    snapshot = (
        await db.execute(
            select(EntityPageSnapshot).where(
                EntityPageSnapshot.user_id == user_id,
                EntityPageSnapshot.entity_id == entity_id,
            )
        )
    ).scalar_one_or_none()

    cache_status = "hit"
    if snapshot is not None and snapshot.source_fingerprint == fingerprint:
        sections = _page_sections_from_snapshot(snapshot)
    else:
        cache_status = "rebuilt"
        sections = _compile_snapshot_payload(entity, source_materials, related_explanations)
        now = datetime.now(timezone.utc)
        if snapshot is None:
            snapshot = EntityPageSnapshot(
                user_id=user_id,
                entity_id=entity_id,
                source_fingerprint=fingerprint,
                source_count=len(source_materials),
                overview=sections["overview"],
                facts=sections["facts"],
                citations=sections["citations"],
                timeline=sections["timeline"],
                related_explanations=sections["related_explanations"],
                questions=sections["questions"],
                actions=sections["actions"],
                compiled_at=now,
            )
            db.add(snapshot)
        else:
            snapshot.source_fingerprint = fingerprint
            snapshot.source_count = len(source_materials)
            snapshot.overview = sections["overview"]
            snapshot.facts = sections["facts"]
            snapshot.citations = sections["citations"]
            snapshot.timeline = sections["timeline"]
            snapshot.related_explanations = sections["related_explanations"]
            snapshot.questions = sections["questions"]
            snapshot.actions = sections["actions"]
            snapshot.compiled_at = now
        await db.flush()

    (
        facts,
        citations,
        timeline,
        cached_related_explanations,
        questions,
        actions,
    ) = _snapshot_sections_to_dataclasses(sections)

    return EntityPage(
        id=str(entity.id),
        name=entity.name,
        type=entity.type,
        mention_count=len(mentions),
        sources=sources,
        related=related,
        overview=sections["overview"],
        facts=facts,
        citations=citations,
        timeline=timeline,
        related_explanations=cached_related_explanations,
        questions=questions,
        actions=actions,
        cache_status=cache_status,
    )
