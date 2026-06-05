"""Brain route — the compiled-wiki projection of canonical memory (read-only)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import CurrentUser, Database
from app.core.brain import compile_brain
from app.core.brain_ask import ask_brain
from app.core.brain_graph import build_brain_graph

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
