"""Nightly memory consolidator (Letta sleep-time × gbrain Dream Cycle).

Reads the last ~24h of conversations + new recordings per active user,
asks an LLM to produce a JSON list of memory updates, and applies them
via the same `write_block` path the in-turn `remember` tool uses —
single source of truth, single audit trail.

Schedule: daily 03:00 UTC via Celery beat. Per-user-local-time
scheduling is a Phase 4 nicety; UTC night covers most users.

References:
- Letta sleep-time agents: docs.letta.com/guides/agents/architectures/sleeptime
  arXiv 2504.13171 (5x compute reduction, +13-18% accuracy)
- gbrain Dream Cycle (11-phase autonomous enhancement)
- Anthropic just-in-time retrieval: the wiki *compounds*; raw RAG
  re-derives knowledge per query.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import memory_proposal as memory_proposal_module
from app.core import user_memory as user_memory_module
from app.core.openai_client import get_openai_client
from app.db.session import get_db_context
from app.models.companion import ChatMessage, Conversation
from app.models.recording import Recording, Summary
from app.models.user import User
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


CONSOLIDATOR_SYSTEM_PROMPT = (
    "You are the nightly memory consolidator for the Wai second brain. "
    "Read the new material from the last 24 hours and return a compact "
    "JSON object {\"updates\": [{block, operation, content, target_line?, "
    "confidence}]}. "
    "Allowed blocks: human (durable facts about the user), topics "
    "(recurring subjects), preferences (how they want to be answered). "
    "Allowed operations: append (new bullet), replace_line (corrects one "
    "earlier claim — requires target_line that matches verbatim), rewrite "
    "(replaces whole block). Only emit updates that are durable — skip "
    "single-day tasks, momentary feelings, and trivia. For each update give "
    "a confidence in [0,1] for how certain and clearly-supported the fact is: "
    "additive high-confidence facts are saved automatically, while corrections "
    "and low-confidence guesses are held for the user to review. Keep content "
    "concise (one bullet per update, ≤200 chars). If nothing durable "
    "happened, return {\"updates\": []}."
)


def _consolidator_schema() -> dict[str, Any]:
    return {
        "name": "wai_memory_updates",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "updates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "block": {
                                "type": "string",
                                "enum": ["human", "topics", "preferences"],
                            },
                            "operation": {
                                "type": "string",
                                "enum": ["append", "replace_line", "rewrite"],
                            },
                            "content": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 500,
                            },
                            "target_line": {"type": ["string", "null"]},
                            "confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                        },
                        "required": [
                            "block",
                            "operation",
                            "content",
                            "target_line",
                            "confidence",
                        ],
                    },
                },
            },
            "required": ["updates"],
        },
    }


async def _gather_user_material(
    db: AsyncSession, user_id: uuid.UUID, since: datetime
) -> dict[str, Any]:
    """Pull the last 24h of conversations + recording summaries for one
    user. Privacy: this stays inside the consolidator and is not
    forwarded to clients or Sentry."""
    msg_stmt = (
        select(ChatMessage)
        .join(Conversation, Conversation.id == ChatMessage.conversation_id)
        .where(
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
            ChatMessage.created_at >= since,
        )
        .order_by(ChatMessage.created_at.asc())
        .limit(500)
    )
    msgs = (await db.execute(msg_stmt)).scalars().all()
    transcript_messages = [
        {
            "role": m.role,
            "content": (
                m.content
                if isinstance(m.content, str)
                else json.dumps(m.content)[:2000]
            ),
        }
        for m in msgs
    ]

    rec_stmt = (
        select(Recording, Summary)
        .outerjoin(Summary, Summary.recording_id == Recording.id)
        .where(
            Recording.user_id == user_id,
            Recording.deleted_at.is_(None),
            Recording.created_at >= since,
        )
        .order_by(Recording.created_at.desc())
        .limit(20)
    )
    rec_rows = list((await db.execute(rec_stmt)).all())
    new_recordings = [
        {
            "title": rec.title,
            "type": rec.type,
            "summary": (summary.summary if summary is not None else None),
            "topics": (summary.topics if summary is not None else None),
            "key_points": (
                summary.key_points if summary is not None else None
            ),
            "people_mentioned": (
                summary.people_mentioned if summary is not None else None
            ),
        }
        for (rec, summary) in rec_rows
    ]
    return {
        "messages": transcript_messages,
        "new_recordings": new_recordings,
    }


async def _apply_updates(
    db: AsyncSession,
    user_id: uuid.UUID,
    updates: list[dict[str, Any]],
) -> dict[str, int]:
    """Route each LLM-proposed update through the governance gate. Additive,
    confident, first-party facts auto-apply to memory (the same write_block
    path as before); destructive corrections and low-confidence guesses are
    queued as proposals for one-tap review. Returns counts by disposition."""
    auto_applied = queued = duplicates = 0
    for upd in updates:
        outcome = await memory_proposal_module.propose_block_update(
            db,
            user_id,
            block_label=upd["block"],
            operation=upd["operation"],
            content=upd["content"],
            target_line=upd.get("target_line"),
            confidence=float(upd.get("confidence", 0.5)),
            authority="self",
        )
        if outcome is None:
            duplicates += 1
        elif outcome.decision == "auto_accepted":
            auto_applied += 1
        else:
            queued += 1
    return {
        "auto_applied": auto_applied,
        "queued": queued,
        "duplicates": duplicates,
    }


async def _consolidate_one_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    openai_client=None,
    now: datetime | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    client = openai_client if openai_client is not None else get_openai_client()
    since = (now or datetime.now(timezone.utc)) - timedelta(hours=24)

    material = await _gather_user_material(db, user_id, since)
    if not material["messages"] and not material["new_recordings"]:
        return {"updates_applied": 0, "updates_rejected": 0, "skipped": True}

    blocks = await user_memory_module.get_or_seed_blocks(db, user_id)
    current_state = "\n\n".join(
        f"## {label} (limit {blocks[label].char_limit})\n{blocks[label].body}"
        for label in user_memory_module.BLOCK_SPECS
    )

    user_payload = {
        "current_memory_blocks": current_state,
        "new_material": material,
    }

    response = await client.responses.create(
        model=settings.openai_llm_model,
        instructions=CONSOLIDATOR_SYSTEM_PROMPT,
        input=[{"role": "user", "content": json.dumps(user_payload)}],
        text={
            "format": {
                "type": "json_schema",
                **_consolidator_schema(),
            }
        },
        prompt_cache_key=f"wai-consolidator-{user_id}",
    )
    text = _first_output_text(response)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError) as exc:
        logger.warning("consolidator parse failure user=%s: %s", user_id, exc)
        return {"auto_applied": 0, "queued": 0, "parse_error": True}

    updates = parsed.get("updates") or []
    counts = await _apply_updates(db, user_id, updates)
    return {**counts, "considered": len(updates)}


def _first_output_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return text
    output = getattr(response, "output", None)
    if not output:
        return ""
    for item in output:
        content = getattr(item, "content", None) or (
            item.get("content") if isinstance(item, dict) else None
        )
        for c in content or []:
            if isinstance(c, dict) and c.get("type") == "output_text":
                return c.get("text", "")
            if getattr(c, "type", None) == "output_text":
                return getattr(c, "text", "")
    return ""


async def _consolidate_all_active_users() -> dict[str, Any]:
    """Walk every non-deleted user once. Each user gets its own DB session
    so a single failure doesn't poison the batch."""
    async with get_db_context() as scan_db:
        user_ids = list(
            (
                await scan_db.execute(
                    select(User.id).order_by(User.id)
                )
            ).scalars().all()
        )

    summary = {"users_processed": 0, "users_skipped": 0, "failures": 0}
    for user_id in user_ids:
        try:
            async with get_db_context() as user_db:
                result = await _consolidate_one_user(user_db, user_id)
                if result.get("skipped"):
                    summary["users_skipped"] += 1
                else:
                    summary["users_processed"] += 1
        except Exception:
            logger.exception(
                "consolidator failed for user_id=%s", user_id
            )
            summary["failures"] += 1
    return summary


@celery_app.task(name="app.tasks.consolidate_user_memory.run")
def run() -> dict[str, Any]:
    """Celery beat entrypoint — daily 03:00 UTC."""
    return asyncio.run(_consolidate_all_active_users())
