"""Cross-source digest for the Telegram /digest command.

Ported from the wai-rocks /summary digest (its strongest daily-use command):
collect everything captured in the period — recordings AND saved materials —
into one compact prompt block, then one editorial LLM pass clusters it by
theme and ends with actionable recommendations. The reply uses the same
lightweight-markdown conventions as recording summaries (**bold** key phrases,
`backtick` metrics, "- " bullets) so ``telegram_html`` renders it like every
other bot message.

No fallbacks: a missing Cerebras key or a failed completion raises, and the
route surfaces an honest failure to the user.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.cerebras_chat import chat_completion_text, get_cerebras_client
from app.models.item import Item, ItemSummary
from app.models.recording import Recording, RecordingStatus

logger = logging.getLogger(__name__)

DIGEST_MAX_DAYS = 7
DIGEST_SOURCE_CAP = 60
_FIELD_CHAR_CAP = 1500
_DIGEST_MAX_COMPLETION_TOKENS = 8192

_RECORDING_KIND_LABELS = {
    "meeting": "встреча",
    "note": "голосовая заметка",
}


@dataclass(frozen=True)
class DigestSource:
    """One captured thing inside the digest period, already reduced to text."""

    kind: str  # human label: "встреча", "статья", "фото", ...
    title: str
    occurred_at: datetime
    summary: str
    key_points: list[str]


def digest_period_start(days: int, *, now: datetime | None = None) -> datetime:
    """UTC start bound: today counts as day 1, so N days = N-1 days back,
    clamped to the start of that day (mirrors the wai-rocks period bounds)."""
    current = now or datetime.now(timezone.utc)
    return (current - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _clip(text: str | None, cap: int = _FIELD_CHAR_CAP) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= cap:
        return cleaned
    return cleaned[:cap].rstrip() + "…"


def _item_kind_label(kind: str | None) -> str:
    return {
        "article": "статья",
        "video": "видео",
        "youtube": "видео",
        "image": "фото",
        "pdf": "документ",
        "note": "заметка",
        "post": "пост",
    }.get((kind or "").strip(), "материал")


async def collect_digest_sources(
    db: AsyncSession,
    user_id: UUID,
    *,
    days: int,
    now: datetime | None = None,
) -> tuple[list[DigestSource], int]:
    """Everything the user captured in the period, newest last.

    Returns ``(sources, total)`` where ``sources`` is capped at
    ``DIGEST_SOURCE_CAP`` (keeping the newest) and ``total`` is the uncapped
    count so the route can disclose the truncation instead of hiding it.
    """
    since = digest_period_start(days, now=now)

    recordings = (
        (
            await db.execute(
                select(Recording)
                .options(selectinload(Recording.summary))
                .where(
                    Recording.user_id == user_id,
                    Recording.created_at >= since,
                    Recording.status == RecordingStatus.READY.value,
                )
                .order_by(Recording.created_at)
            )
        )
        .scalars()
        .all()
    )
    sources: list[DigestSource] = []
    for recording in recordings:
        summary = recording.summary
        summary_text = _clip(summary.summary if summary else None)
        if not summary_text:
            continue  # a recording with no summary has nothing digestible yet
        key_points = [
            _clip(str(point), 300)
            for point in ((summary.key_points if summary else None) or [])[:8]
        ]
        sources.append(
            DigestSource(
                kind=_RECORDING_KIND_LABELS.get(str(recording.type or ""), "запись"),
                title=_clip(recording.title, 200) or "Без названия",
                occurred_at=recording.created_at,
                summary=summary_text,
                key_points=key_points,
            )
        )

    item_rows = (
        await db.execute(
            select(Item, ItemSummary)
            .outerjoin(ItemSummary, ItemSummary.item_id == Item.id)
            .where(
                Item.user_id == user_id,
                Item.created_at >= since,
                Item.state != "failed",
            )
            .order_by(Item.created_at)
        )
    ).all()
    for item, item_summary in item_rows:
        summary_text = _clip(item_summary.summary if item_summary else None)
        if not summary_text:
            # Raw capture still worth a digest line — use the body head.
            summary_text = _clip(item.body, 400)
        if not summary_text:
            continue
        key_points = [
            _clip(str(point), 300)
            for point in ((item_summary.key_points if item_summary else None) or [])[:8]
        ]
        sources.append(
            DigestSource(
                kind=_item_kind_label(item.kind),
                title=_clip(item.title, 200) or "Без названия",
                occurred_at=item.created_at,
                summary=summary_text,
                key_points=key_points,
            )
        )

    sources.sort(key=lambda source: source.occurred_at)
    total = len(sources)
    return sources[-DIGEST_SOURCE_CAP:], total


def build_digest_prompt_block(sources: list[DigestSource]) -> str:
    """wai-rocks-style compact entries the digest model reads."""
    entries: list[str] = []
    for idx, source in enumerate(sources, start=1):
        lines = [
            f"Item {idx}",
            f"Timestamp: {source.occurred_at.astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC",
            f"Type: {source.kind}",
            f"Title: {source.title}",
            f"Summary: {source.summary}",
        ]
        if source.key_points:
            lines.append("KeyPoints: " + "; ".join(source.key_points))
        entries.append("\n".join(lines))
    return "\n\n".join(entries)


_DIGEST_INSTRUCTIONS = """\
You are an editorial analyst preparing a personal digest of everything the user
captured in their second brain over a period: meetings, voice notes, articles,
videos, photos, documents.

Write the digest:
- Cluster related captures by theme, not by source order; name each theme with a
  short header line ending with a colon.
- Under each header use "- " bullets. Inside each bullet wrap the 1-3 most
  load-bearing words in **bold** and wrap every number, amount, date, deadline,
  and metric in `backticks`.
- Keep proper nouns, numbers, and direct quotes verbatim. Do not invent facts —
  only use what the materials contain.
- Surface cross-links between captures when they exist (a meeting that discusses
  an article, repeated topics).
- End with a header "Рекомендации:" (or "Recommendations:" if writing English)
  and 2-3 actionable bullets grounded in the materials.
- Write in the language most of the materials are in.
- No greeting, no preamble, no meta-commentary. Stay under ~3500 characters by
  tightening bullets, not by dropping whole themes.

"""


async def generate_telegram_digest(
    sources_block: str,
    *,
    days: int,
    total_sources: int,
) -> str:
    """One editorial pass over the period's materials. Raises on any failure."""
    settings = get_settings()
    if not settings.cerebras_api_key:
        raise ValueError("CEREBRAS_API_KEY not configured")
    client = get_cerebras_client()
    user_prompt = (
        f"Time span: last {days} day(s). Materials included: {total_sources}.\n\n"
        f"Materials:\n{sources_block}"
    )
    response = await client.chat.completions.create(
        model=settings.cerebras_llm_model,
        messages=[
            {"role": "system", "content": _DIGEST_INSTRUCTIONS},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=_DIGEST_MAX_COMPLETION_TOKENS,
    )
    text = chat_completion_text(response, operation="Telegram digest")
    return text.strip()


def parse_digest_days(arg: str) -> int | None:
    """``""`` -> 1 (today); ``"3"`` -> 3; junk/non-positive -> None."""
    cleaned = (arg or "").strip()
    if not cleaned:
        return 1
    token = cleaned.split()[0]
    try:
        days = int(token)
    except ValueError:
        return None
    if days < 1:
        return None
    return days
