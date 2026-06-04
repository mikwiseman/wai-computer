"""Shared user reminders API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Database
from app.models.reminder import UserReminder

router = APIRouter(prefix="/reminders", tags=["reminders"])

REMINDER_TEXT_LIMIT = 1200
REMINDER_STATUSES = {"pending", "sent", "failed", "cancelled"}


class ReminderCreateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=REMINDER_TEXT_LIMIT)
    due_at: datetime
    source: Literal["api", "web", "mac"] = "api"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReminderResponse(BaseModel):
    id: str
    text: str
    due_at: datetime
    status: str
    source: str
    source_ref: str | None
    sent_at: datetime | None
    failed_at: datetime | None
    error: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ReminderListResponse(BaseModel):
    reminders: list[ReminderResponse]


def _normalize_due_at(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Reminder due_at must include timezone.",
        )
    due_at = value.astimezone(timezone.utc)
    if due_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Reminder due_at must be in the future.",
        )
    return due_at


def _normalize_text(value: str) -> str:
    text = value.strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Reminder text must not be empty.",
        )
    return text


def _response(reminder: UserReminder) -> ReminderResponse:
    return ReminderResponse(
        id=str(reminder.id),
        text=reminder.text,
        due_at=reminder.due_at,
        status=reminder.status,
        source=reminder.source,
        source_ref=reminder.source_ref,
        sent_at=reminder.sent_at,
        failed_at=reminder.failed_at,
        error=reminder.error,
        metadata=reminder.metadata_ or {},
        created_at=reminder.created_at,
        updated_at=reminder.updated_at,
    )


@router.get("", response_model=ReminderListResponse)
async def list_reminders(
    user: CurrentUser,
    db: Database,
    status_filter: str | None = Query(default="pending", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> ReminderListResponse:
    effective_status = None if status_filter in (None, "all") else status_filter
    if effective_status is not None and effective_status not in REMINDER_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported reminder status.",
        )
    query = (
        select(UserReminder)
        .where(UserReminder.user_id == user.id)
        .order_by(UserReminder.due_at.asc(), UserReminder.created_at.asc())
        .limit(limit)
    )
    if effective_status is not None:
        query = query.where(UserReminder.status == effective_status)
    reminders = (await db.execute(query)).scalars().all()
    return ReminderListResponse(reminders=[_response(reminder) for reminder in reminders])


@router.post("", response_model=ReminderResponse, status_code=status.HTTP_201_CREATED)
async def create_reminder(
    body: ReminderCreateRequest,
    user: CurrentUser,
    db: Database,
) -> ReminderResponse:
    reminder = UserReminder(
        user_id=user.id,
        source=body.source,
        text=_normalize_text(body.text),
        due_at=_normalize_due_at(body.due_at),
        status="pending",
        metadata_=body.metadata,
    )
    db.add(reminder)
    await db.flush()
    await db.refresh(reminder)
    return _response(reminder)


@router.post("/{reminder_id}/cancel", response_model=ReminderResponse)
async def cancel_reminder(
    reminder_id: UUID,
    user: CurrentUser,
    db: Database,
) -> ReminderResponse:
    reminder = (
        await db.execute(
            select(UserReminder).where(
                UserReminder.id == reminder_id,
                UserReminder.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if reminder is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reminder not found.",
        )
    if reminder.status == "pending":
        reminder.status = "cancelled"
        await db.flush()
        await db.refresh(reminder)
    elif reminder.status != "cancelled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Reminder is already {reminder.status}.",
        )
    return _response(reminder)
