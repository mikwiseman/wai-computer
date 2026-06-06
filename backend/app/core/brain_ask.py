"""Ask your Brain — a single-shot, cited answer with honest gaps (gbrain `think`).

One question over the whole brain returns ONE synthesized answer where every
substantive claim is cited to the exact recording or item, plus an explicit list
of what the brain *doesn't* know and a freshness read ("nothing added in 6
weeks"). The honesty is the point: it never answers from outside the user's own
Brain sources, and it says so when the material isn't there.

Retrieval reuses the unified recordings + items search; synthesis is one cheap
strict-JSON Cerebras call. Citations the model returns are validated
against the retrieved set — an out-of-range cite is dropped, never rendered.
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
from app.core.cerebras_chat import (
    chat_completion_parsed,
    get_cerebras_client,
    strict_json_response_format,
)
from app.core.observability import safe_text_digest
from app.core.unified_search import UnifiedHit, unified_search

logger = logging.getLogger(__name__)

ASK_RETRIEVAL_LIMIT = 18
_EXCERPT_CHAR_CAP = 600
_STALE_WEEKS = 3


ASK_SYSTEM_PROMPT = (
    "You answer the user's question using ONLY the numbered excerpts from their "
    "own recordings and saved materials, below. You are their sharp, trusted "
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


def _excerpt_for_hit(index: int, hit: UnifiedHit) -> str:
    title = hit.title or ("Recording" if hit.source_kind == "recording" else "Material")
    source_label = "Recording" if hit.source_kind == "recording" else "Material"
    return f"[{index}] ({source_label}: {title}) {(hit.snippet or '')[:_EXCERPT_CHAR_CAP]}"


async def ask_brain(
    db: AsyncSession,
    user_id: uuid.UUID,
    question: str,
    *,
    cerebras_client: Any | None = None,
    limit: int = ASK_RETRIEVAL_LIMIT,
    now: datetime | None = None,
) -> BrainAnswer:
    """Answer ``question`` from the user's recordings and items, cited, with honest gaps."""
    question = (question or "").strip()
    now = now or datetime.now(timezone.utc)
    if not question:
        return BrainAnswer(answer="", gaps=["Ask a question to search your Brain."])

    hits = await unified_search(db, user_id, question, limit=limit)
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
            start_ms=hit.start_ms,
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
