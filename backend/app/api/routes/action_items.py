"""Action items routes."""

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, Database
from app.models.recording import ActionItem, Recording

router = APIRouter(prefix="/action-items", tags=["action-items"])


class ActionItemResponse(BaseModel):
    """Response for an action item."""

    id: str
    recording_id: str
    task: str
    owner: str | None
    due_date: str | None
    priority: str | None
    status: str
    source: str
    created_at: str


class UpdateActionItemRequest(BaseModel):
    """Request to update an action item."""

    task: str | None = None
    owner: str | None = None
    due_date: str | None = None
    priority: Literal["high", "medium", "low"] | None = None
    status: Literal["pending", "in_progress", "completed", "cancelled"] | None = None


@router.get("", response_model=list[ActionItemResponse])
async def list_action_items(
    user: CurrentUser,
    db: Database,
    status_filter: Literal["pending", "in_progress", "completed", "cancelled"] | None = Query(
        None, alias="status"
    ),
    priority: Literal["high", "medium", "low"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[ActionItemResponse]:
    """List all action items for the user."""
    query = (
        select(ActionItem)
        .join(Recording)
        .where(Recording.user_id == user.id)
    )

    if status_filter:
        query = query.where(ActionItem.status == status_filter)
    if priority:
        query = query.where(ActionItem.priority == priority)

    query = query.order_by(ActionItem.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    items = result.scalars().all()

    return [
        ActionItemResponse(
            id=str(item.id),
            recording_id=str(item.recording_id),
            task=item.task,
            owner=item.owner,
            due_date=item.due_date.isoformat() if item.due_date else None,
            priority=item.priority,
            status=item.status,
            source=item.source,
            created_at=item.created_at.isoformat(),
        )
        for item in items
    ]


@router.get("/{item_id}", response_model=ActionItemResponse)
async def get_action_item(
    item_id: UUID,
    user: CurrentUser,
    db: Database,
) -> ActionItemResponse:
    """Get a specific action item."""
    result = await db.execute(
        select(ActionItem)
        .join(Recording)
        .where(ActionItem.id == item_id, Recording.user_id == user.id)
    )
    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action item not found",
        )

    return ActionItemResponse(
        id=str(item.id),
        recording_id=str(item.recording_id),
        task=item.task,
        owner=item.owner,
        due_date=item.due_date.isoformat() if item.due_date else None,
        priority=item.priority,
        status=item.status,
        source=item.source,
        created_at=item.created_at.isoformat(),
    )


@router.patch("/{item_id}", response_model=ActionItemResponse)
async def update_action_item(
    item_id: UUID,
    request: UpdateActionItemRequest,
    user: CurrentUser,
    db: Database,
) -> ActionItemResponse:
    """Update an action item."""
    result = await db.execute(
        select(ActionItem)
        .join(Recording)
        .where(ActionItem.id == item_id, Recording.user_id == user.id)
    )
    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action item not found",
        )

    if "task" in request.model_fields_set and request.task is not None:
        item.task = request.task
    if "owner" in request.model_fields_set:
        item.owner = request.owner
    if "due_date" in request.model_fields_set:
        if request.due_date in (None, ""):
            item.due_date = None
        else:
            try:
                item.due_date = date.fromisoformat(request.due_date)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid due_date format. Expected YYYY-MM-DD",
                ) from exc
    if "priority" in request.model_fields_set:
        item.priority = request.priority
    if "status" in request.model_fields_set:
        item.status = request.status

    await db.flush()

    return ActionItemResponse(
        id=str(item.id),
        recording_id=str(item.recording_id),
        task=item.task,
        owner=item.owner,
        due_date=item.due_date.isoformat() if item.due_date else None,
        priority=item.priority,
        status=item.status,
        source=item.source,
        created_at=item.created_at.isoformat(),
    )


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_action_item(
    item_id: UUID,
    user: CurrentUser,
    db: Database,
) -> None:
    """Delete an action item."""
    result = await db.execute(
        select(ActionItem)
        .join(Recording)
        .where(ActionItem.id == item_id, Recording.user_id == user.id)
    )
    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action item not found",
        )

    await db.delete(item)
