"""Brain route — the compiled-wiki projection of canonical memory (read-only)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, Database
from app.core.brain import compile_brain
from app.core.brain_ask import ask_brain
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
from app.models.brain_map import BrainMap, BrainMapRevision

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


class BrainGraphResponse(BaseModel):
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]
    stats: dict[str, int]


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
    answer = await ask_brain(db, user.id, request.question)
    return BrainAnswerResponse(
        answer=answer.answer,
        citations=[BrainAnswerCitationResponse(**asdict(c)) for c in answer.citations],
        gaps=answer.gaps,
        freshness=BrainFreshnessResponse(**asdict(answer.freshness)),
    )
