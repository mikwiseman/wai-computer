"""Comparison-set routes — forward several items, get a comparison table.

``POST /comparisons`` creates a set from >= 2 item ids (status=generating) and
enqueues background table generation (schema induction + per-item extraction).
``GET /comparisons`` lists the user's sets; ``GET /comparisons/{id}`` returns
one with its columns + rows.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Database
from app.core.comparison import ComparisonResult, to_markdown
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


def _to_csv(columns: list | None, rows: list | None) -> str:
    col_names = [c.get("name", "") for c in (columns or [])]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Item", *col_names])
    for row in rows or []:
        values = row.get("values") or {}
        writer.writerow(
            [row.get("title") or ""]
            + ["" if values.get(name) is None else values.get(name) for name in col_names]
        )
    return buf.getvalue()


@router.get("/{comparison_id}/export")
async def export_comparison(
    comparison_id: UUID,
    user: CurrentUser,
    db: Database,
    format: str = Query("md", pattern="^(md|csv)$"),
) -> Response:
    """Export a ready comparison table as Markdown or CSV."""
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
    if cs.status != "ready" or not cs.columns:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Comparison is not ready to export.",
        )

    if format == "csv":
        return Response(content=_to_csv(cs.columns, cs.rows), media_type="text/csv")
    result = ComparisonResult(
        columns=cs.columns or [], rows=cs.rows or [], rationale=cs.schema_rationale or ""
    )
    return Response(content=to_markdown(result), media_type="text/markdown")


class EditCellRequest(BaseModel):
    item_id: str
    column: str
    value: str | None = None


@router.patch("/{comparison_id}", response_model=ComparisonResponse)
async def edit_comparison_cell(
    comparison_id: UUID,
    request: EditCellRequest,
    user: CurrentUser,
    db: Database,
) -> ComparisonResponse:
    """Edit a single cell of a comparison table (flags the row as user-edited)."""
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

    col_names = {c.get("name") for c in (cs.columns or [])}
    if request.column not in col_names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown column: {request.column}",
        )

    rows = [dict(r) for r in (cs.rows or [])]
    found = False
    for row in rows:
        if str(row.get("item_id")) == request.item_id:
            values = dict(row.get("values") or {})
            values[request.column] = request.value
            row["values"] = values
            row["edited"] = True
            found = True
            break
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not in this comparison."
        )
    cs.rows = rows  # reassign so SQLAlchemy persists the JSONB change
    await db.flush()
    return _response(cs)
