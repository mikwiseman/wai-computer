"""Comparison-set routes — forward several items, get a comparison table.

``POST /comparisons`` creates a set from >= 2 item ids (status=generating) and
enqueues background table generation (schema induction + per-item extraction).
``GET /comparisons`` lists the user's sets; ``GET /comparisons/{id}`` returns
one with its columns + rows.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Database
from app.models.comparison import ComparisonSet
from app.models.item import Item

router = APIRouter(prefix="/comparisons", tags=["comparisons"])

logger = logging.getLogger(__name__)


class CreateComparisonRequest(BaseModel):
    item_ids: list[UUID] = Field(min_length=2, max_length=25)
    title: str | None = Field(default=None, max_length=500)
    intent: str | None = Field(default=None, max_length=500)


class ComparisonResponse(BaseModel):
    id: str
    title: str | None
    item_ids: list[str]
    columns: list[Any] | None
    rows: list[Any] | None
    schema_rationale: str | None
    intent: str | None
    status: str
    created_at: str


class ComparisonListEntry(BaseModel):
    id: str
    title: str | None
    item_count: int
    status: str
    created_at: str


def _response(cs: ComparisonSet) -> ComparisonResponse:
    return ComparisonResponse(
        id=str(cs.id),
        title=cs.title,
        item_ids=[str(i) for i in (cs.item_ids or [])],
        columns=cs.columns,
        rows=cs.rows,
        schema_rationale=cs.schema_rationale,
        intent=cs.intent,
        status=cs.status,
        created_at=cs.created_at.isoformat(),
    )


@router.post("", response_model=ComparisonResponse, status_code=status.HTTP_201_CREATED)
async def create_comparison(
    request: CreateComparisonRequest,
    user: CurrentUser,
    db: Database,
) -> ComparisonResponse:
    """Create a comparison set from >= 2 of the user's items; build in background."""
    # De-dupe (preserve order); a set must compare >= 2 DISTINCT items.
    ids = list(dict.fromkeys(str(i) for i in request.item_ids))
    if len(ids) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A comparison needs at least 2 distinct items.",
        )

    # Validate ownership of every (distinct) item.
    owned = (
        await db.execute(
            select(Item.id).where(
                Item.user_id == user.id,
                Item.id.in_([UUID(i) for i in ids]),
                Item.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    owned_set = {str(i) for i in owned}
    missing = [i for i in ids if i not in owned_set]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Items not found: {', '.join(missing)}",
        )

    cs = ComparisonSet(
        user_id=user.id,
        title=request.title,
        item_ids=ids,
        intent=request.intent,
        status="generating",
    )
    db.add(cs)
    await db.flush()

    try:
        from app.tasks.comparison_generation import generate_comparison_task

        generate_comparison_task.delay(comparison_id=str(cs.id), intent=request.intent)
    except Exception as exc:  # noqa: BLE001 — broker down: mark failed, never a stuck "generating" row
        logger.warning("comparison enqueue failed id=%s: %s", cs.id, exc)
        cs.status = "failed"
        await db.flush()

    return _response(cs)


@router.get("", response_model=list[ComparisonListEntry])
async def list_comparisons(
    user: CurrentUser,
    db: Database,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[ComparisonListEntry]:
    rows = (
        await db.execute(
            select(ComparisonSet)
            .where(ComparisonSet.user_id == user.id)
            .order_by(ComparisonSet.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return [
        ComparisonListEntry(
            id=str(cs.id),
            title=cs.title,
            item_count=len(cs.item_ids or []),
            status=cs.status,
            created_at=cs.created_at.isoformat(),
        )
        for cs in rows
    ]


@router.get("/{comparison_id}", response_model=ComparisonResponse)
async def get_comparison(
    comparison_id: UUID,
    user: CurrentUser,
    db: Database,
) -> ComparisonResponse:
    cs = (
        await db.execute(
            select(ComparisonSet).where(
                ComparisonSet.id == comparison_id,
                ComparisonSet.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if cs is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _response(cs)


@router.post("/{comparison_id}/rebuild", response_model=ComparisonResponse)
async def rebuild_comparison(
    comparison_id: UUID,
    user: CurrentUser,
    db: Database,
) -> ComparisonResponse:
    """Re-run a comparison's generation (e.g. after a transient failure), reusing
    its stored intent — the user's escape hatch for a stuck/failed set."""
    cs = (
        await db.execute(
            select(ComparisonSet).where(
                ComparisonSet.id == comparison_id,
                ComparisonSet.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if cs is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    cs.status = "generating"
    await db.flush()
    try:
        from app.tasks.comparison_generation import generate_comparison_task

        generate_comparison_task.delay(comparison_id=str(cs.id), intent=cs.intent)
    except Exception as exc:  # noqa: BLE001 — broker down: mark failed, never stuck "generating"
        logger.warning("comparison rebuild enqueue failed id=%s: %s", cs.id, exc)
        cs.status = "failed"
        await db.flush()
    return _response(cs)


@router.delete("/{comparison_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comparison(
    comparison_id: UUID,
    user: CurrentUser,
    db: Database,
) -> None:
    cs = (
        await db.execute(
            select(ComparisonSet).where(
                ComparisonSet.id == comparison_id,
                ComparisonSet.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if cs is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await db.delete(cs)
