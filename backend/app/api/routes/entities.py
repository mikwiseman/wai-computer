"""Entity routes for knowledge graph."""

from dataclasses import asdict
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Database
from app.core.entity_dedup import find_duplicate_entity_candidates, merge_entities
from app.core.entity_page_synthesis import ensure_entity_page
from app.models.entity import Entity, EntityMention, EntityRelation

router = APIRouter(prefix="/entities", tags=["entities"])


class EntityRelationResponse(BaseModel):
    """Response for an entity relation."""

    id: str
    target_id: str
    target_name: str
    target_type: str
    relation_type: str | None
    context: str | None


class EntityResponse(BaseModel):
    """Response for an entity."""

    id: str
    type: str
    name: str
    metadata: dict | None
    created_at: datetime
    # How many sources mention this entity — powers Pages ranking + "12 sources".
    mention_count: int = 0
    source_count: int = 0


class EntityDetailResponse(EntityResponse):
    """Detailed response for an entity with relations."""

    relations: list[EntityRelationResponse]


@router.get("", response_model=list[EntityResponse])
async def list_entities(
    user: CurrentUser,
    db: Database,
    type: Literal["person", "topic", "project", "organization"] | None = None,
    q: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[EntityResponse]:
    """List the user's entities — the browsable "Pages", ranked by how many
    sources mention each (so the people/projects/topics that matter surface
    first), optionally filtered by ``type`` and a name search ``q``.

    Each ``EntityMention`` row is one distinct source (unique per entity+source),
    so the mention count equals the source count.
    """
    counts = (
        select(EntityMention.entity_id, func.count().label("n"))
        .where(EntityMention.user_id == user.id)
        .group_by(EntityMention.entity_id)
        .subquery()
    )
    source_count = func.coalesce(counts.c.n, 0)
    query = (
        select(Entity, source_count.label("source_count"))
        .outerjoin(counts, counts.c.entity_id == Entity.id)
        .where(Entity.user_id == user.id)
    )
    if type:
        query = query.where(Entity.type == type)
    search = q.strip() if isinstance(q, str) else ""
    if search:
        query = query.where(Entity.name.ilike(f"%{search}%"))
    query = (
        query.order_by(source_count.desc(), Entity.name.asc()).offset(offset).limit(limit)
    )

    rows = (await db.execute(query)).all()
    return [
        EntityResponse(
            id=str(e.id),
            type=e.type,
            name=e.name,
            metadata=e.metadata_,
            created_at=e.created_at,
            mention_count=int(n),
            source_count=int(n),
        )
        for e, n in rows
    ]


class MergeCandidateResponse(BaseModel):
    """A near-duplicate entity pair surfaced for human-confirmed merge."""

    keep_id: str
    keep_name: str
    drop_id: str
    drop_name: str
    type: str
    score: float
    keep_mentions: int
    drop_mentions: int


# NOTE: declared BEFORE `/{entity_id}` so the literal path isn't captured by the
# UUID path param (which would 422 on "merge-candidates").
@router.get("/merge-candidates", response_model=list[MergeCandidateResponse])
async def list_merge_candidates(
    user: CurrentUser,
    db: Database,
    threshold: float = Query(0.86, ge=0.5, le=1.0),
    limit: int = Query(50, ge=1, le=200),
) -> list[MergeCandidateResponse]:
    """Fuzzy same-type near-duplicate entity pairs awaiting human-confirmed merge
    (never silently merged — exact dups are already deduped at upsert)."""
    candidates = await find_duplicate_entity_candidates(
        db, user.id, threshold=threshold, limit=limit
    )
    return [MergeCandidateResponse(**asdict(c)) for c in candidates]


class MergeEntitiesRequest(BaseModel):
    keep_id: UUID
    drop_id: UUID


@router.post("/merge", status_code=status.HTTP_200_OK)
async def merge_entities_route(
    request: MergeEntitiesRequest,
    user: CurrentUser,
    db: Database,
) -> dict:
    """Merge the ``drop`` entity into ``keep``: re-point provenance, delete drop."""
    if request.keep_id == request.drop_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="keep_id and drop_id must differ.",
        )
    merged = await merge_entities(
        db, user_id=user.id, keep_id=request.keep_id, drop_id=request.drop_id
    )
    if not merged:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or both entities not found.",
        )
    return {"status": "merged", "keep_id": str(request.keep_id)}


