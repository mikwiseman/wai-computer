"""Live Brain Maps: cited, refreshable projections over the user's evidence."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.brain_graph import build_brain_graph
from app.core.unified_search import UnifiedHit, unified_search
from app.models.brain_map import BrainMap, BrainMapRevision
from app.models.entity import Entity, EntityMention
from app.models.item import Item
from app.models.recording import Recording

MAP_STATUS_VALUES = {"draft", "saved", "archived"}
MAP_ORIGINS = {"brain", "inbox", "agent", "wai"}
MAP_TYPES = {
    "live_mirror",
    "project_state",
    "decision",
    "relationship",
    "timeline",
    "comparison",
    "open_questions",
}
DEFAULT_MAP_LIMIT = 18


class BrainMapError(Exception):
    """Base error for explicit HTTP translation."""


class BrainMapNotFoundError(BrainMapError):
    """Map does not exist or is not visible to the user."""


class BrainMapValidationError(BrainMapError):
    """Invalid map request."""


@dataclass(frozen=True)
class _EvidenceHit:
    source_kind: str
    parent_id: str
    chunk_id: str
    title: str | None
    kind: str | None
    snippet: str
    score: float
    created_at: str | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: str | None) -> str:
    return " ".join((value or "").split())


def _shorten(value: str | None, limit: int) -> str:
    text = _clean(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _uuid_or_none(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _citation_id(source_kind: str, source_id: str | uuid.UUID) -> str:
    return f"{source_kind}:{source_id}"


def _source_node_id(source_kind: str, source_id: str | uuid.UUID) -> str:
    return f"source:{source_kind}:{source_id}"


def _entity_node_id(entity_id: str | uuid.UUID) -> str:
    return f"entity:{entity_id}"


def _node_key_set(projection: dict[str, Any] | None) -> set[str]:
    if not projection:
        return set()
    return {str(n.get("id")) for n in projection.get("nodes", []) if n.get("id")}


def _edge_key_set(projection: dict[str, Any] | None) -> set[str]:
    if not projection:
        return set()
    return {str(e.get("id")) for e in projection.get("edges", []) if e.get("id")}


def _source_key_set(projection: dict[str, Any] | None) -> set[str]:
    if not projection:
        return set()
    return {
        str(c.get("id"))
        for c in projection.get("citations", [])
        if c.get("source_kind") in {"item", "recording"} and c.get("id")
    }


def _diff_projection(
    previous: dict[str, Any] | None, current: dict[str, Any]
) -> dict[str, Any]:
    prev_nodes = _node_key_set(previous)
    next_nodes = _node_key_set(current)
    prev_edges = _edge_key_set(previous)
    next_edges = _edge_key_set(current)
    prev_sources = _source_key_set(previous)
    next_sources = _source_key_set(current)
    diff = {
        "nodes_added": len(next_nodes - prev_nodes),
        "nodes_removed": len(prev_nodes - next_nodes),
        "edges_added": len(next_edges - prev_edges),
        "edges_removed": len(prev_edges - next_edges),
        "sources_added": len(next_sources - prev_sources),
        "sources_removed": len(prev_sources - next_sources),
    }
    diff["changed"] = any(value for value in diff.values())
    return diff


def _choose_map_type(prompt: str, explicit: str | None = None) -> str:
    if explicit:
        if explicit not in MAP_TYPES:
            raise BrainMapValidationError(f"unknown map type: {explicit}")
        return explicit
    text = prompt.casefold()
    if any(word in text for word in ("compare", "сравн", "vs", "versus")):
        return "comparison"
    if any(word in text for word in ("timeline", "when", "history", "хронолог", "когда")):
        return "timeline"
    if any(word in text for word in ("decision", "decide", "решен", "выбор")):
        return "decision"
    if any(word in text for word in ("relationship", "people", "network", "связ", "люд")):
        return "relationship"
    if any(word in text for word in ("question", "gap", "unknown", "вопрос", "непонят")):
        return "open_questions"
    return "project_state"


def _title_from_prompt(prompt: str, map_type: str) -> str:
    text = _shorten(prompt, 96)
    if text:
        return text[0].upper() + text[1:]
    if map_type == "live_mirror":
        return "Live Mirror"
    return "Brain Map"


def _coerce_hit(hit: UnifiedHit | _EvidenceHit | Any) -> _EvidenceHit:
    return _EvidenceHit(
        source_kind=str(getattr(hit, "source_kind")),
        parent_id=str(getattr(hit, "parent_id")),
        chunk_id=str(getattr(hit, "chunk_id", "")),
        title=getattr(hit, "title", None),
        kind=getattr(hit, "kind", None),
        snippet=str(getattr(hit, "snippet", "") or ""),
        score=float(getattr(hit, "score", 0.0) or 0.0),
        created_at=getattr(hit, "created_at", None),
    )


async def _search_hits(
    db: AsyncSession,
    user_id: uuid.UUID,
    prompt: str,
    *,
    source_scope: dict[str, Any] | None,
    limit: int,
) -> list[_EvidenceHit]:
    raw_hits = await unified_search(db, user_id, prompt, limit=limit)
    hits = [_coerce_hit(hit) for hit in raw_hits]
    if not source_scope:
        return hits
    allowed = _allowed_scoped_sources(source_scope)
    if not allowed:
        return hits
    scoped_hits = await _scoped_source_hits(db, user_id, allowed)
    filtered = [hit for hit in hits if (hit.source_kind, hit.parent_id) in allowed]
    seen = {(hit.source_kind, hit.parent_id) for hit in filtered}
    filtered.extend(
        hit for hit in scoped_hits if (hit.source_kind, hit.parent_id) not in seen
    )
    return filtered[:limit]


def _allowed_scoped_sources(source_scope: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (str(ref.get("source_kind")), str(ref.get("source_id")))
        for ref in source_scope.get("sources", [])
        if isinstance(ref, dict)
        and ref.get("source_kind") in {"item", "recording"}
        and ref.get("source_id")
    }


async def _scoped_source_hits(
    db: AsyncSession,
    user_id: uuid.UUID,
    allowed: set[tuple[str, str]],
) -> list[_EvidenceHit]:
    item_ids = {
        sid
        for kind, raw_id in allowed
        if kind == "item" and (sid := _uuid_or_none(raw_id))
    }
    rec_ids = {
        sid
        for kind, raw_id in allowed
        if kind == "recording" and (sid := _uuid_or_none(raw_id))
    }
    hits: list[_EvidenceHit] = []
    if item_ids:
        rows = (
            await db.execute(
                select(Item.id, Item.title, Item.url, Item.body, Item.kind, Item.created_at)
                .where(Item.id.in_(item_ids), Item.user_id == user_id, Item.deleted_at.is_(None))
            )
        ).all()
        for iid, title, url, body, kind, created_at in rows:
            hits.append(
                _EvidenceHit(
                    source_kind="item",
                    parent_id=str(iid),
                    chunk_id=str(iid),
                    title=title or url or "Untitled material",
                    kind=kind,
                    snippet=_shorten(body, 280),
                    score=1.0,
                    created_at=created_at.isoformat() if created_at else None,
                )
            )
    if rec_ids:
        rows = (
            await db.execute(
                select(Recording.id, Recording.title, Recording.type, Recording.created_at)
                .where(
                    Recording.id.in_(rec_ids),
                    Recording.user_id == user_id,
                    Recording.deleted_at.is_(None),
                )
            )
        ).all()
        for rid, title, kind, created_at in rows:
            hits.append(
                _EvidenceHit(
                    source_kind="recording",
                    parent_id=str(rid),
                    chunk_id=str(rid),
                    title=title or "Recording",
                    kind=kind,
                    snippet="",
                    score=1.0,
                    created_at=created_at.isoformat() if created_at else None,
                )
            )
    return sorted(hits, key=lambda hit: hit.created_at or "", reverse=True)


async def _recent_hits(
    db: AsyncSession, user_id: uuid.UUID, *, limit: int
) -> list[_EvidenceHit]:
    item_rows = (
        await db.execute(
            select(Item.id, Item.title, Item.url, Item.body, Item.kind, Item.created_at)
            .where(Item.user_id == user_id, Item.deleted_at.is_(None))
            .order_by(Item.created_at.desc())
            .limit(max(1, limit // 2))
        )
    ).all()
    rec_rows = (
        await db.execute(
            select(Recording.id, Recording.title, Recording.type, Recording.created_at)
            .where(Recording.user_id == user_id, Recording.deleted_at.is_(None))
            .order_by(Recording.created_at.desc())
            .limit(max(1, limit // 2))
        )
    ).all()
    hits: list[_EvidenceHit] = []
    for iid, title, url, body, kind, created_at in item_rows:
        hits.append(
            _EvidenceHit(
                source_kind="item",
                parent_id=str(iid),
                chunk_id=str(iid),
                title=title or url or "Untitled material",
                kind=kind,
                snippet=_shorten(body, 280),
                score=1.0,
                created_at=created_at.isoformat() if created_at else None,
            )
        )
    for rid, title, kind, created_at in rec_rows:
        hits.append(
            _EvidenceHit(
                source_kind="recording",
                parent_id=str(rid),
                chunk_id=str(rid),
                title=title or "Recording",
                kind=kind,
                snippet="",
                score=1.0,
                created_at=created_at.isoformat() if created_at else None,
            )
        )
    return sorted(hits, key=lambda hit: hit.created_at or "", reverse=True)[:limit]


async def _owner_visible_sources(
    db: AsyncSession, user_id: uuid.UUID, hits: list[_EvidenceHit]
) -> dict[tuple[str, uuid.UUID], dict[str, Any]]:
    item_ids = {
        sid
        for hit in hits
        if hit.source_kind == "item" and (sid := _uuid_or_none(hit.parent_id))
    }
    rec_ids = {
        sid
        for hit in hits
        if hit.source_kind == "recording" and (sid := _uuid_or_none(hit.parent_id))
    }
    sources: dict[tuple[str, uuid.UUID], dict[str, Any]] = {}
    if item_ids:
        rows = (
            await db.execute(
                select(Item.id, Item.title, Item.url, Item.kind, Item.created_at)
                .where(Item.id.in_(item_ids), Item.user_id == user_id, Item.deleted_at.is_(None))
            )
        ).all()
        for iid, title, url, kind, created_at in rows:
            sources[("item", iid)] = {
                "id": _citation_id("item", iid),
                "source_kind": "item",
                "source_id": str(iid),
                "title": title or url or "Untitled material",
                "kind": kind,
                "created_at": created_at.isoformat() if created_at else None,
            }
    if rec_ids:
        rows = (
            await db.execute(
                select(Recording.id, Recording.title, Recording.type, Recording.created_at)
                .where(
                    Recording.id.in_(rec_ids),
                    Recording.user_id == user_id,
                    Recording.deleted_at.is_(None),
                )
            )
        ).all()
        for rid, title, kind, created_at in rows:
            sources[("recording", rid)] = {
                "id": _citation_id("recording", rid),
                "source_kind": "recording",
                "source_id": str(rid),
                "title": title or "Recording",
                "kind": kind,
                "created_at": created_at.isoformat() if created_at else None,
            }
    return sources


async def _mentions_for_sources(
    db: AsyncSession,
    user_id: uuid.UUID,
    source_keys: set[tuple[str, uuid.UUID]],
) -> list[tuple[uuid.UUID, str, str, str, uuid.UUID, str | None]]:
    item_ids = {sid for kind, sid in source_keys if kind == "item"}
    rec_ids = {sid for kind, sid in source_keys if kind == "recording"}
    conditions = []
    if item_ids:
        conditions.append(
            and_(
                EntityMention.source_kind == "item",
                EntityMention.source_id.in_(item_ids),
            )
        )
    if rec_ids:
        conditions.append(
            and_(EntityMention.source_kind == "recording", EntityMention.source_id.in_(rec_ids))
        )
    if not conditions:
        return []
    rows = (
        await db.execute(
            select(
                Entity.id,
                Entity.type,
                Entity.name,
                EntityMention.source_kind,
                EntityMention.source_id,
                EntityMention.context,
            )
            .join(Entity, Entity.id == EntityMention.entity_id)
            .where(EntityMention.user_id == user_id, or_(*conditions))
            .order_by(Entity.name.asc(), Entity.id.asc())
        )
    ).all()
    return list(rows)


def _layout_position(
    layout: dict[str, Any] | None,
    node_id: str,
    *,
    lane: str,
    index: int,
) -> dict[str, float]:
    override = (layout or {}).get(node_id)
    if isinstance(override, dict) and {"x", "y"} <= set(override):
        return {"x": float(override["x"]), "y": float(override["y"])}
    lane_x = {
        "center": 0,
        "projects": 340,
        "people": 340,
        "topics": 340,
        "sources": -340,
        "gaps": 0,
    }.get(lane, 0)
    lane_y_offset = {
        "center": 0,
        "projects": -160,
        "people": 40,
        "topics": 220,
        "sources": -160,
        "gaps": 260,
    }.get(lane, 0)
    return {"x": float(lane_x), "y": float(lane_y_offset + index * 120)}


def _entity_lane(entity_type: str) -> str:
    if entity_type == "project":
        return "projects"
    if entity_type in {"person", "organization"}:
        return "people"
    return "topics"


def _source_fingerprint(prompt: str, map_type: str, sources: list[dict[str, Any]]) -> str:
    parts = [prompt, map_type]
    for source in sorted(sources, key=lambda s: (s["source_kind"], s["source_id"])):
        parts.append(
            "\x1f".join(
                [
                    str(source.get("source_kind")),
                    str(source.get("source_id")),
                    str(source.get("title") or ""),
                    str(source.get("created_at") or ""),
                ]
            )
        )
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


async def _build_projection(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    prompt: str,
    title: str,
    map_type: str,
    source_scope: dict[str, Any] | None,
    layout: dict[str, Any] | None,
    hits: list[_EvidenceHit],
) -> tuple[dict[str, Any], str, list[dict[str, Any]], dict[str, Any]]:
    source_meta = await _owner_visible_sources(db, user_id, hits)
    source_keys = set(source_meta)
    mentions = await _mentions_for_sources(db, user_id, source_keys)

    hit_by_source: dict[tuple[str, uuid.UUID], _EvidenceHit] = {}
    for hit in hits:
        source_id = _uuid_or_none(hit.parent_id)
        if source_id is not None and (hit.source_kind, source_id) in source_meta:
            hit_by_source.setdefault((hit.source_kind, source_id), hit)

    citations = list(source_meta.values())
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    lens_id = "lens:root"
    nodes.append(
        {
            "id": lens_id,
            "kind": "lens",
            "title": title,
            "body": prompt,
            "lane": "center",
            "citation_ids": [],
            "position": _layout_position(layout, lens_id, lane="center", index=0),
        }
    )

    for index, ((kind, sid), source) in enumerate(
        sorted(source_meta.items(), key=lambda s: s[1]["title"])
    ):
        hit = hit_by_source.get((kind, sid))
        node_id = _source_node_id(kind, sid)
        citation_id = source["id"]
        nodes.append(
            {
                "id": node_id,
                "kind": "source",
                "title": source["title"],
                "body": _shorten(hit.snippet if hit else "", 320),
                "lane": "sources",
                "source_kind": kind,
                "source_id": str(sid),
                "citation_ids": [citation_id],
                "position": _layout_position(layout, node_id, lane="sources", index=index),
            }
        )
        edges.append(
            {
                "id": f"edge:{lens_id}:{node_id}",
                "source": lens_id,
                "target": node_id,
                "kind": "supports",
                "label": "supports",
                "citation_ids": [citation_id],
            }
        )

    entity_citations: dict[str, set[str]] = {}
    entity_meta: dict[str, tuple[str, str]] = {}
    source_entities: dict[str, set[str]] = {}
    for eid, entity_type, name, source_kind, source_id, _context in mentions:
        entity_id = str(eid)
        citation_id = _citation_id(source_kind, source_id)
        entity_meta[entity_id] = (entity_type, name)
        entity_citations.setdefault(entity_id, set()).add(citation_id)
        source_entities.setdefault(citation_id, set()).add(entity_id)

    lane_counts: dict[str, int] = {}
    for entity_id, (entity_type, name) in sorted(entity_meta.items(), key=lambda row: row[1][1]):
        lane = _entity_lane(entity_type)
        index = lane_counts.get(lane, 0)
        lane_counts[lane] = index + 1
        node_id = _entity_node_id(entity_id)
        cites = sorted(entity_citations[entity_id])
        nodes.append(
            {
                "id": node_id,
                "kind": "entity",
                "title": name,
                "body": entity_type,
                "lane": lane,
                "entity_id": entity_id,
                "entity_type": entity_type,
                "citation_ids": cites,
                "position": _layout_position(layout, node_id, lane=lane, index=index),
            }
        )

    for eid, (_entity_type, _name) in entity_meta.items():
        entity_node_id = _entity_node_id(eid)
        for citation_id in sorted(entity_citations[eid]):
            source_kind, source_id = citation_id.split(":", 1)
            source_node_id = _source_node_id(source_kind, source_id)
            edges.append(
                {
                    "id": f"edge:{source_node_id}:{entity_node_id}",
                    "source": source_node_id,
                    "target": entity_node_id,
                    "kind": "mentions",
                    "label": "mentions",
                    "citation_ids": [citation_id],
                }
            )

    seen_related: set[tuple[str, str, str]] = set()
    for citation_id, entity_ids in source_entities.items():
        ordered = sorted(entity_ids)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                key = (ordered[i], ordered[j], citation_id)
                if key in seen_related:
                    continue
                seen_related.add(key)
                a = _entity_node_id(ordered[i])
                b = _entity_node_id(ordered[j])
                edges.append(
                    {
                        "id": f"edge:{a}:{b}:{citation_id}",
                        "source": a,
                        "target": b,
                        "kind": "related_to",
                        "label": "shared source",
                        "citation_ids": [citation_id],
                    }
                )

    if not source_meta:
        gap_id = "gap:no-evidence"
        nodes.append(
            {
                "id": gap_id,
                "kind": "gap",
                "title": "No matching evidence yet",
                "body": "Wai could not find recordings or materials for this lens.",
                "lane": "gaps",
                "citation_ids": [],
                "position": _layout_position(layout, gap_id, lane="gaps", index=0),
            }
        )
        edges.append(
            {
                "id": f"edge:{lens_id}:{gap_id}",
                "source": lens_id,
                "target": gap_id,
                "kind": "open_question",
                "label": "needs evidence",
                "citation_ids": [],
            }
        )

    freshness = _freshness(citations)
    projection = {
        "version": 1,
        "map_type": map_type,
        "title": title,
        "prompt": prompt,
        "summary": _summary(map_type, len(source_meta), len(entity_meta)),
        "nodes": nodes,
        "edges": edges,
        "citations": citations,
        "freshness": freshness,
    }
    return projection, _source_fingerprint(prompt, map_type, citations), citations, freshness


def _freshness(citations: list[dict[str, Any]]) -> dict[str, Any]:
    dates: list[datetime] = []
    for citation in citations:
        raw = citation.get("created_at")
        if not isinstance(raw, str) or not raw:
            continue
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dates.append(dt.astimezone(timezone.utc))
    if not dates:
        return {"newest_source_at": None, "weeks_since": None, "stale": False}
    newest = max(dates)
    weeks = max(0, int((_now() - newest).days // 7))
    return {
        "newest_source_at": newest.isoformat(),
        "weeks_since": weeks,
        "stale": weeks >= 3,
    }


def _summary(map_type: str, source_count: int, entity_count: int) -> str:
    if source_count == 0:
        return "No matching evidence yet."
    label = map_type.replace("_", " ")
    return f"{label.title()} from {source_count} source(s) and {entity_count} linked node(s)."


async def _next_revision_index(db: AsyncSession, map_id: uuid.UUID) -> int:
    value = await db.scalar(
        select(func.max(BrainMapRevision.revision_index)).where(BrainMapRevision.map_id == map_id)
    )
    return int(value or 0) + 1


async def _current_revision(
    db: AsyncSession, brain_map: BrainMap
) -> BrainMapRevision | None:
    if brain_map.current_revision_id is None:
        return None
    return (
        await db.execute(
            select(BrainMapRevision).where(
                BrainMapRevision.id == brain_map.current_revision_id,
                BrainMapRevision.map_id == brain_map.id,
            )
        )
    ).scalar_one_or_none()


async def create_brain_map(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    prompt: str,
    origin: str = "brain",
    map_type: str | None = None,
    title: str | None = None,
    space_id: uuid.UUID | None = None,
    source_scope: dict[str, Any] | None = None,
    status: str = "draft",
    limit: int = DEFAULT_MAP_LIMIT,
) -> tuple[BrainMap, BrainMapRevision]:
    prompt = _clean(prompt)
    if not prompt:
        raise BrainMapValidationError("prompt is required")
    if origin not in MAP_ORIGINS:
        raise BrainMapValidationError(f"unknown map origin: {origin}")
    if status not in MAP_STATUS_VALUES:
        raise BrainMapValidationError(f"unknown map status: {status}")
    selected_type = _choose_map_type(prompt, map_type)
    selected_title = _clean(title) or _title_from_prompt(prompt, selected_type)
    brain_map = BrainMap(
        user_id=user_id,
        space_id=space_id,
        title=selected_title,
        prompt=prompt,
        map_type=selected_type,
        origin=origin,
        status=status,
        source_scope=source_scope,
        layout={},
    )
    db.add(brain_map)
    await db.flush()
    hits = await _search_hits(db, user_id, prompt, source_scope=source_scope, limit=limit)
    projection, fingerprint, citations, freshness = await _build_projection(
        db,
        user_id,
        prompt=prompt,
        title=selected_title,
        map_type=selected_type,
        source_scope=source_scope,
        layout=brain_map.layout,
        hits=hits,
    )
    revision = BrainMapRevision(
        map_id=brain_map.id,
        user_id=user_id,
        revision_index=1,
        projection=projection,
        source_fingerprint=fingerprint,
        source_count=len(citations),
        freshness=freshness,
        diff=_diff_projection(None, projection),
        citations=citations,
        compiled_at=_now(),
    )
    db.add(revision)
    await db.flush()
    brain_map.current_revision_id = revision.id
    await db.flush()
    return brain_map, revision


async def load_brain_map(
    db: AsyncSession, user_id: uuid.UUID, map_id: uuid.UUID
) -> tuple[BrainMap, BrainMapRevision | None]:
    brain_map = (
        await db.execute(
            select(BrainMap).where(
                BrainMap.id == map_id,
                BrainMap.user_id == user_id,
                BrainMap.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if brain_map is None:
        raise BrainMapNotFoundError("Brain Map not found")
    return brain_map, await _current_revision(db, brain_map)


async def list_brain_maps(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[tuple[BrainMap, BrainMapRevision | None]]:
    stmt = select(BrainMap).where(BrainMap.user_id == user_id, BrainMap.archived_at.is_(None))
    if status:
        stmt = stmt.where(BrainMap.status == status)
    maps = list(
        (
            await db.execute(
                stmt.order_by(
                    BrainMap.updated_at.desc(), BrainMap.created_at.desc()
                ).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    revisions: dict[uuid.UUID, BrainMapRevision] = {}
    revision_ids = [m.current_revision_id for m in maps if m.current_revision_id is not None]
    if revision_ids:
        rows = (
            await db.execute(select(BrainMapRevision).where(BrainMapRevision.id.in_(revision_ids)))
        ).scalars()
        revisions = {row.id: row for row in rows}
    return [(m, revisions.get(m.current_revision_id)) for m in maps]


async def refresh_brain_map(
    db: AsyncSession,
    user_id: uuid.UUID,
    map_id: uuid.UUID,
    *,
    limit: int = DEFAULT_MAP_LIMIT,
) -> BrainMapRevision:
    brain_map, previous = await load_brain_map(db, user_id, map_id)
    hits = await _search_hits(
        db,
        user_id,
        brain_map.prompt,
        source_scope=brain_map.source_scope,
        limit=limit,
    )
    projection, fingerprint, citations, freshness = await _build_projection(
        db,
        user_id,
        prompt=brain_map.prompt,
        title=brain_map.title,
        map_type=brain_map.map_type,
        source_scope=brain_map.source_scope,
        layout=brain_map.layout,
        hits=hits,
    )
    if previous is not None and previous.source_fingerprint == fingerprint:
        return previous
    revision = BrainMapRevision(
        map_id=brain_map.id,
        user_id=user_id,
        revision_index=await _next_revision_index(db, brain_map.id),
        projection=projection,
        source_fingerprint=fingerprint,
        source_count=len(citations),
        freshness=freshness,
        diff=_diff_projection(previous.projection if previous else None, projection),
        citations=citations,
        compiled_at=_now(),
    )
    db.add(revision)
    await db.flush()
    brain_map.current_revision_id = revision.id
    await db.flush()
    return revision


async def update_brain_map(
    db: AsyncSession,
    user_id: uuid.UUID,
    map_id: uuid.UUID,
    *,
    title: str | None = None,
    status: str | None = None,
    layout: dict[str, Any] | None = None,
) -> tuple[BrainMap, BrainMapRevision | None]:
    brain_map, revision = await load_brain_map(db, user_id, map_id)
    if title is not None:
        clean_title = _clean(title)
        if not clean_title:
            raise BrainMapValidationError("title cannot be empty")
        brain_map.title = clean_title
    if status is not None:
        if status not in MAP_STATUS_VALUES:
            raise BrainMapValidationError(f"unknown map status: {status}")
        brain_map.status = status
        if status == "archived":
            brain_map.archived_at = _now()
    if layout is not None:
        if not isinstance(layout, dict):
            raise BrainMapValidationError("layout must be an object")
        brain_map.layout = layout
    await db.flush()
    return brain_map, revision


async def list_brain_map_revisions(
    db: AsyncSession, user_id: uuid.UUID, map_id: uuid.UUID
) -> list[BrainMapRevision]:
    await load_brain_map(db, user_id, map_id)
    return list(
        (
            await db.execute(
                select(BrainMapRevision)
                .where(BrainMapRevision.map_id == map_id, BrainMapRevision.user_id == user_id)
                .order_by(BrainMapRevision.revision_index.desc())
            )
        )
        .scalars()
        .all()
    )


async def build_live_mirror(
    db: AsyncSession, user_id: uuid.UUID, *, limit: int = 40
) -> dict[str, Any]:
    hits = await _recent_hits(db, user_id, limit=limit)
    projection, fingerprint, citations, freshness = await _build_projection(
        db,
        user_id,
        prompt="Live Mirror",
        title="Live Mirror",
        map_type="live_mirror",
        source_scope=None,
        layout=None,
        hits=hits,
    )
    graph = await build_brain_graph(db, user_id, include_sources=True, limit=limit)
    projection["source_fingerprint"] = fingerprint
    projection["stats"] = graph.stats
    projection["freshness"] = freshness
    projection["citations"] = citations
    return projection
