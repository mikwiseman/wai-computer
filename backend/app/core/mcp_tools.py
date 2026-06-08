"""Read-only WaiComputer data access exposed through MCP tools."""

from __future__ import annotations

import base64
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.recording import ActionItem, Folder, Recording, Segment, Summary


def _as_uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _recording_url(recording_id: UUID) -> str:
    settings = get_settings()
    return f"{settings.frontend_url.rstrip('/')}/dashboard?recording={recording_id}"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _encode_cursor(created_at: datetime, item_id: UUID) -> str:
    raw = f"{created_at.isoformat()}|{item_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    padded = cursor + "=" * (-len(cursor) % 4)
    raw = base64.urlsafe_b64decode(padded.encode()).decode()
    iso, _, id_str = raw.rpartition("|")
    if not iso or not id_str:
        raise ValueError("invalid cursor")
    return datetime.fromisoformat(iso), UUID(id_str)


def _validate_limit(limit: int, maximum: int) -> None:
    if limit < 1 or limit > maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")


def _coerce_folder_ids(folder_ids: list[str] | None) -> list[UUID] | None:
    if folder_ids is None:
        return None
    return [_as_uuid(value) for value in folder_ids]


async def _user_folder_ids(db: AsyncSession, user_uuid: UUID, requested: list[UUID]) -> list[UUID]:
    """Return the subset of `requested` folder IDs that the user actually owns.

    Pruning unowned IDs here means cross-user data leaks turn into empty
    results rather than authorization errors that fan out of the tool layer."""
    if not requested:
        return []
    result = await db.execute(
        select(Folder.id).where(
            Folder.user_id == user_uuid,
            Folder.id.in_(requested),
        )
    )
    return [row[0] for row in result.all()]


