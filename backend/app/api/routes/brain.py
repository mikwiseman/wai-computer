"""Brain route — the compiled-wiki projection of canonical memory (read-only)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser, Database
from app.core.brain import compile_brain

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
