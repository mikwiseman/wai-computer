"""Ingestion orchestrator: pull a connected MCP server's data into the brain.

Resources-first: list the server's resources, read each, run it through the
untrusted-content boundary (secret redaction), and ingest it idempotently as an
``Item(source="mcp:<connection_id>")``. Each sync is wrapped in an
``McpIngestionRun`` for idempotency + observability, and advances the
connection's ``sync_cursor``.

Security:
- Only resources are pulled by default (read-only data). Tools are NEVER called
  unless explicitly allow-listed on the connection — and even then only through
  a separate, deliberate path (not this default sync).
- Every resource body is secret-redacted before storage/embedding; bodies that
  still look secret are marked ``privacy_level="secret"`` and never summarized.
- Per-sync resource count + byte caps come from the client (defense-in-depth).

The MCP client is injectable so this orchestrator is unit-testable offline.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.item_ingest import ingest_item
from app.core.mcp_client import McpClient, McpResource
from app.core.secrets_crypto import decrypt_secret
from app.core.untrusted import contains_secret, redact_secrets
from app.models.mcp_connection import McpConnection, McpIngestionRun

logger = logging.getLogger(__name__)

ClientFactory = Callable[[str, str | None], Any]


@dataclass
class SyncResult:
    run_id: str
    seen: int
    created: int
    skipped: int
    status: str


def _connection_token(connection: McpConnection) -> str | None:
    if connection.auth_type == "none" or not connection.auth_secret_encrypted:
        return None
    return decrypt_secret(connection.auth_secret_encrypted)


async def sync_connection(
    db: AsyncSession,
    connection: McpConnection,
    *,
    client_factory: ClientFactory | None = None,
    embedder: Callable[[list[str]], Awaitable[list[list[float]]]] | None = None,
    summarize: bool = False,
) -> SyncResult:
    """Pull resources from one connection into Items. Records an McpIngestionRun.

    ``summarize=False`` by default: the sync captures raw items fast (signal-
    capture-first); the per-item summary task enriches them afterward.
    """
    run = McpIngestionRun(
        connection_id=connection.id,
        status="running",
        cursor_before=connection.sync_cursor,
    )
    db.add(run)
    await db.flush()

    factory = client_factory or (lambda url, token: McpClient(url, token))
    seen = created = skipped = 0
    try:
        token = _connection_token(connection)
        client = factory(connection.server_url, token)
        resources: list[McpResource] = await client.list_resources()

        for resource in resources:
            seen += 1
            try:
                raw = await client.read_resource(resource.uri)
            except Exception:  # noqa: BLE001 — skip a bad resource, keep syncing
                logger.info("mcp resource read failed uri_hash=%s", hash(resource.uri))
                skipped += 1
                continue

            body = redact_secrets(raw)
            if not body.strip():
                skipped += 1
                continue

            privacy = "secret" if contains_secret(raw) else connection.privacy_level
            title = (resource.name or resource.description or resource.uri)[:500]

            _item, was_created = await ingest_item(
                db,
                connection.user_id,
                source=f"mcp:{connection.id}",
                source_ref=resource.uri,
                kind="mcp_resource",
                title=title,
                body=body,
                dedup_key=f"mcp:{connection.id}:{resource.uri}",
                privacy_level=privacy,
                authority_score=0.8,  # the user's own connected source = high authority
                embed=True,
                embedder=embedder,
            )
            created += 1 if was_created else 0
            skipped += 0 if was_created else 1

        cursor_after = datetime.now(timezone.utc).isoformat()
        run.status = "succeeded"
        run.cursor_after = cursor_after
        run.items_seen = seen
        run.items_created = created
        run.items_skipped = skipped
        run.finished_at = datetime.now(timezone.utc)
        connection.sync_cursor = cursor_after
        connection.last_sync_at = datetime.now(timezone.utc)
        connection.status = "active"
        connection.last_error = None
        await db.flush()
        logger.info(
            "mcp sync ok connection=%s seen=%s created=%s skipped=%s",
            connection.id, seen, created, skipped,
        )
        return SyncResult(str(run.id), seen, created, skipped, "succeeded")

    except Exception as exc:  # noqa: BLE001 — record failure on the run + connection
        run.status = "failed"
        run.error_code = type(exc).__name__
        run.error_message = "sync failed"
        run.items_seen = seen
        run.items_created = created
        run.items_skipped = skipped
        run.finished_at = datetime.now(timezone.utc)
        connection.status = "error"
        connection.last_error = type(exc).__name__
        await db.flush()
        logger.warning("mcp sync failed connection=%s error=%s", connection.id, type(exc).__name__)
        raise
