"""Entity routes for knowledge graph."""

from dataclasses import asdict
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Database
from app.core.brain_graph import build_entity_page
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


class RelatedEntityResponse(BaseModel):
    id: str
    name: str
    type: str
    shared: int


class EntityPageResponse(BaseModel):
    """The wiki page for one entity: source backlinks + related entities."""

    id: str
    name: str
    type: str
    mention_count: int
    sources: list[EntitySourceResponse]
    related: list[RelatedEntityResponse]


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


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity(
    entity_id: UUID,
    user: CurrentUser,
    db: Database,
) -> None:
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
