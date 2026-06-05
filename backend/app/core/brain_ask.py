"""Ask your Brain — a single-shot, cited answer with honest gaps (gbrain `think`).

One question over the whole brain returns ONE synthesized answer where every
substantive claim is cited to the exact recording, plus an explicit list of what
the brain *doesn't* know and a freshness read ("nothing added in 6 weeks"). The
honesty is the point: it never answers from outside the user's own recordings,
and it says so when the material isn't there.

Retrieval reuses the Companion's hybrid search (``retrieve_context``); synthesis
is one cheap strict-JSON Cerebras call. Citations the model returns are validated
against the retrieved set — an out-of-range cite is dropped, never rendered.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.cerebras_chat import (
    chat_completion_parsed,
    get_cerebras_client,
    strict_json_response_format,
)
from app.core.observability import safe_text_digest
from app.core.qa import retrieve_context
from app.models.recording import Recording

logger = logging.getLogger(__name__)

ASK_RETRIEVAL_LIMIT = 18
_EXCERPT_CHAR_CAP = 600
_STALE_WEEKS = 3


ASK_SYSTEM_PROMPT = (
    "You answer the user's question using ONLY the numbered excerpts from their "
    "own recordings, below. You are their sharp, trusted colleague who remembers "
    "everything they recorded.\n\n"
    "Rules:\n"
    "- Cite every substantive claim with the excerpt number(s) it came from, like "
    "[2] or [1][4], inline. Also return those numbers in `citations`.\n"
    "- Use ONLY the excerpts. Never add outside knowledge, and never guess. If the "
    "excerpts don't answer the question, say so plainly in `answer` and put what's "
    "missing in `gaps`.\n"
    "- If excerpts conflict, surface both — don't silently pick one.\n"
    "- `gaps`: the genuine unknowns — what the recordings don't cover that the "
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
    db: AsyncSession,
    user_id: uuid.UUID,
    recording_ids: set[uuid.UUID],
    *,
    now: datetime,
) -> AnswerFreshness:
    """Newest of the relevant recordings → 'nothing added in N weeks' read."""
    if not recording_ids:
        return AnswerFreshness(None, None, False)
    rows = (
        await db.execute(
            select(Recording.uploaded_at, Recording.created_at).where(
                Recording.id.in_(recording_ids),
                Recording.user_id == user_id,
                Recording.deleted_at.is_(None),
            )
        )
    ).all()
    dates = [uploaded or created for uploaded, created in rows if (uploaded or created)]
    if not dates:
        return AnswerFreshness(None, None, False)
    newest = max(dates)
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=timezone.utc)
    weeks = max(0, int((now - newest).days // 7))
    return AnswerFreshness(newest_source_at=newest, weeks_since=weeks, stale=weeks >= _STALE_WEEKS)


async def ask_brain(
    db: AsyncSession,
    user_id: uuid.UUID,
    question: str,
    *,
    cerebras_client: Any | None = None,
    limit: int = ASK_RETRIEVAL_LIMIT,
    now: datetime | None = None,
) -> BrainAnswer:
    """Answer ``question`` from the user's recordings, cited, with honest gaps."""
    question = (question or "").strip()
    now = now or datetime.now(timezone.utc)
    if not question:
        return BrainAnswer(answer="", gaps=["Ask a question to search your Brain."])

    rows = await retrieve_context(db, user_id, question, limit=limit)
    if not rows:
        freshness = await _freshness_for(db, user_id, set(), now=now)
        return BrainAnswer(
            answer="",
            gaps=["Your recordings don't contain anything about this yet."],
            freshness=freshness,
        )

    number_to_citation: dict[int, AnswerCitation] = {}
    excerpts: list[str] = []
    recording_ids: set[uuid.UUID] = set()
    for i, row in enumerate(rows, start=1):
        recording_ids.add(row.recording_id)
        number_to_citation[i] = AnswerCitation(
            id=str(row.id),
            source_kind="recording",
            source_id=str(row.recording_id),
            title=row.recording_title,
            start_ms=row.start_ms,
        )
        speaker = f"{row.speaker}: " if row.speaker else ""
        title = row.recording_title or "Recording"
        excerpts.append(f"[{i}] ({title}) {speaker}{(row.content or '')[:_EXCERPT_CHAR_CAP]}")

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

    freshness = await _freshness_for(db, user_id, recording_ids, now=now)
    logger.info(
        "brain_ask q=%s segments=%d citations=%d gaps=%d",
        safe_text_digest(question, label="query"),
        len(rows),
        len(citations),
        len(result.gaps),
    )
    return BrainAnswer(
        answer=result.answer.strip(),
        citations=citations,
        gaps=[g.strip() for g in result.gaps if g.strip()],
        freshness=freshness,
    )
