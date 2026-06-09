"""Bounded living-wiki dossier recompile sweep (P3).

Refreshes dossiers for entities flagged dirty (a new mention/relation landed),
oldest-dirty-first, capped per run. ``ensure_entity_page`` is cache-aware, so an
unchanged source fingerprint costs no LLM — the sweep is O(changed). OFF by
default (``brain_dossier_recompile_enabled``); enable deliberately because a
genuinely-changed dossier triggers one Cerebras synthesis call.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

RECOMPILE_LIMIT = 25


async def _recompile_with_db(db: AsyncSession, limit: int) -> dict[str, int]:
    """Recompile the oldest dirty dossiers using the given session; flush (the
    caller commits). Per-entity try/except so one bad entity can't sink the batch.
    """
    from app.core.entity_page_synthesis import ensure_entity_page
    from app.models.entity import Entity

    rows = (
        await db.execute(
            select(Entity.id, Entity.user_id)
            .where(Entity.dossier_dirty.is_(True))
            .order_by(Entity.dossier_dirty_at.asc())
            .limit(limit)
        )
    ).all()

    processed = recompiled = failed = 0
    for entity_id, user_id in rows:
        processed += 1
        try:
            await ensure_entity_page(db, user_id, entity_id)
            recompiled += 1
        except Exception:  # noqa: BLE001 — isolate a bad entity, clear it, move on
            failed += 1
            logger.warning("dossier recompile failed entity=%s", entity_id, exc_info=True)
        entity = await db.get(Entity, entity_id)
        if entity is not None:
            entity.dossier_dirty = False
    await db.flush()
    return {"processed": processed, "recompiled": recompiled, "failed": failed}


async def recompile_dirty_dossiers(limit: int = RECOMPILE_LIMIT) -> dict[str, int]:
    from app.db.session import get_db_context

    async with get_db_context() as db:
        result = await _recompile_with_db(db, limit)
        await db.commit()
        return result


@celery_app.task(name="app.tasks.recompile_entity_dossiers.run")
def run() -> dict[str, object]:
    """Celery beat entry (hourly). No-op unless enabled."""
    if not get_settings().brain_dossier_recompile_enabled:
        return {"skipped": "disabled"}
    return asyncio.run(recompile_dirty_dossiers())
