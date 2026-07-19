"""Universal inbox read model.

Inbox is the capture surface for recordings and saved materials. Wai chats stay
available through Search and companion routes, but they are not Inbox rows.
"""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, exists, func, not_, or_, select

from app.api.deps import CurrentUser, Database
from app.api.routes.items import _derive_status, _item_error
from app.core.item_titles import title_from_body
from app.models.item import Item, ItemSummary
from app.models.recording import Recording, RecordingStatus, Summary

router = APIRouter(prefix="/inbox", tags=["inbox"])

InboxSourceKind = Literal["recording", "item"]
InboxStatus = Literal["ready", "processing", "needs_input", "failed", "archived"]
InboxStatusFilter = Literal["ready", "processing", "needs_attention"]

SOURCE_RANK: dict[str, int] = {"recording": 0, "item": 1}


class InboxDetailRef(BaseModel):
    kind: InboxSourceKind
    id: str


class InboxError(BaseModel):
    code: str
    message: str


class InboxRow(BaseModel):
    id: str
    source_kind: InboxSourceKind
    source_id: str
    detail: InboxDetailRef
    title: str | None
    source_label: str
    sublabel: str | None
    activity_at: datetime
    created_at: datetime
    updated_at: datetime | None
    occurred_at: datetime | None
    status: InboxStatus
    source_status: str | None
    error: InboxError | None
    folder_id: str | None
    duration_seconds: int | None
    language: str | None
    has_summary: bool | None
    is_starred: bool
    is_pinned: bool
    is_archived: bool
    is_trashed: bool


class InboxResponse(BaseModel):
    rows: list[InboxRow]
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True)
class InboxCursor:
    activity_at: datetime
    source_kind: InboxSourceKind
    source_id: str


def _sort_key(row: InboxRow) -> tuple[datetime, int, str]:
    return (row.activity_at, SOURCE_RANK[row.source_kind], row.source_id)


