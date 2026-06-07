"""Ask your Brain — a single-shot, cited answer with honest gaps (gbrain `think`).

One question over the whole brain returns ONE synthesized answer where every
substantive claim is cited to the exact recording, material, or Wai chat, plus an explicit list
of what the brain *doesn't* know and a freshness read ("nothing added in 6
weeks"). The honesty is the point: it never answers from outside the user's own
Brain sources, and it says so when the material isn't there.

Retrieval reuses unified recordings + items search and explicit scoped chat
evidence; synthesis is one cheap strict-JSON Cerebras call. Citations the model
returns are validated against the retrieved set — an out-of-range cite is
dropped, never rendered.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.brain_maps import _allowed_scoped_sources, _scoped_source_hits
from app.core.cerebras_chat import (
    chat_completion_parsed,
    get_cerebras_client,
    strict_json_response_format,
)
from app.core.observability import safe_text_digest
from app.core.unified_search import UnifiedHit, unified_search

logger = logging.getLogger(__name__)

ASK_RETRIEVAL_LIMIT = 18
ASK_SEARCH_POOL_MULTIPLIER = 3
ASK_MAX_EXCERPTS_PER_SOURCE = 2
_EXCERPT_CHAR_CAP = 600
_STALE_WEEKS = 3


ASK_SYSTEM_PROMPT = (
    "You answer the user's question using ONLY the numbered excerpts from their "
    "own recordings, saved materials, and Wai chats below. You are their sharp, trusted "
    "colleague who remembers their Brain.\n\n"
    "Rules:\n"
    "- Cite every substantive claim with the excerpt number(s) it came from, like "
    "[2] or [1][4], inline. Also return those numbers in `citations`.\n"
    "- Use ONLY the excerpts. Never add outside knowledge, and never guess. If the "
    "excerpts don't answer the question, say so plainly in `answer` and put what's "
    "missing in `gaps`.\n"
    "- If excerpts conflict, surface both — don't silently pick one.\n"
    "- `gaps`: the genuine unknowns — what the sources don't cover that the "
    "question needs. Empty list if the answer is fully supported.\n"
    "- Be concise and concrete. Do NOT give commands or say 'you should'. No "
    "preamble like 'Based on the excerpts'."
)


class _AskResult(BaseModel):
    answer: str
    citations: list[int]
    gaps: list[str]


@dataclass
class AnswerCitation:
    id: str
    source_kind: str
    source_id: str
    title: str | None
    start_ms: int | None


@dataclass
class AnswerFreshness:
    newest_source_at: datetime | None
    weeks_since: int | None
    stale: bool


@dataclass
class BrainAnswer:
    answer: str
    citations: list[AnswerCitation] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    freshness: AnswerFreshness = field(
        default_factory=lambda: AnswerFreshness(None, None, False)
    )


async def _freshness_for(
    hits: list[UnifiedHit],
    *,
    now: datetime,
) -> AnswerFreshness:
    """Newest of the relevant unified hits → 'nothing added in N weeks' read."""
    dates: list[datetime] = []
    for hit in hits:
        raw = hit.created_at
        if not raw:
            continue
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        dates.append(parsed)
    if not dates:
        return AnswerFreshness(None, None, False)
    newest = max(dates)
    weeks = max(0, int((now - newest).days // 7))
    return AnswerFreshness(newest_source_at=newest, weeks_since=weeks, stale=weeks >= _STALE_WEEKS)


def _excerpt_for_hit(index: int, hit: UnifiedHit | Any) -> str:
    fallback_title = {
        "recording": "Recording",
        "item": "Material",
        "chat": "Wai chat",
    }.get(hit.source_kind, "Source")
    title = hit.title or fallback_title
    source_label = {
        "recording": "Recording",
        "item": "Material",
        "chat": "Wai chat",
    }.get(hit.source_kind, "Source")
    return f"[{index}] ({source_label}: {title}) {(hit.snippet or '')[:_EXCERPT_CHAR_CAP]}"


def _diverse_hits(hits: list[UnifiedHit | Any], limit: int) -> list[UnifiedHit | Any]:
    """Pick a diverse excerpt set: cap per source AND per source-kind so a noisy
    mailbox (many ``item`` hits) can't crowd out the meeting/chat where the
    decision was actually made. A second pass fills leftover slots without the
    kind cap, so excerpts are never wasted when only one kind exists.
    """
    selected: list[UnifiedHit | Any] = []
    selected_chunk_ids: set[str] = set()
    per_source_counts: dict[tuple[str, str], int] = {}
    per_kind_counts: dict[str, int] = {}
    max_per_source = max(1, ASK_MAX_EXCERPTS_PER_SOURCE)
    kind_cap = max(1, (limit * 3 + 4) // 5)  # ~60% — reserve slots for other kinds

    def _fill(enforce_kind_cap: bool) -> None:
        for quota in range(1, max_per_source + 1):
            for hit in hits:
                if len(selected) >= limit:
                    return
                if hit.chunk_id in selected_chunk_ids:
                    continue
                source_key = (hit.source_kind, hit.parent_id)
                if per_source_counts.get(source_key, 0) >= quota:
                    continue
                if enforce_kind_cap and per_kind_counts.get(hit.source_kind, 0) >= kind_cap:
                    continue
                selected.append(hit)
                selected_chunk_ids.add(hit.chunk_id)
                per_source_counts[source_key] = per_source_counts.get(source_key, 0) + 1
                per_kind_counts[hit.source_kind] = per_kind_counts.get(hit.source_kind, 0) + 1

    _fill(enforce_kind_cap=True)
    if len(selected) < limit:
        _fill(enforce_kind_cap=False)
    return selected


async def _search_hits(
    db: AsyncSession,
    user_id: uuid.UUID,
    question: str,
    *,
    source_scope: dict[str, Any] | None,
    limit: int,
) -> list[UnifiedHit | Any]:
    search_pool_limit = max(limit, limit * ASK_SEARCH_POOL_MULTIPLIER)
    if source_scope is None:
        raw_hits = await unified_search(db, user_id, question, limit=search_pool_limit)
        return _diverse_hits(raw_hits, limit)

    allowed = _allowed_scoped_sources(source_scope)
    if not allowed:
        return []

    raw_hits = await unified_search(db, user_id, question, limit=search_pool_limit)
    scoped_hits = await _scoped_source_hits(db, user_id, allowed)
    filtered = [hit for hit in raw_hits if (hit.source_kind, hit.parent_id) in allowed]
    seen_sources = {(hit.source_kind, hit.parent_id) for hit in filtered}
    filtered.extend(
        hit for hit in scoped_hits if (hit.source_kind, hit.parent_id) not in seen_sources
    )
    return _diverse_hits(filtered, limit)


async def ask_brain(
    db: AsyncSession,
    user_id: uuid.UUID,
    question: str,
    *,
    cerebras_client: Any | None = None,
    limit: int = ASK_RETRIEVAL_LIMIT,
    now: datetime | None = None,
    source_scope: dict[str, Any] | None = None,
) -> BrainAnswer:
    """Answer ``question`` from the user's recordings, items, and chats, cited, with honest gaps."""
    question = (question or "").strip()
    now = now or datetime.now(timezone.utc)
    if not question:
        return BrainAnswer(answer="", gaps=["Ask a question to search your Brain."])

    hits = await _search_hits(
        db,
        user_id,
        question,
        source_scope=source_scope,
        limit=limit,
    )
    if not hits:
        freshness = await _freshness_for([], now=now)
        return BrainAnswer(
            answer="",
            gaps=["Your Brain doesn't contain anything about this yet."],
            freshness=freshness,
        )

    number_to_citation: dict[int, AnswerCitation] = {}
    excerpts: list[str] = []
    for i, hit in enumerate(hits, start=1):
        number_to_citation[i] = AnswerCitation(
            id=hit.chunk_id,
            source_kind=hit.source_kind,
            source_id=hit.parent_id,
            title=hit.title,
            start_ms=getattr(hit, "start_ms", None),
        )
        excerpts.append(_excerpt_for_hit(i, hit))

    settings = get_settings()
    client = cerebras_client if cerebras_client is not None else get_cerebras_client()
    user_content = f"Question: {question}\n\nExcerpts:\n" + "\n".join(excerpts)
    response = await client.chat.completions.create(
        model=settings.cerebras_llm_model,
        messages=[
            {"role": "system", "content": ASK_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format=strict_json_response_format(_AskResult, name="brain_answer"),
        temperature=0.2,
    )
    result = chat_completion_parsed(response, _AskResult, operation="brain_ask")

    citations: list[AnswerCitation] = []
    seen: set[int] = set()
    for n in result.citations:
        if n in number_to_citation and n not in seen:
            seen.add(n)
            citations.append(number_to_citation[n])

    freshness = await _freshness_for(hits, now=now)
    logger.info(
        "brain_ask q=%s sources=%d citations=%d gaps=%d",
        safe_text_digest(question, label="query"),
        len(hits),
        len(citations),
        len(result.gaps),
    )
    return BrainAnswer(
        answer=result.answer.strip(),
        citations=citations,
        gaps=[g.strip() for g in result.gaps if g.strip()],
        freshness=freshness,
    )
