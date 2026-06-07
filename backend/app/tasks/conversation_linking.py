"""Celery tasks that keep Wai chats linked into the Brain.

Two entry points:

- ``link_conversation`` — enqueued (debounced) when a chat turn completes, so
  every conversation auto-joins the Brain as it accrues content. The work is
  idempotent and watermark-guarded, so coalesced/duplicate enqueues are cheap
  no-ops.
- ``sweep_unlinked_conversations`` — a nightly bounded backstop that links the
  legacy backlog of chats that predate auto-linking (or that a dropped enqueue
  missed), one isolated session per user like the memory consolidator.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy import select

from app.core.conversation_brain import (
    link_conversation_to_brain,
    link_unlinked_conversations,
)
from app.db.session import get_db_context
from app.models.companion import Conversation
from app.models.user import User
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# Per-user cap for the nightly backstop — bounds cost; auto-link-on-turn keeps
# active chats current, so the backstop only chips away at the legacy backlog.
_SWEEP_LIMIT_PER_USER = 25


async def _link_conversation(conversation_id: str, user_id: str) -> None:
    async with get_db_context() as db:
        result = await link_conversation_to_brain(
            db, UUID(user_id), UUID(conversation_id)
        )
    logger.info(
        "link_conversation task conv=%s linked=%s reason=%s",
        conversation_id,
        result.linked,
        result.skipped_reason,
    )


@celery_app.task(
    name="app.tasks.conversation_linking.link_conversation",
    acks_late=True,
    soft_time_limit=120,
    time_limit=150,
)
def link_conversation(conversation_id: str, user_id: str) -> None:
    """Link one conversation into the Brain (entity mentions + searchable chunks).

    Best-effort + watermark-debounced: if nothing new arrived since the last
    link this is a no-op. Failures are logged; the nightly sweep is the backstop.
    """
    try:
        asyncio.run(_link_conversation(conversation_id, user_id))
    except Exception:
        logger.exception(
            "link_conversation task failed conv=%s", conversation_id
        )


async def _sweep_unlinked_conversations(limit_per_user: int) -> dict[str, int]:
    async with get_db_context() as scan_db:
        user_ids = list(
            (await scan_db.execute(select(User.id).order_by(User.id)))
            .scalars()
            .all()
        )

    totals = {
        "users_processed": 0,
        "conversations_linked": 0,
        "mentions_recorded": 0,
        "failures": 0,
    }
    for user_id in user_ids:
        try:
            async with get_db_context() as user_db:
                # Cheap pre-check so we don't open work for users with nothing
                # to link.
                has_unlinked = (
                    await user_db.execute(
                        select(Conversation.id).where(
                            Conversation.user_id == user_id,
                            Conversation.deleted_at.is_(None),
                            Conversation.archived_at.is_(None),
                            Conversation.brain_linked_message_count == 0,
                            Conversation.last_message_at.isnot(None),
                        ).limit(1)
                    )
                ).first()
                if has_unlinked is None:
                    continue
                result = await link_unlinked_conversations(
                    user_db, user_id, limit=limit_per_user
                )
            totals["users_processed"] += 1
            totals["conversations_linked"] += result.conversations_linked
            totals["mentions_recorded"] += result.mentions_recorded
        except Exception:
            logger.exception(
                "conversation link sweep failed for user_id=%s", user_id
            )
            totals["failures"] += 1
    return totals


@celery_app.task(name="app.tasks.conversation_linking.sweep_unlinked_conversations")
def sweep_unlinked_conversations(
    limit_per_user: int = _SWEEP_LIMIT_PER_USER,
) -> dict[str, int]:
    """Nightly backstop: link the legacy backlog of never-linked chats."""
    return asyncio.run(_sweep_unlinked_conversations(limit_per_user))