def _first_match_snippet(text: str, query: str, max_chars: int = 500) -> str:
    clean = " ".join(text.split())
    if len(clean) <= max_chars:
        return clean

    index = clean.lower().find(query.lower().strip())
    if index < 0:
        return clean[: max_chars - 1].rstrip() + "..."

    start = max(0, index - max_chars // 3)
    end = min(len(clean), start + max_chars)
    snippet = clean[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(clean):
        snippet = snippet.rstrip() + "..."
    return snippet


def _recording_search_text(recording: Recording) -> str:
    chunks: list[str] = []
    if recording.title:
        chunks.append(recording.title)
    if recording.summary and recording.summary.summary:
        chunks.append(recording.summary.summary)
    chunks.extend(
        segment.content for segment in sorted(recording.segments, key=lambda s: s.start_ms or 0)
    )
    return "\n".join(chunk for chunk in chunks if chunk)


def _summary_metadata(summary: Summary | None) -> dict:
    if summary is None:
        return {}
    return {
        "topics": summary.topics or [],
        "people_mentioned": summary.people_mentioned or [],
        "sentiment": summary.sentiment,
    }


async def search_recordings_for_mcp(
    db: AsyncSession,
    user_id: str | UUID,
    query: str,
    *,
    limit: int = 10,
    folder_ids: list[str] | None = None,
) -> dict:
    """Search a user's non-deleted recordings for MCP search/fetch clients.

    `folder_ids=None` returns matches from every folder (and unfiled recordings).
    Passing a list restricts the search to those folders; an empty list returns
    no results. Cross-user IDs are pruned before the query so a malicious
    client cannot probe foreign folders."""
    settings = get_settings()
    if not query or not query.strip():
        return {"results": []}
    _validate_limit(limit, settings.mcp_max_search_results)

    user_uuid = _as_uuid(user_id)
    requested_folders = _coerce_folder_ids(folder_ids)
    if requested_folders is not None:
        if not requested_folders:
            return {"results": []}
        owned = await _user_folder_ids(db, user_uuid, requested_folders)
        if not owned:
            return {"results": []}
    else:
        owned = None

    pattern = f"%{query.strip()}%"
    stmt = (
        select(Recording)
        .outerjoin(Segment)
        .outerjoin(Summary)
        .where(
            Recording.user_id == user_uuid,
            Recording.deleted_at.is_(None),
            or_(
                Recording.title.ilike(pattern),
                Segment.content.ilike(pattern),
                Summary.summary.ilike(pattern),
            ),
        )
        .options(selectinload(Recording.segments), selectinload(Recording.summary))
        .order_by(Recording.created_at.desc())
        .limit(limit)
    )
    if owned is not None:
        stmt = stmt.where(Recording.folder_id.in_(owned))

    result = await db.execute(stmt)
    recordings = list(result.scalars().unique().all())

    return {
        "results": [
            {
                "id": str(recording.id),
                "title": recording.title or "Untitled Recording",
                "text": _first_match_snippet(_recording_search_text(recording), query),
                "url": _recording_url(recording.id),
                "metadata": {
                    # Always present so a folder-scoped `search` hit carries the
                    # same source_kind discriminator as the unified path.
                    "source_kind": "recording",
                    "type": recording.type,
                    "created_at": _iso(recording.created_at),
                    "duration_seconds": recording.duration_seconds,
                    "folder_id": str(recording.folder_id) if recording.folder_id else None,
                    **_summary_metadata(recording.summary),
                },
            }
            for recording in recordings
        ]
    }


async def list_folders_for_mcp(db: AsyncSession, user_id: str | UUID) -> dict:
    """Return the user's folders with non-deleted recording counts.

    Used by agents to discover what folders exist before calling
    `list_recordings` or `search` with a folder filter."""
    user_uuid = _as_uuid(user_id)
    count_subq = (
        select(
            Recording.folder_id.label("folder_id"),
            func.count(Recording.id).label("recording_count"),
        )
        .where(Recording.user_id == user_uuid, Recording.deleted_at.is_(None))
        .group_by(Recording.folder_id)
        .subquery()
    )
    stmt = (
        select(Folder, func.coalesce(count_subq.c.recording_count, 0))
        .outerjoin(count_subq, count_subq.c.folder_id == Folder.id)
        .where(Folder.user_id == user_uuid)
        .order_by(Folder.name.asc(), Folder.created_at.asc())
    )
    result = await db.execute(stmt)
    folders = [
        {
            "id": str(folder.id),
            "name": folder.name,
            "recording_count": int(count),
        }
        for folder, count in result.all()
    ]
    return {"folders": folders}


async def list_recordings_for_mcp(
    db: AsyncSession,
    user_id: str | UUID,
    *,
    folder_ids: list[str] | None = None,
    recording_type: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    """List the user's non-deleted recordings, newest first, with cursor pagination.

    `folder_ids=None` returns every recording (filed and unfiled). A non-empty
    list narrows the result to those folders. An empty list is treated as
    "no folders" and returns an empty page. `recording_type` narrows the page
    to one domain type such as "meeting"."""
    settings = get_settings()
    _validate_limit(limit, settings.mcp_max_search_results)

    user_uuid = _as_uuid(user_id)
    requested_folders = _coerce_folder_ids(folder_ids)
    if requested_folders is not None:
        if not requested_folders:
            return {"results": [], "next_cursor": None}
        owned = await _user_folder_ids(db, user_uuid, requested_folders)
        if not owned:
            return {"results": [], "next_cursor": None}
    else:
        owned = None

    stmt = (
        select(Recording)
        .where(Recording.user_id == user_uuid, Recording.deleted_at.is_(None))
        .options(selectinload(Recording.summary))
        .order_by(Recording.created_at.desc(), Recording.id.desc())
        .limit(limit + 1)
    )
    if owned is not None:
        stmt = stmt.where(Recording.folder_id.in_(owned))
    if recording_type is not None:
        stmt = stmt.where(Recording.type == recording_type)
    if cursor is not None:
        cursor_created_at, cursor_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Recording.created_at < cursor_created_at,
                and_(
                    Recording.created_at == cursor_created_at,
                    Recording.id < cursor_id,
                ),
            )
        )

    result = await db.execute(stmt)
    recordings = list(result.scalars().unique().all())
    has_more = len(recordings) > limit
    page = recordings[:limit]
    next_cursor = _encode_cursor(page[-1].created_at, page[-1].id) if has_more and page else None

    return {
        "results": [
            {
                "id": str(recording.id),
                "title": recording.title or "Untitled Recording",
                "url": _recording_url(recording.id),
                "metadata": {
                    "type": recording.type,
                    "created_at": _iso(recording.created_at),
                    "duration_seconds": recording.duration_seconds,
                    "folder_id": str(recording.folder_id) if recording.folder_id else None,
                    "language": recording.language,
                    **_summary_metadata(recording.summary),
                },
            }
            for recording in page
        ],
        "next_cursor": next_cursor,
    }


async def list_action_items_for_mcp(
    db: AsyncSession,
    user_id: str | UUID,
    *,
    status: str | None = None,
    folder_ids: list[str] | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    """List action items from the user's non-deleted recordings, newest first.

    `status` filters by ActionItem.status ("pending", "completed", ...).
    `folder_ids` restricts to action items from recordings in those folders;
    an empty list returns an empty page."""
    settings = get_settings()
    _validate_limit(limit, settings.mcp_max_search_results)

    user_uuid = _as_uuid(user_id)
    requested_folders = _coerce_folder_ids(folder_ids)
    if requested_folders is not None:
        if not requested_folders:
            return {"results": [], "next_cursor": None}
        owned = await _user_folder_ids(db, user_uuid, requested_folders)
        if not owned:
            return {"results": [], "next_cursor": None}
    else:
        owned = None

    stmt = (
        select(ActionItem, Recording)
        .join(Recording, ActionItem.recording_id == Recording.id)
        .where(
            Recording.user_id == user_uuid,
            Recording.deleted_at.is_(None),
        )
        .order_by(ActionItem.created_at.desc(), ActionItem.id.desc())
        .limit(limit + 1)
    )
    if status is not None:
        stmt = stmt.where(ActionItem.status == status)
    if owned is not None:
        stmt = stmt.where(Recording.folder_id.in_(owned))
    if cursor is not None:
        cursor_created_at, cursor_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                ActionItem.created_at < cursor_created_at,
                and_(
                    ActionItem.created_at == cursor_created_at,
                    ActionItem.id < cursor_id,
                ),
            )
        )

    result = await db.execute(stmt)
    rows = list(result.all())
    has_more = len(rows) > limit
    page = rows[:limit]
    if has_more and page:
        last_item, _ = page[-1]
        next_cursor: str | None = _encode_cursor(last_item.created_at, last_item.id)
    else:
        next_cursor = None

    return {
        "results": [
            {
                "id": str(item.id),
                "task": item.task,
                "owner": item.owner,
                "due_date": item.due_date.isoformat() if item.due_date else None,
                "priority": item.priority,
                "status": item.status,
                "recording_id": str(recording.id),
                "recording_title": recording.title or "Untitled Recording",
                "url": _recording_url(recording.id),
            }
            for item, recording in page
        ],
        "next_cursor": next_cursor,
    }


