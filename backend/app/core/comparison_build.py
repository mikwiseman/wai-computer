"""Assemble a ComparisonSet's table from its items (DB glue around comparison.py)."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.comparison import ComparisonItem, build_comparison
from app.models.comparison import ComparisonSet
from app.models.item import Item, ItemSummary

logger = logging.getLogger(__name__)


def _item_text(item: Item, summary: ItemSummary | None) -> str:
    """Prefer the summary (compact, comparable) over the raw body."""
    if summary is not None and (summary.summary or "").strip():
        kp = summary.key_points or []
        extra = ("\nKey points: " + "; ".join(str(k) for k in kp)) if kp else ""
        return (summary.summary or "") + extra
    return (item.body or "")[:4000]


async def build_comparison_set(
    db: AsyncSession,
    comparison_id: UUID,
    *,
    intent: str | None = None,
) -> ComparisonSet | None:
    """Load the set's items, build the table, persist columns/rows. Marks failed on error."""
    cs = (
        await db.execute(select(ComparisonSet).where(ComparisonSet.id == comparison_id))
    ).scalar_one_or_none()
    if cs is None:
        return None

    item_ids = [UUID(i) for i in (cs.item_ids or [])]
    items = (
        await db.execute(select(Item).where(Item.id.in_(item_ids)))
    ).scalars().all()
    # Preserve the requested order.
    by_id = {str(it.id): it for it in items}
    ordered = [by_id[i] for i in (cs.item_ids or []) if i in by_id]

    summaries = {
        str(s.item_id): s
        for s in (
            await db.execute(
                select(ItemSummary).where(ItemSummary.item_id.in_([it.id for it in ordered]))
            )
        ).scalars().all()
    }

    comparison_items = [
        ComparisonItem(
            item_id=str(it.id),
            title=(it.title or "Untitled")[:200],
            text=_item_text(it, summaries.get(str(it.id))),
        )
        for it in ordered
    ]

    try:
        result = await build_comparison(comparison_items, intent=intent)
    except Exception as exc:  # noqa: BLE001 — record failure, don't crash the worker
        cs.status = "failed"
        cs.schema_rationale = f"Comparison failed: {type(exc).__name__}"
        await db.flush()
        logger.warning("comparison build failed id=%s error=%s", comparison_id, type(exc).__name__)
        raise

    cs.columns = result.columns
    cs.rows = result.rows
    cs.schema_rationale = result.rationale
    cs.status = "ready"
    if not (cs.title or "").strip():
        cs.title = "Comparison of " + ", ".join(ci.title for ci in comparison_items[:3])
    await db.flush()
    logger.info(
        "comparison built id=%s cols=%s rows=%s",
        comparison_id,
        len(result.columns),
        len(result.rows),
    )
    return cs
