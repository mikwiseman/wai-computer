"""Universal item routes — "add anything" capture + the unified feed.

``POST /items`` is the signal-capture-first intake for non-audio content
(pasted text, an article URL, a forwarded link). It stores the raw item
immediately, embeds it, and enqueues background summarization (summary +
key-moments table). Re-posting the same content/URL is idempotent.

``GET /items`` is the item half of the unified feed (filterable by source /
kind / folder). ``GET /items/{id}`` returns the item with its summary and the
hero key-moments table.

Note: source fetching for URLs (YouTube/article/PDF) lands in a follow-up; for
now a URL with no body is stored as a raw item and a body can be supplied
(e.g. by a fetcher or the Telegram path). No silent fallback — an empty
paste is rejected.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Database
from app.core.item_ingest import ingest_item
from app.models.item import Item, ItemSummary

router = APIRouter(prefix="/items", tags=["items"])


class CreateItemRequest(BaseModel):
    """Add anything to the brain: a paste, a URL, or fetched content."""

    source: str = Field(default="paste", max_length=80)
    kind: str = Field(default="note", max_length=50)
    title: str | None = Field(default=None, max_length=500)
    body: str | None = None
    url: str | None = Field(default=None, max_length=2000)
    folder_id: UUID | None = None


class ItemSummaryResponse(BaseModel):
    summary: str | None
    key_points: list[Any] | None
    action_items: list[Any] | None
    topics: list[Any] | None
    people_mentioned: list[Any] | None
    highlights: list[Any] | None
    key_moments: list[Any] | None
    sentiment: str | None


class ItemResponse(BaseModel):
    id: str
    source: str
    source_ref: str | None
    url: str | None
    kind: str
    title: str | None
    body: str | None
    occurred_at: str | None
    state: str
    folder_id: str | None
    created_at: str
    summary: ItemSummaryResponse | None = None


class ItemListEntry(BaseModel):
    id: str
    source: str
    url: str | None
    kind: str
    title: str | None
    state: str
    folder_id: str | None
    occurred_at: str | None
    created_at: str
    has_summary: bool


class ItemListResponse(BaseModel):
    items: list[ItemListEntry]
    total: int


def _summary_response(summary: ItemSummary | None) -> ItemSummaryResponse | None:
    if summary is None:
        return None
    return ItemSummaryResponse(
        summary=summary.summary,
        key_points=summary.key_points,
        action_items=summary.action_items,
        topics=summary.topics,
        people_mentioned=summary.people_mentioned,
        highlights=summary.highlights,
        key_moments=summary.key_moments,
        sentiment=summary.sentiment,
    )


def _item_response(item: Item, summary: ItemSummary | None) -> ItemResponse:
    return ItemResponse(
        id=str(item.id),
        source=item.source,
        source_ref=item.source_ref,
        url=item.url,
        kind=item.kind,
        title=item.title,
        body=item.body,
        occurred_at=item.occurred_at.isoformat() if item.occurred_at else None,
        state=item.state,
        folder_id=str(item.folder_id) if item.folder_id else None,
        created_at=item.created_at.isoformat(),
        summary=_summary_response(summary),
    )


@router.post("", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    request: CreateItemRequest,
    user: CurrentUser,
    db: Database,
) -> ItemResponse:
    """Add anything to the brain. Stores immediately, summarizes in background."""
    has_body = bool((request.body or "").strip())
    has_url = bool((request.url or "").strip())
    if not has_body and not has_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide body text or a URL.",
        )

    # Stable dedup key: prefer the URL (stable before/after fetch), else body.
    dedup_key = request.url if has_url else request.body

    item, created = await ingest_item(
        db,
        user.id,
        source=request.source,
        kind=request.kind,
        title=request.title,
        body=request.body,
        url=request.url,
        folder_id=request.folder_id,
        dedup_key=dedup_key,
        embed=has_body,
    )
    await db.flush()

    if created:
        # Enqueue background processing: fetch the URL (if body-less), embed,
        # and summarize + build the key-moments table. Import lazily so the API
        # process doesn't hard-depend on Celery wiring at import time.
        try:
            from app.tasks.item_summary_generation import generate_item_summary_task

            generate_item_summary_task.delay(item_id=str(item.id))
        except Exception:  # noqa: BLE001 — broker optional in some envs; item is still saved
            pass

    summary = (
        await db.execute(select(ItemSummary).where(ItemSummary.item_id == item.id))
    ).scalar_one_or_none()
    return _item_response(item, summary)


@router.get("", response_model=ItemListResponse)
async def list_items(
    user: CurrentUser,
    db: Database,
    source: str | None = Query(None, max_length=80),
    kind: str | None = Query(None, max_length=50),
    folder_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ItemListResponse:
    """List the user's items newest-first (the item half of the unified feed)."""
    base = select(Item).where(Item.user_id == user.id, Item.deleted_at.is_(None))
    if source:
        base = base.where(Item.source == source)
    if kind:
        base = base.where(Item.kind == kind)
    if folder_id is not None:
        base = base.where(Item.folder_id == folder_id)

    rows = (
        await db.execute(
            base.order_by(Item.created_at.desc()).offset(offset).limit(limit)
        )
    ).scalars().all()

    summarized_ids = set(
        (
            await db.execute(
                select(ItemSummary.item_id).where(
                    ItemSummary.item_id.in_([r.id for r in rows])
                )
            )
        ).scalars().all()
    ) if rows else set()

    from sqlalchemy import func

    count_q = select(func.count()).select_from(
        base.order_by(None).subquery()
    )
    total = (await db.execute(count_q)).scalar() or 0

    return ItemListResponse(
        items=[
            ItemListEntry(
                id=str(r.id),
                source=r.source,
                url=r.url,
                kind=r.kind,
                title=r.title,
                state=r.state,
                folder_id=str(r.folder_id) if r.folder_id else None,
                occurred_at=r.occurred_at.isoformat() if r.occurred_at else None,
                created_at=r.created_at.isoformat(),
                has_summary=r.id in summarized_ids,
            )
            for r in rows
        ],
        total=total,
    )


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: UUID,
    user: CurrentUser,
    db: Database,
) -> ItemResponse:
    """Get one item with its summary + key-moments table."""
    item = (
        await db.execute(
            select(Item).where(
                Item.id == item_id,
                Item.user_id == user.id,
                Item.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found"
        )
    summary = (
        await db.execute(select(ItemSummary).where(ItemSummary.item_id == item.id))
    ).scalar_one_or_none()
    return _item_response(item, summary)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: UUID,
    user: CurrentUser,
    db: Database,
) -> None:
    """Soft-delete an item."""
    from datetime import datetime, timezone

    item = (
        await db.execute(
            select(Item).where(Item.id == item_id, Item.user_id == user.id)
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found"
        )
    item.deleted_at = datetime.now(timezone.utc)
    await db.flush()