def _decode_cursor(cursor: str | None) -> InboxCursor | None:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
        source_kind = payload["source_kind"]
        if source_kind not in SOURCE_RANK:
            raise ValueError("unknown source kind")
        activity_at = datetime.fromisoformat(payload["activity_at"])
        if activity_at.tzinfo is None:
            raise ValueError("activity_at must include a timezone")
        source_id = str(uuid.UUID(payload["source_id"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid cursor: {exc}",
        ) from exc
    return InboxCursor(
        activity_at=activity_at,
        source_kind=source_kind,
        source_id=source_id,
    )


def _encode_cursor(row: InboxRow) -> str:
    raw = json.dumps(
        {
            "activity_at": row.activity_at.isoformat(),
            "source_kind": row.source_kind,
            "source_id": row.source_id,
        },
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _cursor_clause(activity_expr, source_kind: InboxSourceKind, cursor: InboxCursor):
    source_rank = SOURCE_RANK[source_kind]
    cursor_rank = SOURCE_RANK[cursor.source_kind]
    clauses = [activity_expr < cursor.activity_at]
    if source_rank < cursor_rank:
        clauses.append(activity_expr == cursor.activity_at)
    elif source_rank == cursor_rank:
        clauses.append(
            and_(
                activity_expr == cursor.activity_at,
                uuid_column_for_source(source_kind) < uuid.UUID(cursor.source_id),
            )
        )
    return or_(*clauses)


def uuid_column_for_source(source_kind: InboxSourceKind):
    if source_kind == "recording":
        return Recording.id
    return Item.id


def _recording_status(status_value: str) -> InboxStatus:
    if status_value == RecordingStatus.READY.value:
        return "ready"
    if status_value == RecordingStatus.FAILED.value:
        return "failed"
    return "processing"


def _item_inbox_status(item_status: str) -> InboxStatus:
    if item_status in {"fetching", "summarizing"}:
        return "processing"
    if item_status == "needs_input":
        return "needs_input"
    if item_status == "failed":
        return "failed"
    return "ready"


def _recording_error(recording: Recording) -> InboxError | None:
    if not recording.failure_code and not recording.failure_message:
        return None
    return InboxError(
        code=recording.failure_code or "recording_failed",
        message=recording.failure_message or "",
    )


def _item_processing_error_clause():
    processing_error_present = Item.metadata_.op("?")("processing_error")
    return or_(Item.metadata_.is_(None), not_(processing_error_present))


def _source_allowed(
    wanted: InboxSourceKind | None,
    source_kind: InboxSourceKind,
) -> bool:
    return wanted is None or wanted == source_kind


async def _recording_rows(
    db: Database,
    user_id: uuid.UUID,
    limit: int,
    cursor: InboxCursor | None,
    status_filter: InboxStatusFilter | None,
    folder_id: uuid.UUID | None,
) -> list[InboxRow]:
    activity_expr = Recording.created_at
    summary_exists = exists(select(Summary.id).where(Summary.recording_id == Recording.id))
    stmt = select(Recording, summary_exists.label("has_summary")).where(
        Recording.user_id == user_id,
        Recording.deleted_at.is_(None),
    )
    if folder_id is not None:
        stmt = stmt.where(Recording.folder_id == folder_id)
    if status_filter == "ready":
        stmt = stmt.where(Recording.status == RecordingStatus.READY.value)
    elif status_filter == "processing":
        stmt = stmt.where(
            Recording.status.in_(
                [
                    RecordingStatus.PENDING_UPLOAD.value,
                    RecordingStatus.UPLOADING.value,
                    RecordingStatus.PROCESSING.value,
                ]
            )
        )
    elif status_filter == "needs_attention":
        stmt = stmt.where(Recording.status == RecordingStatus.FAILED.value)
    if cursor is not None:
        stmt = stmt.where(_cursor_clause(activity_expr, "recording", cursor))

    result = await db.execute(
        stmt.order_by(activity_expr.desc(), Recording.id.desc()).limit(limit + 1)
    )
    rows: list[InboxRow] = []
    for recording, has_summary in result.all():
        row_status = _recording_status(recording.status)
        rows.append(
            InboxRow(
                id=f"recording:{recording.id}",
                source_kind="recording",
                source_id=str(recording.id),
                detail=InboxDetailRef(kind="recording", id=str(recording.id)),
                title=recording.title,
                source_label="Recording",
                sublabel=recording.type,
                activity_at=recording.created_at,
                created_at=recording.created_at,
                updated_at=recording.updated_at,
                occurred_at=recording.uploaded_at,
                status=row_status,
                source_status=recording.status,
                error=_recording_error(recording),
                folder_id=str(recording.folder_id) if recording.folder_id else None,
                duration_seconds=recording.duration_seconds,
                language=recording.language,
                has_summary=bool(has_summary),
                is_starred=recording.starred_at is not None,
                is_pinned=False,
                is_archived=False,
                is_trashed=False,
            )
        )
    return rows


async def _item_rows(
    db: Database,
    user_id: uuid.UUID,
    limit: int,
    cursor: InboxCursor | None,
    status_filter: InboxStatusFilter | None,
    folder_id: uuid.UUID | None,
) -> list[InboxRow]:
    activity_expr = func.coalesce(Item.occurred_at, Item.created_at)
    summary_exists = exists(select(ItemSummary.id).where(ItemSummary.item_id == Item.id))
    stmt = select(
        Item,
        activity_expr.label("activity_at"),
        summary_exists.label("has_summary"),
    ).where(
        Item.user_id == user_id,
        Item.deleted_at.is_(None),
    )
    if folder_id is not None:
        stmt = stmt.where(Item.folder_id == folder_id)
    if status_filter == "ready":
        stmt = stmt.where(summary_exists)
    elif status_filter == "processing":
        stmt = stmt.where(
            not_(summary_exists),
            Item.state.notin_(["needs_input", "failed"]),
            _item_processing_error_clause(),
        )
    elif status_filter == "needs_attention":
        stmt = stmt.where(
            or_(
                Item.state.in_(["needs_input", "failed"]),
                Item.metadata_.op("?")("processing_error"),
            )
        )
    if cursor is not None:
        stmt = stmt.where(_cursor_clause(activity_expr, "item", cursor))

    result = await db.execute(
        stmt.order_by(activity_expr.desc(), Item.id.desc()).limit(limit + 1)
    )
    rows: list[InboxRow] = []
    for item, activity_at, has_summary in result.all():
        source_status = _derive_status(item, bool(has_summary))
        item_error = _item_error(item)
        rows.append(
            InboxRow(
                id=f"item:{item.id}",
                source_kind="item",
                source_id=str(item.id),
                detail=InboxDetailRef(kind="item", id=str(item.id)),
                title=item.title or title_from_body(item.body),
                source_label="Material",
                sublabel=item.kind,
                activity_at=activity_at,
                created_at=item.created_at,
                updated_at=item.updated_at,
                occurred_at=item.occurred_at,
                status=_item_inbox_status(source_status),
                source_status=source_status,
                error=(
                    InboxError(code=item_error.code, message=item_error.message)
                    if item_error
                    else None
                ),
                folder_id=str(item.folder_id) if item.folder_id else None,
                duration_seconds=None,
                language=None,
                has_summary=bool(has_summary),
                is_starred=False,
                is_pinned=False,
                is_archived=False,
                is_trashed=False,
            )
        )
    return rows


@router.get("", response_model=InboxResponse)
async def list_inbox(
    user: CurrentUser,
    db: Database,
    source_kind: InboxSourceKind | None = None,
    status: InboxStatusFilter | None = None,
    folder_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None),
) -> InboxResponse:
    decoded_cursor = _decode_cursor(cursor)
    rows: list[InboxRow] = []
    if _source_allowed(source_kind, "recording"):
        rows.extend(
            await _recording_rows(
                db,
                user.id,
                limit,
                decoded_cursor,
                status,
                folder_id,
            )
        )
    if _source_allowed(source_kind, "item"):
        rows.extend(
            await _item_rows(
                db,
                user.id,
                limit,
                decoded_cursor,
                status,
                folder_id,
            )
        )
    rows.sort(key=_sort_key, reverse=True)
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    return InboxResponse(
        rows=page_rows,
        has_more=has_more,
        next_cursor=_encode_cursor(page_rows[-1]) if has_more and page_rows else None,
    )
