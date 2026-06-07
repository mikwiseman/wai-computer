"""Ingestion orchestrator: pull a connected MCP server's data into the brain.

Two paths, one destination (idempotent ``ingest_item`` -> the brain pipeline):

- **resources** — list the server's MCP resources, read each, ingest. For
  servers that expose their data as MCP resources.
- **tools** — most real data servers (Gmail/Telegram/Notion/Obsidian/Drive)
  expose their data through *tools*, not resources. We resolve an
  :class:`~app.core.mcp_plan.IngestionPlan` (a recipe for known servers, else a
  heuristic from the tool schemas) and drive ``enumerate(->fetch)->map`` over
  it. If we cannot resolve a plan, the connection is flagged ``needs_setup`` —
  loud, never a silent zero-ingest.

Read-only safety: every tool call goes through one chokepoint
(:func:`_guarded_call`) that refuses any tool not on the plan's allow-list and
any tool whose name implies a mutation, so a sync can never call
``send_message`` / ``delete_*`` / ``write_*``.

Each sync is wrapped in an ``McpIngestionRun`` for idempotency + observability.
The MCP client is injectable so this orchestrator is unit-testable offline.
"""

from __future__ import annotations

import json
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.entity_graph import reconcile_person_entities, seed_entities_from_metadata
from app.core.item_ingest import ingest_item
from app.core.mcp_client import McpClient, McpResource
from app.core.mcp_entity_extract import ExtractorShapeError
from app.core.mcp_ingest_guard import mcp_ingestion_halted
from app.core.mcp_item_map import dig, first_value, parse_records, record_to_item_kwargs
from app.core.mcp_plan import FetchStep, IngestionPlan, plan_tools, resolve_plan_from_tools
from app.core.mcp_recipes import match_recipe
from app.core.mcp_tool_classify import is_mutation
from app.core.secrets_crypto import decrypt_secret
from app.core.untrusted import contains_secret, redact_secrets
from app.models.mcp_connection import McpConnection, McpIngestionRun

logger = logging.getLogger(__name__)

ClientFactory = Callable[[str, str | None], Any]
Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]

# Defense-in-depth caps for the tool path (incremental watermarks are a planned
# extension; these + content-hash dedup keep a single run bounded meanwhile).
MAX_PAGES_PER_STEP = 50
MAX_SCOPES_PER_STEP = 200
MAX_RECORDS_PER_SYNC = 2000

# State machine: how many consecutive transient failures before we give up and
# flag the connection terminal (loud "reconnect needed") instead of retrying.
MAX_TRANSIENT_FAILURES = 8
_BACKOFF_CAP_MINUTES = 60
_NEEDS_SETUP_REPROBE_MINUTES = 360  # re-probe an unreadable server ~every 6h

# Error-message hints that mean "the user must act" (auth), not "retry later".
_TERMINAL_HINTS = (
    "401", "403", "unauthorized", "forbidden", "invalid_token", "invalid token",
    "token expired", "expired", "invalid grant", "authentication failed",
)


def _jitter(minutes: float) -> float:
    return max(1.0, minutes * random.uniform(0.85, 1.15))


def _next_after(minutes: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=_jitter(minutes))


def _classify_error(exc: Exception) -> tuple[str, bool]:
    """Map an exception to (classified_code, is_terminal). No PII in the code."""
    name = type(exc).__name__
    msg = str(exc).lower()
    if name in ("InvalidToken", "InvalidSignature"):  # Fernet decrypt failure
        return "decrypt_failed", True
    if any(hint in msg for hint in _TERMINAL_HINTS):
        return "auth_expired", True
    if "timeout" in msg or name.endswith("TimeoutError"):
        return "timeout", False
    if "429" in msg or "rate limit" in msg:
        return "rate_limited", False
    if any(s in msg for s in ("500", "502", "503", "504", "gateway", "unavailable")):
        return "provider_5xx", False
    if "connect" in msg or "network" in msg or name in ("ConnectionError", "ConnectError"):
        return "network", False
    return "sync_error", False


@dataclass
class SyncResult:
    run_id: str
    seen: int
    created: int
    skipped: int
    status: str  # succeeded | failed | needs_setup


