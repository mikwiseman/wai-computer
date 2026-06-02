"""Entity routes for knowledge graph."""

from dataclasses import asdict
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Database
from app.core.brain_graph import build_entity_page
from app.core.entity_dedup import find_duplicate_entity_candidates, merge_entities
from app.models.entity import Entity, EntityRelation

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


class EntityDetailResponse(EntityResponse):
    """Detailed response for an entity with relations."""

    relations: list[EntityRelationResponse]


@router.get("", response_model=list[EntityResponse])
async def list_entities(
    user: CurrentUser,
    db: Database,
    type: Literal["person", "topic", "project", "organization"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[EntityResponse]:
    """List all entities for the user."""
    query = select(Entity).where(Entity.user_id == user.id)

    if type:
        query = query.where(Entity.type == type)

    query = query.order_by(Entity.name).offset(offset).limit(limit)

    result = await db.execute(query)
    entities = result.scalars().all()

    return [
        EntityResponse(
            id=str(e.id),
            type=e.type,
            name=e.name,
            metadata=e.metadata_,
            created_at=e.created_at,
        )
        for e in entities
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
    occurred_at: str | None = None


class RelatedEntityResponse(BaseModel):
    id: str
    name: str
    type: str
    shared: int


class EntityCitationResponse(BaseModel):
    id: str
    source_kind: str
    source_id: str
    title: str
    context: str | None
    occurred_at: str | None


class EntityPageFactResponse(BaseModel):
    id: str
    text: str
    citation_ids: list[str]


class EntityTimelineEventResponse(BaseModel):
    id: str
    title: str
    description: str | None
    occurred_at: str | None
    citation_ids: list[str]


class RelatedEntityExplanationResponse(BaseModel):
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
    """The cached wiki page for one entity."""

    id: str
    name: str
    type: str
    mention_count: int
    sources: list[EntitySourceResponse]
    related: list[RelatedEntityResponse]
    overview: str
    facts: list[EntityPageFactResponse]
    citations: list[EntityCitationResponse]
    timeline: list[EntityTimelineEventResponse]
    related_explanations: list[RelatedEntityExplanationResponse]
    questions: list[EntityPageQuestionResponse]
    actions: list[EntityPageActionResponse]
    cache_status: str


@router.get("/{entity_id}/page", response_model=EntityPageResponse)
async def get_entity_page(
    entity_id: UUID,
    user: CurrentUser,
    db: Database,
) -> EntityPageResponse:
    """Wiki page for one entity: the items/recordings that mention it (backlinks)
    + related entities ranked by shared sources."""
    page = await build_entity_page(db, user.id, entity_id)
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
