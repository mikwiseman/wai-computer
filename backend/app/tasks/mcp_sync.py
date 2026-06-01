"""Celery tasks for connect-any-MCP ingestion.

- ``sync_mcp_connection`` — sync ONE connection. A Redis lock per connection
  prevents two workers syncing the same server concurrently (idempotency is
  also guaranteed at the item level, but the lock avoids wasted work).
- ``dispatch_due_mcp_syncs`` — beat task: enqueue every enabled connection
  whose ``next_sync_at`` is due, and advance ``next_sync_at`` by its interval.

Per-item summaries are produced by the existing item summary task afterward;
this sync is signal-capture-first (fast raw capture).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from app.core.mcp_ingest import sync_connection
from app.core.observability import capture_sentry_exception, fingerprint_text
from app.db.session import get_db_context
from app.models.mcp_connection import McpConnection
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_LOCK_TTL_SECONDS = 1800  # 30 min — above a normal sync, below a stuck-forever


def _redis_client():
    """Best-effort Redis client for the per-connection lock (optional)."""
    try:
        import redis

        from app.config import get_settings

        return redis.Redis.from_url(get_settings().redis_url)
    except Exception:  # noqa: BLE001 — lock is an optimization, not a correctness req
        return None


async def _sync_one(connection_id: str) -> None:
    async with get_db_context() as db:
        conn = (
            await db.execute(
                select(McpConnection).where(McpConnection.id == UUID(connection_id))
            )
        ).scalar_one_or_none()
        if conn is None or not conn.enabled:
            logger.info("mcp sync skip — missing/disabled id=%s", connection_id)
            return
        await sync_connection(db, conn, summarize=False)


@celery_app.task(
    bind=True,
    name="app.tasks.mcp_sync.sync_mcp_connection",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=1500,
    time_limit=1620,
)
def sync_mcp_connection(self, *, connection_id: str) -> None:
    lock_key = f"mcp_sync_lock:{connection_id}"
    client = _redis_client()
    if client is not None:
        try:
            acquired = client.set(lock_key, "1", nx=True, ex=_LOCK_TTL_SECONDS)
            if not acquired:
                logger.info("mcp sync already running id=%s", connection_id)
                return
        except Exception:  # noqa: BLE001 — proceed without the lock if Redis hiccups
            client = None
    try:
        logger.info("mcp sync task started id=%s", connection_id)
        asyncio.run(_sync_one(connection_id))
        logger.info("mcp sync task finished id=%s", connection_id)
    except Exception as exc:  # noqa: BLE001
        capture_sentry_exception(exc)
        logger.error(
            "mcp sync task failed id=%s error_type=%s error_fingerprint=%s",
            connection_id,
            type(exc).__name__,
            fingerprint_text(str(exc)),
        )
        raise
    finally:
        if client is not None:
            try:
                client.delete(lock_key)
            except Exception:  # noqa: BLE001
                pass


async def _dispatch_due() -> int:
    now = datetime.now(timezone.utc)
    enqueued = 0
    async with get_db_context() as db:
        due = (
            await db.execute(
                select(McpConnection).where(
                    McpConnection.enabled.is_(True),
                    McpConnection.status != "error",
                    (McpConnection.next_sync_at.is_(None))
                    | (McpConnection.next_sync_at <= now),
                )
            )
        ).scalars().all()
        for conn in due:
            conn.next_sync_at = now + timedelta(minutes=conn.sync_interval_minutes)
            enqueued += 1
            conn_id = str(conn.id)
            await db.flush()
            try:
                sync_mcp_connection.delay(connection_id=conn_id)
            except Exception:  # noqa: BLE001 — broker optional; next beat retries
                pass
    return enqueued


@celery_app.task(name="app.tasks.mcp_sync.dispatch_due_mcp_syncs")
def dispatch_due_mcp_syncs() -> int:
    """Beat task: enqueue all due MCP connection syncs. Returns count enqueued."""
    return asyncio.run(_dispatch_due())
