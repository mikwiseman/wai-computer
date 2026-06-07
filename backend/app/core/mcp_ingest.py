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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.item_ingest import ingest_item
from app.core.mcp_client import McpClient, McpResource
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

# Defense-in-depth caps for the tool path (D4 adds the full Redis cost guard +
# incremental watermarks; these keep a single run bounded in the meantime).
MAX_PAGES_PER_STEP = 50
MAX_SCOPES_PER_STEP = 200
MAX_RECORDS_PER_SYNC = 2000


@dataclass
class SyncResult:
    run_id: str
    seen: int
    created: int
    skipped: int
    status: str  # succeeded | failed | needs_setup


class DisallowedToolError(RuntimeError):
    """A plan tried to call a tool that isn't allow-listed or is a mutation."""


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
                t_seen, t_created, t_skipped = await _run_plan(
                    db, connection, client, plan, embedder
                )
                seen += t_seen
                created += t_created
                skipped += t_skipped

        cursor_after = datetime.now(timezone.utc).isoformat()
        run.status = "succeeded"
        run.cursor_after = cursor_after
        run.items_seen = seen
        run.items_created = created
        run.items_skipped = skipped
        run.finished_at = datetime.now(timezone.utc)
        connection.sync_cursor = cursor_after
        connection.last_sync_at = datetime.now(timezone.utc)
        if final_status == "needs_setup":
            connection.status = "needs_setup"
            connection.last_error = "no_readable_data_tools"
            run.error_code = "needs_setup"
        else:
            connection.status = "active"
            connection.last_error = None
        await db.flush()
        logger.info(
            "mcp sync %s connection=%s seen=%s created=%s skipped=%s",
            final_status, connection.id, seen, created, skipped,
        )
        return SyncResult(str(run.id), seen, created, skipped, final_status)

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
) -> tuple[int, int, int]:
    allowed = plan_tools(plan)
    call = _guarded_call(allowed)
    seen = created = skipped = 0
    for step in plan.steps:
        if seen >= MAX_RECORDS_PER_SYNC:
            break
        scopes = await _scope_ids(call, client, step)
        for scope in scopes:
            if seen >= MAX_RECORDS_PER_SYNC:
                break
            s, c, k = await _drain_step(
                db, connection, call, client, step, scope, embedder,
                budget=MAX_RECORDS_PER_SYNC - seen,
            )
            seen += s
            created += c
            skipped += k
    return seen, created, skipped


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
    *,
    budget: int,
) -> tuple[int, int, int]:
    seen = created = skipped = 0
    cursor_val: Any = None
    stream_key = step.enumerate_tool if scope is None else f"{step.enumerate_tool}:{scope}"
    for _page in range(MAX_PAGES_PER_STEP):
        if seen >= budget:
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
            if seen >= budget:
                break
            n_created, n_total = await _ingest_from_record(
                db, connection, call, client, step, record, embedder, stream_key
            )
            seen += n_total
            created += n_created
            skipped += n_total - n_created
        cursor_val = _next_cursor(raw, step.cursor)
        if not cursor_val:
            break
    return seen, created, skipped


async def _ingest_from_record(
    db: AsyncSession,
    connection: McpConnection,
    call,
    client: Any,
    step: FetchStep,
    enum_record: dict,
    embedder: Embedder | None,
    stream_key: str,
) -> tuple[int, int]:
    """Ingest one enumerate row (fetching full content first if configured).

    Returns ``(items_created, items_total)``.
    """
    records_to_ingest: list[dict] = [enum_record]
    if step.fetch_tool:
        fetch_id = dig(enum_record, step.id_path) if step.id_path else None
        if fetch_id is None:
            fetch_id = first_value(enum_record, step.field_map.source_ref + ["id", "uri", "path"])
        if fetch_id is None:
            return 0, 1
        try:
            fraw = await call(client, step.fetch_tool, {step.fetch_arg or "id": fetch_id})
        except DisallowedToolError:
            raise
        except Exception:  # noqa: BLE001 — skip a bad fetch, keep syncing
            logger.info("mcp fetch failed tool=%s", step.fetch_tool)
            return 0, 1
        fetched = parse_records(fraw, step.fetch_record_path)
        records_to_ingest = fetched or [enum_record]

    n_created = n_total = 0
    for record in records_to_ingest:
        kw = record_to_item_kwargs(
            record, step=step, connection_id=str(connection.id), stream_key=stream_key
        )
        raw_body = kw["body"]
        body = redact_secrets(raw_body)
        if not body.strip():
            continue
        n_total += 1
        privacy = "secret" if contains_secret(raw_body) else connection.privacy_level
        _item, was_created = await ingest_item(
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
        if was_created:
            n_created += 1
    return n_created, n_total


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