class DisallowedToolError(RuntimeError):
    """A plan tried to call a tool that isn't allow-listed or is a mutation."""


@dataclass
class _ToolStats:
    seen: int = 0
    created: int = 0
    skipped: int = 0
    mentions: int = 0      # graph mentions written from item metadata
    persons: int = 0       # person mentions (drives a single end-of-sync reconcile)
    errors: int = 0        # structured-extractor shape failures


def _connection_token(connection: McpConnection) -> str | None:
    if connection.auth_type == "none" or not connection.auth_secret_encrypted:
        return None
    return decrypt_secret(connection.auth_secret_encrypted)


async def sync_connection(
    db: AsyncSession,
    connection: McpConnection,
    *,
    client_factory: ClientFactory | None = None,
    embedder: Embedder | None = None,
    summarize: bool = False,
) -> SyncResult:
    """Pull a connection's data into Items via resources and/or tools.

    ``summarize=False`` by default: the sync captures raw items fast (signal-
    capture-first); the per-item summary task enriches them afterward.
    """
    # Emergency kill-switch: defer (the dispatcher lease re-fires later), never
    # a failed run — a halt is operational, not a connection fault.
    if await mcp_ingestion_halted(connection.user_id):
        logger.info("mcp sync halted by guard connection=%s", connection.id)
        return SyncResult("", 0, 0, 0, "deferred")

    run = McpIngestionRun(
        connection_id=connection.id,
        status="running",
        cursor_before=connection.sync_cursor,
    )
    db.add(run)
    await db.flush()

    factory = client_factory or (lambda url, token: McpClient(url, token))
    seen = created = skipped = 0
    final_status = "succeeded"
    try:
        token = _connection_token(connection)
        client = factory(connection.server_url, token)

        # ── Path A: resources ──────────────────────────────────────────────
        resources: list[McpResource] = (
            await client.list_resources() if hasattr(client, "list_resources") else []
        )
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

        # ── Path B: tools (servers whose data lives behind tools) ───────────
        if seen == 0 and hasattr(client, "introspect") and hasattr(client, "call_tool"):
            plan = await _resolve_plan(client)
            if plan is None or not plan.steps:
                final_status = "needs_setup"
            else:
                stats = await _run_plan(db, connection, client, plan, embedder)
                seen += stats.seen
                created += stats.created
                skipped += stats.skipped
                run.mentions_recorded = stats.mentions
                run.extract_errors = stats.errors
                # A spike of structured-extractor failures means a provider
                # format drift — flip to a visible "degraded" state, not silent.
                if stats.errors and stats.seen and stats.errors / stats.seen > 0.25:
                    final_status = "degraded"

        now = datetime.now(timezone.utc)
        cursor_after = now.isoformat()
        run.status = "succeeded"
        run.cursor_after = cursor_after
        run.items_seen = seen
        run.items_created = created
        run.items_skipped = skipped
        run.finished_at = now
        connection.sync_cursor = cursor_after
        connection.last_sync_at = now
        connection.consecutive_failures = 0
        if final_status == "needs_setup":
            # Read attempt succeeded mechanically but we can't read this server;
            # stay visibly "needs_setup" and re-probe slowly (tools may appear).
            connection.status = "needs_setup"
            connection.last_error = "no_readable_data_tools"
            connection.last_error_code = "needs_setup"
            run.error_code = "needs_setup"
            connection.next_sync_at = _next_after(_NEEDS_SETUP_REPROBE_MINUTES)
        else:
            connection.last_success_at = now
            connection.last_error = None
            connection.last_error_code = None
            connection.next_sync_at = _next_after(connection.sync_interval_minutes)
            if final_status == "degraded":
                connection.status = "degraded"
                connection.last_error = "structured_extraction_failing"
                run.error_code = "extract_degraded"
            else:
                connection.status = "active"
        await db.flush()
        logger.info(
            "mcp sync %s connection=%s seen=%s created=%s skipped=%s",
            final_status, connection.id, seen, created, skipped,
        )
        return SyncResult(str(run.id), seen, created, skipped, final_status)

    except Exception as exc:  # noqa: BLE001 — record failure on the run + connection
        now = datetime.now(timezone.utc)
        code, terminal = _classify_error(exc)
        connection.consecutive_failures = (connection.consecutive_failures or 0) + 1
        if connection.consecutive_failures >= MAX_TRANSIENT_FAILURES:
            terminal = True  # give up retrying; ask the user to reconnect
        run.status = "failed"
        run.error_code = code
        run.error_message = None  # classified code + connection state carry the signal
        run.items_seen = seen
        run.items_created = created
        run.items_skipped = skipped
        run.finished_at = now
        connection.last_error = code
        connection.last_error_code = code
        connection.last_error_at = now
        if terminal:
            # Terminal (auth/decrypt or exhausted retries): stop + loud reconnect.
            connection.status = "error_terminal"
            connection.next_sync_at = None
        else:
            # Transient (network/5xx/timeout): stay eligible, back off + retry.
            connection.status = "error_transient"
            backoff = min(
                connection.sync_interval_minutes * (2 ** connection.consecutive_failures),
                _BACKOFF_CAP_MINUTES,
            )
            connection.next_sync_at = _next_after(backoff)
        await db.flush()
        logger.warning(
            "mcp sync failed connection=%s code=%s terminal=%s failures=%s",
            connection.id, code, terminal, connection.consecutive_failures,
        )
        raise


