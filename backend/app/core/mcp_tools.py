"""Read-only WaiSay data access exposed through MCP tools."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.recording import ActionItem, Recording, Segment, Summary


def _as_uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _recording_url(recording_id: UUID) -> str:
    settings = get_settings()
    return f"{settings.frontend_url.rstrip('/')}/dashboard?recording={recording_id}"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


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
) -> dict:
    """Search a user's non-deleted recordings for MCP search/fetch clients."""
    settings = get_settings()
    if not query or not query.strip():
        return {"results": []}
    if limit < 1 or limit > settings.mcp_max_search_results:
        raise ValueError(f"limit must be between 1 and {settings.mcp_max_search_results}")

    user_uuid = _as_uuid(user_id)
    pattern = f"%{query.strip()}%"
    result = await db.execute(
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
    recordings = list(result.scalars().unique().all())

    return {
        "results": [
            {
                "id": str(recording.id),
                "title": recording.title or "Untitled Recording",
                "text": _first_match_snippet(_recording_search_text(recording), query),
                "url": _recording_url(recording.id),
                "metadata": {
                    "type": recording.type,
                    "created_at": _iso(recording.created_at),
                    "duration_seconds": recording.duration_seconds,
                    **_summary_metadata(recording.summary),
                },
            }
            for recording in recordings
        ]
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