@router.get("/{entity_id}", response_model=EntityDetailResponse)
async def get_entity(
    entity_id: UUID,
    user: CurrentUser,
    db: Database,
) -> EntityDetailResponse:
    """Get an entity with its relations."""
    result = await db.execute(
        select(Entity)
        .where(Entity.id == entity_id, Entity.user_id == user.id)
        .options(selectinload(Entity.source_relations).selectinload(EntityRelation.target))
    )
    entity = result.scalar_one_or_none()

    if entity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entity not found",
        )

    return EntityDetailResponse(
        id=str(entity.id),
        type=entity.type,
        name=entity.name,
        metadata=entity.metadata_,
        created_at=entity.created_at,
        relations=[
            EntityRelationResponse(
                id=str(r.id),
                target_id=str(r.target_id),
                target_name=r.target.name,
                target_type=r.target.type,
                relation_type=r.relation_type,
                context=r.context,
            )
            for r in entity.source_relations
        ],
    )


class EntitySourceResponse(BaseModel):
    source_kind: str
    source_id: str
    title: str
    context: str | None
    occurred_at: datetime | None


class RelatedEntityResponse(BaseModel):
    id: str
    name: str
    type: str
    shared: int


class EntityPageCitationResponse(BaseModel):
    id: str
    source_kind: str
    source_id: str
    title: str
    context: str | None
    occurred_at: datetime | None


class EntityPageFactResponse(BaseModel):
    id: str
    text: str
    citation_ids: list[str]


class EntityPageTimelineEventResponse(BaseModel):
    id: str
    title: str
    description: str | None
    occurred_at: datetime | None
    citation_ids: list[str]


class EntityPageRelatedExplanationResponse(BaseModel):
    id: str
    name: str
    type: str
    shared: int
    explanation: str
    citation_ids: list[str]


class EntityPageQuestionResponse(BaseModel):
    id: str
    text: str
    citation_ids: list[str]


class EntityPageActionResponse(BaseModel):
    id: str
    text: str
    owner: str | None
    due_date: str | None
    status: str | None
    citation_ids: list[str]


class EntityPageResponse(BaseModel):
    """The wiki page for one entity: source backlinks + related entities."""

    id: str
    name: str
    type: str
    mention_count: int
    sources: list[EntitySourceResponse]
    related: list[RelatedEntityResponse]
    overview: str
    facts: list[EntityPageFactResponse]
    citations: list[EntityPageCitationResponse]
    timeline: list[EntityPageTimelineEventResponse]
    related_explanations: list[EntityPageRelatedExplanationResponse]
    questions: list[EntityPageQuestionResponse]
    actions: list[EntityPageActionResponse]
    cache_status: str


@router.get("/{entity_id}/page", response_model=EntityPageResponse)
async def get_entity_page(
    entity_id: UUID,
    user: CurrentUser,
    db: Database,
) -> EntityPageResponse:
    """The living dossier for one entity: a compiled-truth overview + cited
    facts, a cited timeline, open questions, and action items, over the
    items/recordings that mention it. Synthesis runs inline on a cache miss."""
    page = await ensure_entity_page(db, user.id, entity_id)
    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found"
        )
    return EntityPageResponse(**asdict(page))


class CreateEntityRequest(BaseModel):
    """Request to create an entity."""

    type: Literal["person", "topic", "project", "organization"]
    name: str
    metadata: dict | None = None


@router.post("", response_model=EntityResponse, status_code=status.HTTP_201_CREATED)
async def create_entity(
    request: CreateEntityRequest,
    user: CurrentUser,
    db: Database,
) -> EntityResponse:
    """Create a new entity."""
    entity = Entity(
        user_id=user.id,
        type=request.type,
        name=request.name,
        metadata_=request.metadata,
    )
    db.add(entity)
    await db.flush()

    return EntityResponse(
        id=str(entity.id),
        type=entity.type,
        name=entity.name,
        metadata=entity.metadata_,
        created_at=entity.created_at,
    )


@router.delete(
    "/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_entity(
    entity_id: UUID,
    user: CurrentUser,
    db: Database,
) -> Response:
    """Delete an entity."""
    result = await db.execute(
        select(Entity).where(Entity.id == entity_id, Entity.user_id == user.id)
    )
    entity = result.scalar_one_or_none()

    if entity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entity not found",
        )

    await db.delete(entity)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