# ── plan resolution ─────────────────────────────────────────────────────────
async def _resolve_plan(client: Any) -> IngestionPlan | None:
    """Recipe (known server) -> heuristic (from tool schemas) -> None."""
    intro = await client.introspect()
    specs = list(getattr(intro, "tool_specs", None) or [])
    names = [s.name for s in specs] if specs else list(getattr(intro, "tools", []))
    recipe = match_recipe(names)
    if recipe is not None:
        return recipe
    if specs:
        return resolve_plan_from_tools(specs)
    return None


# ── tool execution (read-only, bounded) ─────────────────────────────────────
def _guarded_call(allowed: set[str]) -> Callable[[Any, str, dict], Awaitable[str]]:
    """A call_tool wrapper that enforces the allow-list + mutation gate."""

    async def _call(client: Any, name: str, args: dict) -> str:
        if name not in allowed or is_mutation(name):
            raise DisallowedToolError(name)
        return await client.call_tool(name, args)

    return _call


async def _run_plan(
    db: AsyncSession,
    connection: McpConnection,
    client: Any,
    plan: IngestionPlan,
    embedder: Embedder | None,
) -> _ToolStats:
    allowed = plan_tools(plan)
    call = _guarded_call(allowed)
    stats = _ToolStats()
    for step in plan.steps:
        if stats.seen >= MAX_RECORDS_PER_SYNC:
            break
        scopes = await _scope_ids(call, client, step)
        for scope in scopes:
            if stats.seen >= MAX_RECORDS_PER_SYNC:
                break
            await _drain_step(db, connection, call, client, step, scope, embedder, stats)
    # Link freshly-seeded people to known speakers once per sync (the scan is
    # too heavy to run per item), idempotent + exact-name only.
    if stats.persons > 0:
        await reconcile_person_entities(db, connection.user_id)
    return stats


async def _scope_ids(call, client: Any, step: FetchStep) -> list[Any]:
    """Discover scope ids (e.g. Telegram chat ids) to fan an enumerate over."""
    if not step.scope_tool:
        return [None]
    raw = await call(client, step.scope_tool, {})
    records = parse_records(raw, None)
    ids: list[Any] = []
    for record in records[:MAX_SCOPES_PER_STEP]:
        sid = dig(record, step.scope_id_path) if step.scope_id_path else None
        if sid is None:
            sid = first_value(record, ["chat_id", "id", "chatId", "uri", "path"])
        if sid is not None:
            ids.append(sid)
    return ids or [None]