def _format_transcript(segments: list[Segment]) -> str:
    lines: list[str] = []
    for segment in sorted(segments, key=lambda s: s.start_ms or 0):
        speaker = segment.speaker or "Unknown"
        lines.append(f"{speaker}: {segment.content}")
    return "\n".join(lines)


def _format_action_items(items: list[ActionItem]) -> str:
    lines: list[str] = []
    for item in items:
        owner = f" ({item.owner})" if item.owner else ""
        due = f" due {item.due_date.isoformat()}" if item.due_date else ""
        lines.append(f"- {item.task}{owner}{due}")
    return "\n".join(lines)


def _truncate_text(text: str) -> tuple[str, bool]:
    settings = get_settings()
    if len(text) <= settings.mcp_max_tool_text_chars:
        return text, False
    return text[: settings.mcp_max_tool_text_chars - 1].rstrip() + "...", True


async def fetch_recording_for_mcp(
    db: AsyncSession,
    user_id: str | UUID,
    recording_id: str | UUID,
) -> dict | None:
    """Fetch one user's recording as a citation-friendly MCP document."""
    result = await db.execute(
        select(Recording)
        .where(
            Recording.id == _as_uuid(recording_id),
            Recording.user_id == _as_uuid(user_id),
            Recording.deleted_at.is_(None),
        )
        .options(
            selectinload(Recording.segments),
            selectinload(Recording.summary),
            selectinload(Recording.action_items),
        )
    )
    recording = result.scalar_one_or_none()
    if recording is None:
        return None

    sections: list[str] = []
    if recording.summary and recording.summary.summary:
        sections.append(f"Summary:\n{recording.summary.summary}")
    if recording.summary and recording.summary.key_points:
        key_points = "\n".join(f"- {point}" for point in recording.summary.key_points)
        sections.append(f"Key points:\n{key_points}")
    if recording.action_items:
        sections.append(f"Action items:\n{_format_action_items(recording.action_items)}")
    if recording.segments:
        sections.append(f"Transcript:\n{_format_transcript(recording.segments)}")

    text, truncated = _truncate_text("\n\n".join(sections))
    return {
        "id": str(recording.id),
        "title": recording.title or "Untitled Recording",
        "text": text,
        "url": _recording_url(recording.id),
        "metadata": {
            "type": recording.type,
            "created_at": _iso(recording.created_at),
            "uploaded_at": _iso(recording.uploaded_at),
            "duration_seconds": recording.duration_seconds,
            "language": recording.language,
            "truncated": truncated,
            **_summary_metadata(recording.summary),
        },
    }
