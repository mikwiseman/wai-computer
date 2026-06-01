"""Compiled-wiki ("Brain") projection of the user's canonical memory.

A read-only view that compiles what the second brain durably knows about the
user into a browsable wiki (Karpathy "compiled wiki" / gbrain compiled-truth):

- ``memory_sections`` — the long-term ``UserMemoryBlock`` markdown blocks
  (human / topics / preferences …), the cacheable facts the Companion always
  has in context.
- ``entity_pages`` — each ``Entity`` (person / topic / project) with its
  relations, the self-wired knowledge graph rendered as linkable pages.

This is a projection only: it never writes. The source of truth stays in the
memory blocks + entity tables; this just makes them human-browsable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import user_memory as user_memory_module
from app.models.entity import Entity, EntityRelation


@dataclass
class MemorySection:
    label: str
    body: str
    updated_at: str | None


@dataclass
class EntityRelationView:
    relation_type: str | None
    target_name: str
    target_type: str
    context: str | None


@dataclass
class EntityPage:
    id: str
    name: str
    type: str
    relations: list[EntityRelationView] = field(default_factory=list)


@dataclass
class BrainProjection:
    memory_sections: list[MemorySection]
    entity_pages: list[EntityPage]
    entity_count: int


async def compile_brain(db: AsyncSession, user_id: uuid.UUID) -> BrainProjection:
    """Compile the user's canonical memory into the browsable Brain projection."""
    # Memory blocks (seeded so the section set is stable even when empty).
    blocks = await user_memory_module.get_or_seed_blocks(db, user_id)
    sections: list[MemorySection] = []
    for label in user_memory_module.BLOCK_SPECS:
        block = blocks.get(label)
        if block is None:
            continue
        updated = getattr(block, "updated_at", None)
        sections.append(
            MemorySection(
                label=label,
                body=block.body or "",
                updated_at=updated.isoformat() if updated else None,
            )
        )

    # Entities + their outgoing relations (target names resolved in one pass).
    entities = (
        await db.execute(
            select(Entity)
            .where(Entity.user_id == user_id)
            .order_by(Entity.name)
        )
    ).scalars().all()

    entity_by_id = {e.id: e for e in entities}
    pages: list[EntityPage] = []
    if entities:
        relations = (
            await db.execute(
                select(EntityRelation).where(
                    EntityRelation.source_id.in_([e.id for e in entities])
                )
            )
        ).scalars().all()
        rels_by_source: dict[uuid.UUID, list[EntityRelation]] = {}
        for rel in relations:
            rels_by_source.setdefault(rel.source_id, []).append(rel)

        for entity in entities:
            rel_views: list[EntityRelationView] = []
            for rel in rels_by_source.get(entity.id, []):
                target = entity_by_id.get(rel.target_id)
                rel_views.append(
                    EntityRelationView(
                        relation_type=rel.relation_type,
                        target_name=target.name if target else "(unknown)",
                        target_type=target.type if target else "unknown",
                        context=rel.context,
                    )
                )
            pages.append(
                EntityPage(
                    id=str(entity.id),
                    name=entity.name,
                    type=entity.type,
                    relations=rel_views,
                )
            )

    return BrainProjection(
        memory_sections=sections,
        entity_pages=pages,
        entity_count=len(entities),
    )
