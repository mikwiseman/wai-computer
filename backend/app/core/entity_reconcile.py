"""Reconcile graph person-Entities with the Person (voiceprint/speaker) directory.

A single human can exist twice: as a graph ``Entity`` (type=person, seeded from a
summary's ``people_mentioned``) AND as a ``Person`` (a known speaker with
voiceprints). They're the same person — link them so the brain doesn't carry two
disconnected identities and a graph node can resolve to its known speaker.

EXACT normalised-name match only (display_name or any alias) — per the product
decision, fuzzy / embedding-similar candidates are NEVER silently merged; those
belong in the human Review queue. The link is stored in
``Entity.metadata_["person_id"]`` (no schema change) and is idempotent.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.name_moderation import normalise_name
from app.models.entity import Entity
from app.models.person import Person

logger = logging.getLogger(__name__)


async def reconcile_person_entities(db: AsyncSession, user_id: Any) -> int:
    """Auto-link person-Entities to known Persons by exact normalised name.

    Returns the count of newly-linked entities. Stores the match in
    ``Entity.metadata_['person_id']``; re-running is a no-op (idempotent).
    """
    people = (
        await db.execute(select(Person).where(Person.user_id == user_id))
    ).scalars().all()
    if not people:
        return 0

    # Normalised name (display_name + aliases) -> person. First writer wins, so a
    # later alias can't clobber a primary display-name match.
    by_name: dict[str, Person] = {}
    for person in people:
        for raw in (person.display_name, *(person.aliases or [])):
            key = normalise_name(str(raw)) if raw is not None else None
            if key and key not in by_name:
                by_name[key] = person

    entities = (
        await db.execute(
            select(Entity).where(Entity.user_id == user_id, Entity.type == "person")
        )
    ).scalars().all()

    linked = 0
    for entity in entities:
        # entity.name is already normalised (upsert_entity stores normalise_name).
        person = by_name.get(entity.name)
        if person is None:
            continue
        meta = dict(entity.metadata_ or {})
        if meta.get("person_id") == str(person.id):
            continue  # already linked
        meta["person_id"] = str(person.id)
        entity.metadata_ = meta  # reassign so SQLAlchemy persists the JSONB change
        linked += 1

    if linked:
        await db.flush()
    return linked
