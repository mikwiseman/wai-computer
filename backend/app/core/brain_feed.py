"""GET /brain/feed — the calm "Cards-That-Think" home feed (P0b).

A keyset-paginated, time-ordered feed of the user's sources (recordings + items +
chats) as two-line cards. The card summary comes from the ALREADY-STORED summary
(``summaries.summary`` / ``item_summaries.summary``) — ZERO new LLM, so opening
the Brain costs nothing. ``is_new`` flags sources newer than the user's
``brain_last_seen_at`` watermark to power the "Since you last looked · N new"
strip (m65 resurfacing, pull side). One UNION query, reusing the same machinery
as unified_search (no new infra).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SUMMARY_CHARS = 280  # two calm lines

_FEED_SQL = text(
    """
    WITH feed AS (
        SELECT 'recording' AS source_kind, r.id::text AS source_id,
               COALESCE(r.title, 'Recording') AS title,
               LEFT(COALESCE(su.summary, ''), :chars) AS summary,
               COALESCE(r.updated_at, r.created_at) AS source_time
        FROM recordings r
        LEFT JOIN summaries su ON su.recording_id = r.id
        WHERE r.user_id = :uid AND r.deleted_at IS NULL
        UNION ALL
        SELECT 'item', i.id::text,
               COALESCE(i.title, i.url, 'Untitled'),
               LEFT(COALESCE(isum.summary, i.body, ''), :chars),
               COALESCE(i.occurred_at, i.created_at)
        FROM items i
        LEFT JOIN item_summaries isum ON isum.item_id = i.id
        WHERE i.user_id = :uid AND i.deleted_at IS NULL
        UNION ALL
        SELECT 'chat', c.id::text,
               COALESCE(c.title, 'Wai thread'),
               '',
               COALESCE(c.last_message_at, c.created_at)
        FROM conversations c
        WHERE c.user_id = :uid AND c.deleted_at IS NULL AND c.archived_at IS NULL
    )
    SELECT source_kind, source_id, title, summary, source_time
    FROM feed
    WHERE CAST(:cursor_time AS timestamptz) IS NULL
       OR source_time < CAST(:cursor_time AS timestamptz)
       OR (source_time = CAST(:cursor_time AS timestamptz) AND source_id < :cursor_id)
    ORDER BY source_time DESC, source_id DESC
    LIMIT :lim
    """
)


@dataclass
class FeedCard:
    id: str  # "<source_kind>:<source_id>"
    source_kind: str
    source_id: str
    title: str
    summary: str
    source_time: str | None
    is_new: bool


@dataclass
class BrainFeed:
    cards: list[FeedCard]
    next_cursor: str | None  # pass back as ?cursor= for the next page


async def get_brain_feed(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = 24,
    cursor: str | None = None,
    last_seen: datetime | None = None,
) -> BrainFeed:
    """Recency-ordered feed of source cards. ``cursor`` is the ISO ``source_time``
    of the last card from the previous page (keyset pagination)."""
    limit = max(1, min(limit, 100))
    # Keyset cursor "(<iso source_time>|<source_id>)" — composite so rows sharing
    # a timestamp (e.g. a batch imported in one transaction, where Postgres now()
    # is identical) paginate correctly instead of being skipped.
    cursor_dt: datetime | None = None
    cursor_id = ""
    if cursor:
        raw_time, _, cursor_id = cursor.rpartition("|")
        if not raw_time:  # no separator -> treat the whole value as the timestamp
            raw_time, cursor_id = cursor, ""
        cursor_dt = datetime.fromisoformat(raw_time)  # asyncpg needs a datetime, not a str
    rows = (
        await db.execute(
            _FEED_SQL,
            {
                "uid": str(user_id),
                "chars": _SUMMARY_CHARS,
                "cursor_time": cursor_dt,
                "cursor_id": cursor_id,
                "lim": limit + 1,
            },
        )
    ).fetchall()

    has_more = len(rows) > limit
    rows = rows[:limit]

    cards: list[FeedCard] = []
    for r in rows:
        st = r.source_time
        is_new = bool(last_seen and st and st > last_seen)
        cards.append(
            FeedCard(
                id=f"{r.source_kind}:{r.source_id}",
                source_kind=r.source_kind,
                source_id=r.source_id,
                title=r.title,
                summary=(r.summary or "").strip(),
                source_time=st.isoformat() if st else None,
                is_new=is_new,
            )
        )

    last = cards[-1] if cards else None
    next_cursor = (
        f"{last.source_time}|{last.source_id}"
        if (has_more and last and last.source_time)
        else None
    )
    return BrainFeed(cards=cards, next_cursor=next_cursor)


async def count_new_since_last_seen(
    db: AsyncSession, user_id: uuid.UUID, *, last_seen: datetime | None
) -> int:
    """How many sources are newer than the watermark (capped scan for the strip)."""
    if last_seen is None:
        return 0
    feed = await get_brain_feed(db, user_id, limit=100, last_seen=last_seen)
    return sum(1 for c in feed.cards if c.is_new)