async def _drain_step(
    db: AsyncSession,
    connection: McpConnection,
    call,
    client: Any,
    step: FetchStep,
    scope: Any,
    embedder: Embedder | None,
    stats: _ToolStats,
) -> None:
    cursor_val: Any = None
    stream_key = step.enumerate_tool if scope is None else f"{step.enumerate_tool}:{scope}"
    for _page in range(MAX_PAGES_PER_STEP):
        if stats.seen >= MAX_RECORDS_PER_SYNC:
            break
        args = dict(step.enumerate_args)
        if scope is not None and step.scope_arg:
            args[step.scope_arg] = scope
        if step.cursor:
            if step.cursor.page_size_param:
                args.setdefault(step.cursor.page_size_param, step.cursor.page_size)
            if step.cursor.page_param and cursor_val is not None:
                args[step.cursor.page_param] = cursor_val
        raw = await call(client, step.enumerate_tool, args)
        records = parse_records(raw, step.record_path)
        if not records:
            break
        for record in records:
            if stats.seen >= MAX_RECORDS_PER_SYNC:
                break
            await _ingest_from_record(
                db, connection, call, client, step, record, embedder, stream_key, stats
            )
        cursor_val = _next_cursor(raw, step.cursor)
        if not cursor_val:
            break


async def _ingest_from_record(
    db: AsyncSession,
    connection: McpConnection,
    call,
    client: Any,
    step: FetchStep,
    enum_record: dict,
    embedder: Embedder | None,
    stream_key: str,
    stats: _ToolStats,
) -> None:
    """Ingest one enumerate row (fetching full content first if configured),
    then seed graph entities from each created item's structured record.
    """
    records_to_ingest: list[dict] = [enum_record]
    if step.fetch_tool:
        fetch_id = dig(enum_record, step.id_path) if step.id_path else None
        if fetch_id is None:
            fetch_id = first_value(enum_record, step.field_map.source_ref + ["id", "uri", "path"])
        if fetch_id is None:
            stats.seen += 1
            stats.skipped += 1
            return
        try:
            fraw = await call(client, step.fetch_tool, {step.fetch_arg or "id": fetch_id})
        except DisallowedToolError:
            raise
        except Exception:  # noqa: BLE001 — skip a bad fetch, keep syncing
            logger.info("mcp fetch failed tool=%s", step.fetch_tool)
            stats.seen += 1
            stats.skipped += 1
            return
        fetched = parse_records(fraw, step.fetch_record_path)
        records_to_ingest = fetched or [enum_record]

    for record in records_to_ingest:
        kw = record_to_item_kwargs(
            record, step=step, connection_id=str(connection.id), stream_key=stream_key
        )
        raw_body = kw["body"]
        body = redact_secrets(raw_body)
        if not body.strip():
            continue
        stats.seen += 1
        privacy = "secret" if contains_secret(raw_body) else connection.privacy_level
        item, was_created = await ingest_item(
            db,
            connection.user_id,
            source=f"mcp:{connection.id}",
            source_ref=kw["source_ref"],
            kind=kw["kind"],
            title=kw["title"],
            body=body,
            url=kw["url"],
            occurred_at=kw["occurred_at"],
            metadata=kw["metadata"],
            dedup_key=kw["dedup_key"],
            privacy_level=privacy,
            authority_score=0.8,
            embed=True,
            embedder=embedder,
        )
        if not was_created:
            stats.skipped += 1
            continue
        stats.created += 1
        # Zero-LLM structured linking from the raw record (only on create —
        # re-syncs dedup before this point, so mentions never duplicate).
        try:
            seeded = await seed_entities_from_metadata(
                db,
                connection.user_id,
                source_kind="item",
                source_id=item.id,
                kind=kw["kind"],
                metadata=kw["metadata"],
            )
            stats.mentions += seeded.mentions_recorded
            stats.persons += seeded.persons_seeded
        except ExtractorShapeError:
            stats.errors += 1
            logger.info("mcp extract shape error kind=%s", kw["kind"])


def _next_cursor(raw: str, cursor_spec) -> Any:
    """Find the next-page cursor in a tool response, if any."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if cursor_spec and cursor_spec.next_path:
        val = dig(data, cursor_spec.next_path)
        if val:
            return val
    for key in ("nextPageToken", "next_cursor", "nextCursor", "next_page_token", "cursor", "next"):
        val = data.get(key)
        if val:
            return val
    return None
