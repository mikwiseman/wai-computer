"""LLM synthesis of an entity's living dossier (gbrain "compiled truth").

``build_entity_page`` (in ``brain_graph``) is deterministic: backlinks,
co-occurrence, and action items. This module adds the *compiled truth* on
top — a current-state-of-play overview plus cited facts, a cited timeline,
and the genuine open questions the sources raise — and caches it in
``EntityPageSnapshot`` keyed by a fingerprint of the entity's sources.

Discipline (no fabrication): the model may only cite the numbered sources we
hand it; any fact / event / question whose citations don't resolve to a real
source is dropped. When an entity has no sources we never call the LLM — the
page stays an honest skeleton.

Synthesis runs *inline on cache miss* (``ensure_entity_page``): the first view
of a changed page pays one cheap Cerebras call (~1-2s), every later view is a
fingerprint cache hit. A failed synthesis never fabricates and never 500s the
page — the deterministic backlinks still render, with ``cache_status="error"``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.brain_graph import (
    EntityPage,
    build_entity_page,
    entity_source_fingerprint,
)
from app.core.cerebras_chat import (
    CerebrasResponseError,
    chat_completion_parsed,
    get_cerebras_client,
    strict_json_response_format,
)
from app.models.entity import Entity, EntityMention, EntityPageSnapshot
from app.models.item import Item
from app.models.recording import Recording, Summary

logger = logging.getLogger(__name__)

# Cap the evidence we hand the model — a hot entity can be in hundreds of
# sources; the most recent, summary-bearing ones carry the signal.
MAX_EVIDENCE_SOURCES = 25
_MAX_CONTEXT_CHARS = 600
_MAX_SUMMARY_CHARS = 800


SYNTHESIS_SYSTEM_PROMPT = (
    "You compile a living dossier about ONE entity (a person, project, or "
    "topic) from the user's own recordings and materials. Write the current "
    "state of play, grounded ONLY in the numbered sources provided.\n\n"
    "Rules:\n"
    "- overview: 2-4 plain sentences — the 30-second state of play. Synthesize, "
    "don't list. Present tense for what is true now.\n"
    "- facts: durable, specific facts. Each MUST cite the source numbers it "
    "comes from in `sources` (e.g. [1,3]).\n"
    "- timeline: events worth remembering, newest-relevant first. Put any date "
    "you can infer in `occurred_at` as ISO (YYYY-MM-DD, or YYYY-MM). Each MUST "
    "cite sources.\n"
    "- questions: the genuine open questions / unknowns the sources raise — "
    "what is unresolved or unclear, not rhetorical. Each MUST cite sources.\n"
    "- Never invent names, numbers, dates, or claims not supported by the "
    "sources. If sources conflict, say so in a fact. If there is little to say, "
    "return few items — do not pad.\n"
    "- Be concrete and factual. Do NOT address the user, give advice, or say "
    "'you should'. No marketing tone."
)


class _SynthFact(BaseModel):
    text: str
    sources: list[int]


class _SynthEvent(BaseModel):
    title: str
    description: str
    occurred_at: str  # ISO-ish or "" — tolerant; parsed best-effort downstream
    sources: list[int]


class _SynthQuestion(BaseModel):
    text: str
    sources: list[int]


class _SynthResult(BaseModel):
    overview: str
    facts: list[_SynthFact]
    timeline: list[_SynthEvent]
    questions: list[_SynthQuestion]


def _citation_id(source_kind: str, source_id: uuid.UUID | str) -> str:
    return f"{source_kind}:{source_id}"


def _coerce_occurred_at(raw: str) -> datetime | None:
    """Best-effort parse of a model-supplied date string into a datetime.

    Partial dates ("2026-03", "Q3") that don't parse return None — the human
    phrasing is preserved in the event title/description regardless.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    for candidate, fmt in ((raw[:10], "%Y-%m-%d"), (raw[:7], "%Y-%m"), (raw[:4], "%Y")):
        try:
            return datetime.strptime(candidate, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def _gather_evidence(
    db: AsyncSession, user_id: uuid.UUID, entity_id: uuid.UUID
) -> tuple[list[dict[str, Any]], dict[int, str]]:
    """Build the numbered evidence pack + a {number -> citation_id} map.

    One numbered source per distinct (kind, id) the entity is mentioned in,
    carrying the mention context and — for recordings — the summary, so the
    model has real material to compile from.
    """
    mentions = (
        await db.execute(
            select(
                EntityMention.source_kind,
                EntityMention.source_id,
                EntityMention.context,
                EntityMention.created_at,
            ).where(
                EntityMention.user_id == user_id,
                EntityMention.entity_id == entity_id,
            )
        )
    ).all()
    if not mentions:
        return [], {}

    rec_ids = {sid for kind, sid, _, _ in mentions if kind == "recording"}
    item_ids = {sid for kind, sid, _, _ in mentions if kind == "item"}

    rec_meta: dict[uuid.UUID, tuple[str, str | None, list | None]] = {}
    if rec_ids:
        for rid, title, summary_text, key_points in (
            await db.execute(
                select(
                    Recording.id, Recording.title, Summary.summary, Summary.key_points
                )
                .outerjoin(Summary, Summary.recording_id == Recording.id)
                .where(Recording.id.in_(rec_ids), Recording.deleted_at.is_(None))
            )
        ).all():
            rec_meta[rid] = (title or "Recording", summary_text, key_points)

    item_meta: dict[uuid.UUID, str] = {}
    if item_ids:
        for iid, title, url in (
            await db.execute(
                select(Item.id, Item.title, Item.url).where(
                    Item.id.in_(item_ids), Item.deleted_at.is_(None)
                )
            )
        ).all():
            item_meta[iid] = title or url or "Untitled"

    # Order: recordings with summaries first (richest), then by recency.
    ordered = sorted(
        mentions,
        key=lambda m: (
            0 if (m[0] == "recording" and rec_meta.get(m[1], (None, None, None))[1]) else 1,
            -(m[3].timestamp() if m[3] else 0.0),
        ),
    )

    evidence: list[dict[str, Any]] = []
    number_to_citation: dict[int, str] = {}
    seen: set[tuple[str, uuid.UUID]] = set()
    for kind, sid, context, _created in ordered:
        if (kind, sid) in seen:
            continue
        if kind == "recording" and sid not in rec_meta:
            continue
        if kind == "item" and sid not in item_meta:
            continue
        seen.add((kind, sid))
        number = len(evidence) + 1
        if kind == "recording":
            title, summary_text, key_points = rec_meta[sid]
            block = {
                "n": number,
                "kind": kind,
                "title": title,
                "context": (context or "")[:_MAX_CONTEXT_CHARS],
                "summary": (summary_text or "")[:_MAX_SUMMARY_CHARS],
                "key_points": [str(p)[:200] for p in (key_points or [])][:8],
            }
        else:
            block = {
                "n": number,
                "kind": kind,
                "title": item_meta[sid],
                "context": (context or "")[:_MAX_CONTEXT_CHARS],
            }
        evidence.append(block)
        number_to_citation[number] = _citation_id(kind, sid)
        if len(evidence) >= MAX_EVIDENCE_SOURCES:
            break

    return evidence, number_to_citation


def _map_citations(
    sources: list[int], number_to_citation: dict[int, str], valid_ids: set[str]
) -> list[str]:
    """Resolve model source-numbers to real citation ids, dropping fabrications."""
    out: list[str] = []
    for n in sources:
        cid = number_to_citation.get(n)
        if cid and cid in valid_ids and cid not in out:
            out.append(cid)
    return out


async def synthesize_entity_page(
    db: AsyncSession,
    user_id: uuid.UUID,
    entity_id: uuid.UUID,
    *,
    cerebras_client: Any | None = None,
) -> EntityPageSnapshot | None:
    """Compile the dossier for one entity and upsert its snapshot.

    Returns None if the entity isn't the user's or has no usable sources.
    Raises ``CerebrasResponseError`` if the model output is unusable — callers
    that must stay resilient (the page route) catch it; tests assert on it.
    """
    entity = (
        await db.execute(
            select(Entity).where(Entity.id == entity_id, Entity.user_id == user_id)
        )
    ).scalar_one_or_none()
    if entity is None:
        return None

    page = await build_entity_page(db, user_id, entity_id)
    if page is None or not page.citations:
        return None  # honest skeleton — nothing to compile, no LLM call

    valid_ids = {c.id for c in page.citations}
    evidence, number_to_citation = await _gather_evidence(db, user_id, entity_id)
    if not evidence:
        return None

    settings = get_settings()
    client = cerebras_client if cerebras_client is not None else get_cerebras_client()
    user_payload = {
        "entity": {"name": entity.name, "type": entity.type},
        "sources": evidence,
    }
    response = await client.chat.completions.create(
        model=settings.cerebras_llm_model,
        messages=[
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": _json_dumps(user_payload)},
        ],
        response_format=strict_json_response_format(_SynthResult, name="entity_dossier"),
        temperature=0.2,
    )
    result = chat_completion_parsed(
        response, _SynthResult, operation="entity_page_synthesis"
    )

    facts = [
        {"text": f.text.strip(), "citation_ids": cites}
        for f in result.facts
        if f.text.strip()
        and (cites := _map_citations(f.sources, number_to_citation, valid_ids))
    ]
    timeline = [
        {
            "title": e.title.strip(),
            "description": (e.description or "").strip() or None,
            "occurred_at": occ.isoformat() if (occ := _coerce_occurred_at(e.occurred_at)) else None,
            "citation_ids": cites,
        }
        for e in result.timeline
        if e.title.strip()
        and (cites := _map_citations(e.sources, number_to_citation, valid_ids))
    ]
    questions = [
        {"text": q.text.strip(), "citation_ids": cites}
        for q in result.questions
        if q.text.strip()
        and (cites := _map_citations(q.sources, number_to_citation, valid_ids))
    ]
    overview = result.overview.strip() or page.overview

    snapshot = (
        await db.execute(
            select(EntityPageSnapshot).where(EntityPageSnapshot.entity_id == entity_id)
        )
    ).scalar_one_or_none()
    fingerprint = entity_source_fingerprint(page, entity.updated_at)
    citations_payload = [
        {
            "id": c.id,
            "source_kind": c.source_kind,
            "source_id": c.source_id,
            "title": c.title,
        }
        for c in page.citations
    ]
    now = datetime.now(timezone.utc)
    if snapshot is None:
        snapshot = EntityPageSnapshot(
            user_id=user_id,
            entity_id=entity_id,
            source_fingerprint=fingerprint,
            source_count=len(page.citations),
            overview=overview,
            facts=facts,
            citations=citations_payload,
            timeline=timeline,
            related_explanations=[],
            questions=questions,
            actions=[],
            compiled_at=now,
        )
        db.add(snapshot)
    else:
        snapshot.source_fingerprint = fingerprint
        snapshot.source_count = len(page.citations)
        snapshot.overview = overview
        snapshot.facts = facts
        snapshot.citations = citations_payload
        snapshot.timeline = timeline
        snapshot.questions = questions
        snapshot.compiled_at = now
    await db.flush()
    return snapshot


async def ensure_entity_page(
    db: AsyncSession, user_id: uuid.UUID, entity_id: uuid.UUID
) -> EntityPage | None:
    """Return the entity page, compiling its dossier inline on a cache miss.

    Resilient by design: a synthesis failure logs and returns the deterministic
    page with ``cache_status="error"`` — the real backlinks still render, and we
    never fabricate the compiled fields.
    """
    page = await build_entity_page(db, user_id, entity_id)
    if page is None:
        return None
    if page.cache_status != "stale":
        return page  # ready (cache hit) or skeleton (no sources)
    try:
        await synthesize_entity_page(db, user_id, entity_id)
    except CerebrasResponseError:
        logger.warning("entity_page_synthesis failed for entity=%s", entity_id)
        page.cache_status = "error"
        return page
    refreshed = await build_entity_page(db, user_id, entity_id)
    return refreshed or page


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
