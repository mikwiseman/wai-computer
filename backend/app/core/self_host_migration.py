"""Self-host migration contract.

This module describes how user-owned data moves before any archive/export code
is allowed to ship. It deliberately does not run SQL or SSH.
"""

from __future__ import annotations

from typing import Any

from app.core.data_ownership import ARTIFACT_OWNERSHIP, DATA_OWNERSHIP
from app.models import Base

MIGRATION_CONTRACT_VERSION = "2026-06-03"
ARCHIVE_FORMAT = "wai-self-host-export-v1"

DERIVED_OWNER_EDGES: dict[str, dict[str, str]] = {
    "recording_tags": {
        "parent_table": "tags",
        "local_column": "tag_id",
        "parent_column": "id",
        "owner_column": "user_id",
    },
    "entity_relations": {
        "parent_table": "entities",
        "local_column": "source_id",
        "parent_column": "id",
        "owner_column": "user_id",
    },
    "brain_space_members": {
        "parent_table": "brain_spaces",
        "local_column": "space_id",
        "parent_column": "id",
        "owner_column": "owner_user_id",
    },
    "brain_space_sources": {
        "parent_table": "brain_spaces",
        "local_column": "space_id",
        "parent_column": "id",
        "owner_column": "owner_user_id",
    },
    "brain_pages": {
        "parent_table": "brain_spaces",
        "local_column": "space_id",
        "parent_column": "id",
        "owner_column": "owner_user_id",
    },
    "brain_claims": {
        "parent_table": "brain_spaces",
        "local_column": "space_id",
        "parent_column": "id",
        "owner_column": "owner_user_id",
    },
    "brain_review_packs": {
        "parent_table": "brain_spaces",
        "local_column": "space_id",
        "parent_column": "id",
        "owner_column": "owner_user_id",
    },
    "agent_steps": {
        "parent_table": "agent_runs",
        "local_column": "run_id",
        "parent_column": "id",
        "owner_column": "user_id",
    },
    "chat_messages": {
        "parent_table": "conversations",
        "local_column": "conversation_id",
        "parent_column": "id",
        "owner_column": "user_id",
    },
    "conversation_chunks": {
        "parent_table": "conversations",
        "local_column": "conversation_id",
        "parent_column": "id",
        "owner_column": "user_id",
    },
    "message_citations": {
        "parent_table": "chat_messages",
        "local_column": "message_id",
        "parent_column": "id",
        "owner_column": "conversation.user_id",
    },
    "segments": {
        "parent_table": "recordings",
        "local_column": "recording_id",
        "parent_column": "id",
        "owner_column": "user_id",
    },
    "summaries": {
        "parent_table": "recordings",
        "local_column": "recording_id",
        "parent_column": "id",
        "owner_column": "user_id",
    },
    "highlights": {
        "parent_table": "recordings",
        "local_column": "recording_id",
        "parent_column": "id",
        "owner_column": "user_id",
    },
    "action_items": {
        "parent_table": "recordings",
        "local_column": "recording_id",
        "parent_column": "id",
        "owner_column": "user_id",
    },
    "item_chunks": {
        "parent_table": "items",
        "local_column": "item_id",
        "parent_column": "id",
        "owner_column": "user_id",
    },
    "item_summaries": {
        "parent_table": "items",
        "local_column": "item_id",
        "parent_column": "id",
        "owner_column": "user_id",
    },
    "mcp_ingestion_runs": {
        "parent_table": "mcp_connections",
        "local_column": "connection_id",
        "parent_column": "id",
        "owner_column": "user_id",
    },
    "billing_invoices": {
        "parent_table": "billing_subscriptions",
        "local_column": "subscription_id",
        "parent_column": "id",
        "owner_column": "user_id",
    },
    "billing_events": {
        "parent_table": "billing_subscriptions",
        "local_column": "subscription_id",
        "parent_column": "id",
        "owner_column": "user_id",
    },
    "transcript_segments": {
        "parent_table": "recordings",
        "local_column": "recording_id",
        "parent_column": "id",
        "owner_column": "user_id",
    },
}


def _table_scope_strategy(table_name: str) -> str:
    if table_name == "users":
        return "owner_scoped_primary_key"
    table = Base.metadata.tables.get(table_name)
    if table is None:
        return "model_table_missing"
    if "user_id" in table.columns:
        return "owner_scoped_user_id"
    if "owner_user_id" in table.columns:
        return "owner_scoped_owner_user_id"
    return "derived_owner_scoped"


def _derived_owner_edge(table_name: str) -> dict[str, str] | None:
    return DERIVED_OWNER_EDGES.get(table_name)


def migration_contract_response() -> dict[str, Any]:
    owned_tables = []
    reconnect_tables = []
    server_local_tables = []
    excluded_tables = []

    for entry in DATA_OWNERSHIP:
        table_spec = {
            "name": entry.name,
            "table": entry.table,
            "classification": entry.classification,
            "contains_user_content": entry.contains_user_content,
            "requires_reconnect": entry.requires_reconnect,
            "reason": entry.reason,
        }
        if entry.classification == "owned_exportable":
            owned_row = {
                **table_spec,
                "scope_strategy": _table_scope_strategy(entry.table),
                "export_strategy": "rows",
            }
            edge = _derived_owner_edge(entry.table)
            if edge is not None:
                owned_row["derived_owner_edge"] = edge
            owned_tables.append(owned_row)
        elif entry.classification == "reconnect_required":
            reconnect_tables.append(table_spec)
        elif entry.classification == "self_host_local":
            server_local_tables.append(table_spec)
        else:
            excluded_tables.append(table_spec)

    owned_artifacts = []
    reconnect_artifacts = []
    server_local_artifacts = []
    excluded_artifacts = []
    for entry in ARTIFACT_OWNERSHIP:
        artifact_spec = {
            "name": entry.name,
            "classification": entry.classification,
            "contains_user_content": entry.contains_user_content,
            "requires_reconnect": entry.requires_reconnect,
            "reason": entry.reason,
            "path_hint": entry.path_hint,
        }
        if entry.classification == "owned_exportable":
            owned_artifacts.append({**artifact_spec, "export_strategy": "files"})
        elif entry.classification == "reconnect_required":
            reconnect_artifacts.append(artifact_spec)
        elif entry.classification == "self_host_local":
            server_local_artifacts.append(artifact_spec)
        else:
            excluded_artifacts.append(artifact_spec)

    return {
        "schema_version": MIGRATION_CONTRACT_VERSION,
        "archive_format": ARCHIVE_FORMAT,
        "requires_same_alembic_head": True,
        "preserve_user_ids": True,
        "collision_policy": "reject",
        "secret_policy": "reconnect_or_bring_your_own",
        "owned_exportable": {
            "tables": owned_tables,
            "artifacts": owned_artifacts,
        },
        "reconnect_required": {
            "tables": reconnect_tables,
            "artifacts": reconnect_artifacts,
        },
        "server_local": {
            "tables": server_local_tables,
            "artifacts": server_local_artifacts,
        },
        "excluded": {
            "tables": excluded_tables,
            "artifacts": excluded_artifacts,
        },
    }
