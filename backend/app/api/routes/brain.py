"""Brain routes — compiled wiki, live mirror, maps, and zero-LLM graph sync."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Database
from app.core.brain import compile_brain
from app.core.brain_ask import ask_brain
from app.core.brain_feed import count_new_since_last_seen, get_brain_feed
from app.core.brain_graph import build_brain_graph
from app.core.brain_maps import (
    BrainMapError,
    BrainMapNotFoundError,
    BrainMapValidationError,
    build_live_mirror,
    create_brain_map,
    list_brain_map_revisions,
    list_brain_maps,
    load_brain_map,
    refresh_brain_map,
    update_brain_map,
)
from app.core.conversation_brain import link_unlinked_conversations
from app.core.entity_graph import backfill_entity_mentions_from_existing_summaries
from app.models.brain_map import BrainMap, BrainMapRevision

# Cap chat linking per explicit sync so the button (which extracts entities via
# the LLM for never-linked chats) can never trigger a cost spike. New chats
# auto-link on turn completion; this only chips at the legacy backlog.
CHAT_SYNC_LIMIT = 50

router = APIRouter(prefix="/brain", tags=["brain"])


class MemorySectionResponse(BaseModel):
    label: str
    body: str
    updated_at: str | None


class EntityRelationResponse(BaseModel):
    relation_type: str | None
    target_name: str
    target_type: str
    context: str | None


class EntityPageResponse(BaseModel):
    id: str
    name: str
    type: str
    relations: list[EntityRelationResponse]


class BrainResponse(BaseModel):
    memory_sections: list[MemorySectionResponse]
    entity_pages: list[EntityPageResponse]
    entity_count: int


@router.get("", response_model=BrainResponse)
async def get_brain(user: CurrentUser, db: Database) -> BrainResponse:
    """Return the compiled-wiki view of what the brain durably knows."""
    projection = await compile_brain(db, user.id)
    return BrainResponse(
        memory_sections=[
            MemorySectionResponse(label=s.label, body=s.body, updated_at=s.updated_at)
            for s in projection.memory_sections
        ],
        entity_pages=[
            EntityPageResponse(
                id=p.id,
                name=p.name,
                type=p.type,
                relations=[
                    EntityRelationResponse(
                        relation_type=r.relation_type,
                        target_name=r.target_name,
                        target_type=r.target_type,
                        context=r.context,
                    )
                    for r in p.relations
                ],
            )
            for p in projection.entity_pages
        ],
        entity_count=projection.entity_count,
    )


class BrainSyncRequest(BaseModel):
    limit: int = Field(default=500, ge=1, le=2000)
    # When true (the explicit "Link" button), also link never-linked Wai chats,
    # which extracts entities via the LLM. Left false on the cheap auto-sync
    # that runs on Brain open, so opening the Brain never spends tokens.
    include_chats: bool = False


class BrainSyncResponse(BaseModel):
    recording_summaries_scanned: int
    item_summaries_scanned: int
    sources_with_entities: int
    mentions_recorded: int
    entity_mentions_before: int
    entity_mentions_after: int
    created_mentions: int
    conversations_scanned: int
    conversations_linked: int
    llm_requests: int


class FeedCardResponse(BaseModel):
    id: str
    source_kind: str
    source_id: str
    title: str
    summary: str
    source_time: str | None
    is_new: bool


class BrainFeedResponse(BaseModel):
    cards: list[FeedCardResponse]
    next_cursor: str | None


class SinceLastSeenResponse(BaseModel):
    new_count: int
    last_seen: str | None


class SeenResponse(BaseModel):
    seen_at: str


@router.get("/feed", response_model=BrainFeedResponse)
async def get_brain_feed_route(
    user: CurrentUser,
    db: Database,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=24, ge=1, le=100),
) -> BrainFeedResponse:
    """Calm home feed: recency-ordered source cards with two-line stored summaries
    (zero LLM). Cursor-paginated; ``is_new`` flags sources newer than the watermark."""
    feed = await get_brain_feed(
        db, user.id, limit=limit, cursor=cursor, last_seen=user.brain_last_seen_at
    )
    return BrainFeedResponse(
        cards=[FeedCardResponse(**asdict(card)) for card in feed.cards],
        next_cursor=feed.next_cursor,
    )


@router.get("/since-last-seen", response_model=SinceLastSeenResponse)
async def brain_since_last_seen_route(
    user: CurrentUser, db: Database
) -> SinceLastSeenResponse:
    """How many sources are new since the user last opened the Brain."""
    new_count = await count_new_since_last_seen(db, user.id, last_seen=user.brain_last_seen_at)
    return SinceLastSeenResponse(
        new_count=new_count,
        last_seen=user.brain_last_seen_at.isoformat() if user.brain_last_seen_at else None,
    )


@router.post("/seen", response_model=SeenResponse)
async def mark_brain_seen_route(user: CurrentUser, db: Database) -> SeenResponse:
    """Stamp the Brain-seen watermark to now (called when the user opens the Brain)."""
    now = datetime.now(timezone.utc)
    user.brain_last_seen_at = now
    await db.flush()
    return SeenResponse(seen_at=now.isoformat())


@router.post("/sync", response_model=BrainSyncResponse)
async def sync_brain_route(
    user: CurrentUser,
    db: Database,
    request: BrainSyncRequest | None = None,
) -> BrainSyncResponse:
    """Repair source->entity provenance so every source is a graph citizen.

    Recordings + materials are zero-LLM (replay stored summary people/topics).
    When ``include_chats`` is set, never-linked Wai chats are extracted + linked
    too (bounded by ``CHAT_SYNC_LIMIT``) — the explicit catch-up the "Link"
    button runs. New chats already auto-link on turn completion.
    """
    request = request or BrainSyncRequest()
    result = await backfill_entity_mentions_from_existing_summaries(
        db,
        user_id=user.id,
        limit=request.limit,
    )
    payload = result.as_dict()
    conversations_scanned = conversations_linked = 0
    if request.include_chats:
        sweep = await link_unlinked_conversations(
            db, user.id, limit=min(request.limit, CHAT_SYNC_LIMIT)
        )
        conversations_scanned = sweep.conversations_scanned
        conversations_linked = sweep.conversations_linked
        payload["mentions_recorded"] += sweep.mentions_recorded
        payload["created_mentions"] += sweep.mentions_recorded
        payload["sources_with_entities"] += sweep.conversations_linked
        payload["llm_requests"] += sweep.llm_requests
    return BrainSyncResponse(
        **payload,
        conversations_scanned=conversations_scanned,
        conversations_linked=conversations_linked,
    )


class GraphNodeResponse(BaseModel):
    id: str
    label: str
    kind: str
    degree: int


class GraphEdgeResponse(BaseModel):
    source: str
    target: str
    type: str
    weight: float


class BrainSourceCoverageResponse(BaseModel):
    total: int
    summarized: int
    organized: int
    unorganized: int


class BrainOverviewEntityResponse(BaseModel):
    id: str
    name: str
    type: str
    source_count: int
    recording_count: int
    material_count: int
    chat_count: int


class BrainOverviewSourceResponse(BaseModel):
    id: str
    source_kind: str
    source_id: str
    title: str
    entity_count: int
    organized_at: str | None


class BrainOverviewResponse(BaseModel):
    recordings: BrainSourceCoverageResponse
    materials: BrainSourceCoverageResponse
    chats: BrainSourceCoverageResponse
    pending_review_count: int
    top_entities: list[BrainOverviewEntityResponse]
    recent_sources: list[BrainOverviewSourceResponse]
    llm_requests: int


class BrainGraphResponse(BaseModel):
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]
    stats: dict[str, int]
    overview: BrainOverviewResponse


@router.get("/graph", response_model=BrainGraphResponse)
async def get_brain_graph(
    user: CurrentUser,
    db: Database,
    focus: UUID | None = None,
    include_sources: bool = True,
    limit: int = Query(200, ge=10, le=2000),
) -> BrainGraphResponse:
    """Force-graph-ready nodes + edges for the Brain visualization.

    Entities (+ optionally the items/recordings that mention them) as nodes;
    co-occurrence + mention edges. ``focus`` returns the ego graph around one
    entity; ``limit`` caps entity nodes by degree.
    """
    graph = await build_brain_graph(
        db, user.id, focus=focus, include_sources=include_sources, limit=limit
    )
    return BrainGraphResponse(
        nodes=[GraphNodeResponse(**asdict(n)) for n in graph.nodes],
        edges=[GraphEdgeResponse(**asdict(e)) for e in graph.edges],
        stats=graph.stats,
        overview=BrainOverviewResponse(**asdict(graph.overview)),
    )


class BrainMapRevisionResponse(BaseModel):
    id: str
    map_id: str
    revision_index: int
    projection: dict[str, Any]
    source_fingerprint: str
    source_count: int
    freshness: dict[str, Any]
    diff: dict[str, Any]
    citations: list[dict[str, Any]]
    compiled_at: datetime
    created_at: datetime


class BrainMapResponse(BaseModel):
    id: str
    space_id: str | None
    title: str
    prompt: str
    map_type: str
    origin: str
    status: str
    source_scope: dict[str, Any] | None
    layout: dict[str, Any] | None
    current_revision_id: str | None
    current_revision: BrainMapRevisionResponse | None
    created_at: datetime
    updated_at: datetime


class BrainMapsResponse(BaseModel):
    maps: list[BrainMapResponse]


class BrainMapCreateRequest(BaseModel):
    prompt: str
    origin: str = "brain"
    map_type: str | None = None
    title: str | None = None
    space_id: UUID | None = None
    source_scope: dict[str, Any] | None = None


class BrainMapUpdateRequest(BaseModel):
    title: str | None = None
    status: str | None = None
    layout: dict[str, Any] | None = None


class BrainMapRevisionsResponse(BaseModel):
    revisions: list[BrainMapRevisionResponse]


def _raise_map_http(exc: Exception) -> None:
    if isinstance(exc, BrainMapNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, BrainMapValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if isinstance(exc, BrainMapError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    raise exc


def _revision_response(revision: BrainMapRevision) -> BrainMapRevisionResponse:
    return BrainMapRevisionResponse(
        id=str(revision.id),
        map_id=str(revision.map_id),
        revision_index=revision.revision_index,
        projection=revision.projection,
        source_fingerprint=revision.source_fingerprint,
        source_count=revision.source_count,
        freshness=revision.freshness,
        diff=revision.diff,
        citations=revision.citations,
        compiled_at=revision.compiled_at,
        created_at=revision.created_at,
    )


def _map_response(
    brain_map: BrainMap, revision: BrainMapRevision | None
) -> BrainMapResponse:
    return BrainMapResponse(
        id=str(brain_map.id),
        space_id=str(brain_map.space_id) if brain_map.space_id else None,
        title=brain_map.title,
        prompt=brain_map.prompt,
        map_type=brain_map.map_type,
        origin=brain_map.origin,
        status=brain_map.status,
        source_scope=brain_map.source_scope,
        layout=brain_map.layout,
        current_revision_id=(
            str(brain_map.current_revision_id) if brain_map.current_revision_id else None
        ),
        current_revision=_revision_response(revision) if revision else None,
        created_at=brain_map.created_at,
        updated_at=brain_map.updated_at,
    )


@router.get("/mirror")
async def get_brain_mirror(
    user: CurrentUser,
    db: Database,
    limit: int = Query(40, ge=5, le=200),
) -> dict[str, Any]:
    """The Live Mirror: an always-current visual projection over recent Brain evidence."""
    return await build_live_mirror(db, user.id, limit=limit)


@router.get("/maps", response_model=BrainMapsResponse)
async def get_brain_maps(
    user: CurrentUser,
    db: Database,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
) -> BrainMapsResponse:
    rows = await list_brain_maps(db, user.id, status=status_filter, limit=limit)
    return BrainMapsResponse(maps=[_map_response(m, r) for m, r in rows])


@router.post("/maps", response_model=BrainMapResponse, status_code=status.HTTP_201_CREATED)
async def create_brain_map_route(
    request: BrainMapCreateRequest,
    user: CurrentUser,
    db: Database,
) -> BrainMapResponse:
    try:
        brain_map, revision = await create_brain_map(
            db,
            user.id,
            prompt=request.prompt,
            origin=request.origin,
            map_type=request.map_type,
            title=request.title,
            space_id=request.space_id,
            source_scope=request.source_scope,
        )
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_map_http(exc)
    return _map_response(brain_map, revision)


@router.get("/maps/{map_id}", response_model=BrainMapResponse)
async def get_brain_map_route(
    map_id: UUID,
    user: CurrentUser,
    db: Database,
) -> BrainMapResponse:
    try:
        brain_map, revision = await load_brain_map(db, user.id, map_id)
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_map_http(exc)
    return _map_response(brain_map, revision)


@router.patch("/maps/{map_id}", response_model=BrainMapResponse)
async def update_brain_map_route(
    map_id: UUID,
    request: BrainMapUpdateRequest,
    user: CurrentUser,
    db: Database,
) -> BrainMapResponse:
    try:
        brain_map, revision = await update_brain_map(
            db,
            user.id,
            map_id,
            title=request.title,
            status=request.status,
            layout=request.layout,
        )
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_map_http(exc)
    return _map_response(brain_map, revision)


@router.post("/maps/{map_id}/refresh", response_model=BrainMapRevisionResponse)
async def refresh_brain_map_route(
    map_id: UUID,
    user: CurrentUser,
    db: Database,
) -> BrainMapRevisionResponse:
    try:
        revision = await refresh_brain_map(db, user.id, map_id)
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_map_http(exc)
    return _revision_response(revision)


@router.get("/maps/{map_id}/revisions", response_model=BrainMapRevisionsResponse)
async def get_brain_map_revisions_route(
    map_id: UUID,
    user: CurrentUser,
    db: Database,
) -> BrainMapRevisionsResponse:
    try:
        revisions = await list_brain_map_revisions(db, user.id, map_id)
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_map_http(exc)
    return BrainMapRevisionsResponse(
        revisions=[_revision_response(revision) for revision in revisions]
    )


class BrainAskRequest(BaseModel):
    question: str
    source_scope: dict[str, Any] | None = None


class BrainAnswerCitationResponse(BaseModel):
    id: str
    source_kind: str
    source_id: str
    title: str | None
    start_ms: int | None


class BrainFreshnessResponse(BaseModel):
    newest_source_at: datetime | None
    weeks_since: int | None
    stale: bool


class BrainAnswerResponse(BaseModel):
    answer: str
    citations: list[BrainAnswerCitationResponse]
    gaps: list[str]
    freshness: BrainFreshnessResponse


@router.post("/ask", response_model=BrainAnswerResponse)
async def ask_brain_route(
    request: BrainAskRequest, user: CurrentUser, db: Database
) -> BrainAnswerResponse:
    """Ask your Brain: one cited answer from your own recordings, with the
    gaps and staleness stated honestly — never an answer from outside them."""
    answer = await ask_brain(db, user.id, request.question, source_scope=request.source_scope)
    return BrainAnswerResponse(
        answer=answer.answer,
        citations=[BrainAnswerCitationResponse(**asdict(c)) for c in answer.citations],
        gaps=answer.gaps,
        freshness=BrainFreshnessResponse(**asdict(answer.freshness)),
    )
