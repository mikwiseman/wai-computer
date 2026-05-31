"""Generate + persist the AI summary and key-moments table for an Item.

This is the item analogue of ``summary_generation.apply_summary_result`` for
recordings, but it writes to the single ``item_summaries`` JSONB row instead of
the recordings-only summaries/action_items/highlights tables. It produces both:

- the structured summary (reusing ``summarize_content``), and
- the hero **key-moments table** (reusing ``extract_key_moments`` + word-level
  timestamp resolution when the item has time-coded segments in metadata).

The LLM functions are injectable so unit tests don't call OpenAI.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.summarizer import (
    KeyMoment,
    SummaryResult,
    extract_key_moments,
    resolve_key_moment_timestamps,
    summarize_content,
)
from app.models.item import Item, ItemSummary

logger = logging.getLogger(__name__)

Summarizer = Callable[..., Awaitable[SummaryResult]]
MomentExtractor = Callable[..., Awaitable[list[KeyMoment]]]


async def generate_item_summary(
    db: AsyncSession,
    item: Item,
    *,
    language: str = "auto",
    style: str = "medium",
    instructions: str | None = None,
    summarizer: Summarizer | None = None,
    moment_extractor: MomentExtractor | None = None,
) -> ItemSummary:
    """Summarize an item's body and build its key-moments table.

    Upserts the single ``item_summaries`` row and flips the item kind-aware
    fields. Returns the persisted ``ItemSummary``. Raises (no silent fallback)
    if the item has no text to summarize.
    """
    text = (item.body or "").strip()
    if not text:
        raise ValueError("item has no body to summarize")

    summarize_fn = summarizer or summarize_content
    moments_fn = moment_extractor or extract_key_moments

    summary_result = await summarize_fn(
        text,
        content_kind=item.kind,
        language=language,
        style=style,
        instructions=instructions,
    )

    moments = await moments_fn(text, language=language)
    # If the item carries time-coded segments (e.g. a transcribed video), map
    # moments to millisecond ranges so the UI can deep-link into playback.
    segments = _segments_from_metadata(item)
    if segments:
        moments = resolve_key_moment_timestamps(moments, segments)

    existing = await db.execute(
        select(ItemSummary).where(ItemSummary.item_id == item.id)
    )
    summary = existing.scalar_one_or_none()
    if summary is None:
        summary = ItemSummary(item_id=item.id)
        db.add(summary)

    summary.summary = summary_result.summary
    summary.key_points = summary_result.key_points
    summary.decisions = summary_result.decisions
    summary.action_items = summary_result.action_items
    summary.topics = summary_result.topics
    summary.people_mentioned = summary_result.people_mentioned
    summary.highlights = summary_result.highlights
    summary.sentiment = summary_result.sentiment
    summary.key_moments = [asdict(m) for m in moments]

    # Fill in a title if the item didn't have one yet.
    if not (item.title or "").strip() and summary_result.title:
        item.title = summary_result.title[:500]

    await db.flush()
    logger.info(
        "item_summary generated item=%s key_points=%s moments=%s",
        item.id,
        len(summary_result.key_points),
        len(moments),
    )
    return summary


def _segments_from_metadata(item: Item) -> list[dict[str, Any]]:
    """Pull time-coded segments out of item.metadata, if a fetcher stored them.

    Video/podcast fetchers may store ``metadata["segments"] = [{content,
    start_ms, end_ms}, ...]``. Text items have none.
    """
    meta = item.metadata_ or {}
    segments = meta.get("segments")
    if isinstance(segments, list) and all(isinstance(s, dict) for s in segments):
        return segments
    return []
