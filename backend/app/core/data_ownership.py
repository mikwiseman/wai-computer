"""Data ownership registry for cloud export and self-host migration.

This registry is intentionally explicit. A new durable table or file artifact
must be classified here before it can ship, otherwise the tests fail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OwnershipClassification = Literal[
    "owned_exportable",
    "self_host_local",
    "hosted_control_plane",
    "reconnect_required",
    "excluded_with_reason",
]

OWNERSHIP_CLASSIFICATIONS = {
    "owned_exportable",
    "self_host_local",
    "hosted_control_plane",
    "reconnect_required",
    "excluded_with_reason",
}


@dataclass(frozen=True)
class DataOwnershipEntry:
    name: str
    classification: OwnershipClassification
    reason: str
    contains_user_content: bool = False
    requires_reconnect: bool = False


@dataclass(frozen=True)
class TableOwnershipEntry(DataOwnershipEntry):
    table: str = ""

    def __post_init__(self) -> None:
        if not self.table:
            object.__setattr__(self, "table", self.name)


@dataclass(frozen=True)
class ArtifactOwnershipEntry(DataOwnershipEntry):
    path_hint: str | None = None


DATA_OWNERSHIP: tuple[TableOwnershipEntry, ...] = (
    TableOwnershipEntry(
        "users",
        "owned_exportable",
        "Account profile, legal acceptance, language, transcription, and UI preferences.",
    ),
    TableOwnershipEntry(
        "devices",
        "owned_exportable",
        "User device registrations and desktop action routing metadata.",
    ),
    TableOwnershipEntry(
        "refresh_tokens",
        "reconnect_required",
        "Session tokens are hash-only and must be recreated on the destination.",
        requires_reconnect=True,
    ),
    TableOwnershipEntry(
        "api_keys",
        "reconnect_required",
        "Personal API tokens are hash-only; export metadata and require regeneration.",
        requires_reconnect=True,
    ),
    TableOwnershipEntry("folders", "owned_exportable", "User recording organization."),
    TableOwnershipEntry(
        "recordings",
        "owned_exportable",
        "Recording metadata and lifecycle state.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "segments",
        "owned_exportable",
        "Transcript segments and embeddings.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "summaries",
        "owned_exportable",
        "AI-generated recording summaries.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "summary_generation_jobs", "owned_exportable", "Durable summary job state."
    ),
    TableOwnershipEntry(
        "summary_audio_artifacts",
        "owned_exportable",
        "Generated summary-audio metadata and file references.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "action_items",
        "owned_exportable",
        "Generated and user-managed action items.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "highlights",
        "owned_exportable",
        "Generated recording highlights.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "recording_shares",
        "reconnect_required",
        "Share token hashes can move as metadata, but public links should be reissued per server.",
        requires_reconnect=True,
    ),
    TableOwnershipEntry("tags", "owned_exportable", "User tags."),
    TableOwnershipEntry("recording_tags", "owned_exportable", "Recording/tag associations."),
    TableOwnershipEntry(
        "people", "owned_exportable", "User speaker/person profiles.", contains_user_content=True
    ),
    TableOwnershipEntry("voiceprints", "owned_exportable", "Voice embeddings owned by the user."),
    TableOwnershipEntry(
        "recording_speaker_embeddings", "owned_exportable", "Per-recording speaker embeddings."
    ),
    TableOwnershipEntry(
        "public_voiceprints",
        "excluded_with_reason",
        "Global voice-sharing directory state is not imported to a private self-host server.",
    ),
    TableOwnershipEntry(
        "dictation_entries", "owned_exportable", "Dictation history.", contains_user_content=True
    ),
    TableOwnershipEntry(
        "dictation_dictionary_words", "owned_exportable", "User dictation dictionary."
    ),
    TableOwnershipEntry(
        "dictation_snippets",
        "owned_exportable",
        "User dictation snippets (voice-triggered text expansions).",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "personalization_import_jobs",
        "owned_exportable",
        "Personalization import metadata and source text.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "personalization_terms",
        "owned_exportable",
        "User spelling and vocabulary preferences.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "memory_proposals",
        "owned_exportable",
        "Pending memory edits and evidence.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "user_memory_blocks",
        "owned_exportable",
        "Long-term user memory blocks.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "user_memory_log", "owned_exportable", "Memory change history.", contains_user_content=True
    ),
    TableOwnershipEntry(
        "user_reminders",
        "owned_exportable",
        "User scheduled reminders and delivery metadata.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "entities",
        "owned_exportable",
        "User brain entities and embeddings.",
        contains_user_content=True,
    ),
    TableOwnershipEntry("entity_relations", "owned_exportable", "User brain graph relations."),
    TableOwnershipEntry(
        "entity_facts",
        "owned_exportable",
        "Bi-temporal asserted facts about the user's entities.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "entity_mentions",
        "owned_exportable",
        "Entity mentions linked to user content.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "entity_page_snapshots",
        "owned_exportable",
        "Generated entity wiki snapshots.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "items",
        "owned_exportable",
        "Second-brain items, source refs, bodies, and embeddings.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "item_chunks",
        "owned_exportable",
        "Item chunk text and embeddings.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "item_summaries",
        "owned_exportable",
        "Item summaries and extracted structure.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "comparison_sets",
        "owned_exportable",
        "User comparison workspaces.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "brain_spaces",
        "owned_exportable",
        "User-owned WaiBrain Space containers and descriptions.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "brain_space_members",
        "owned_exportable",
        "Space membership and collaboration metadata.",
    ),
    TableOwnershipEntry(
        "brain_space_sources",
        "owned_exportable",
        "Sources linked into user-owned WaiBrain Spaces.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "brain_pages",
        "owned_exportable",
        "Canonical Markdown pages inside WaiBrain Spaces.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "brain_claims",
        "owned_exportable",
        "Structured claims extracted into WaiBrain Spaces.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "brain_review_packs",
        "owned_exportable",
        "Review packs for accepting shared WaiBrain knowledge.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "brain_maps",
        "owned_exportable",
        "Saved Brain Map prompts, layout preferences, and source scopes.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "brain_map_revisions",
        "owned_exportable",
        "Generated Brain Map projections, citations, diffs, and freshness metadata.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "commitments", "owned_exportable", "Tracked commitments.", contains_user_content=True
    ),
    TableOwnershipEntry(
        "conversations", "owned_exportable", "Companion chat sessions.", contains_user_content=True
    ),
    TableOwnershipEntry(
        "chat_messages",
        "owned_exportable",
        "Companion chat messages and tool calls.",
        contains_user_content=True,
    ),
    TableOwnershipEntry("message_citations", "owned_exportable", "Companion citation links."),
    TableOwnershipEntry(
        "conversation_chunks",
        "owned_exportable",
        "Embedded chat chunks that make conversations searchable in the Brain.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "companion_pending_actions",
        "owned_exportable",
        "User-approved or pending desktop actions.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "agents",
        "owned_exportable",
        "User agent definitions.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "agent_runs",
        "owned_exportable",
        "Agent execution metadata.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "agent_steps",
        "owned_exportable",
        "Agent step metadata and results.",
        contains_user_content=True,
    ),
    TableOwnershipEntry(
        "mcp_oauth_clients",
        "self_host_local",
        "MCP OAuth dynamic client registrations are server-local.",
    ),
    TableOwnershipEntry(
        "mcp_oauth_authorization_requests",
        "self_host_local",
        "Short-lived OAuth authorization state is server-local.",
    ),
    TableOwnershipEntry(
        "mcp_oauth_authorization_codes",
        "self_host_local",
        "Short-lived OAuth codes are server-local.",
    ),
    TableOwnershipEntry(
        "mcp_oauth_tokens",
        "reconnect_required",
        "MCP OAuth token hashes are server-bound and must be reissued.",
        requires_reconnect=True,
    ),
    TableOwnershipEntry(
        "mcp_oauth_consents",
        "owned_exportable",
        "User client consent metadata; clients must reconnect to the new issuer.",
        requires_reconnect=True,
    ),
    TableOwnershipEntry(
        "telegram_accounts",
        "owned_exportable",
        "Linked Telegram account metadata; the destination server must reconnect its bot.",
        contains_user_content=True,
        requires_reconnect=True,
    ),
    TableOwnershipEntry(
        "telegram_pairings",
        "self_host_local",
        "Short-lived Telegram pairing state is server-local.",
    ),
    TableOwnershipEntry(
        "telegram_bot_link_codes",
        "self_host_local",
        "Short-lived Telegram bot link codes are server-local.",
    ),
    TableOwnershipEntry(
        "telegram_updates",
        "self_host_local",
        "Telegram webhook idempotency ledger is local to the receiving server.",
    ),
    TableOwnershipEntry(
        "dictation_benchmark_votes", "owned_exportable", "User benchmark vote metadata."
    ),
    TableOwnershipEntry(
        "deepgram_usage_events",
        "owned_exportable",
        "Provider usage ledger without raw user content.",
    ),
    TableOwnershipEntry(
        "ai_usage_events", "owned_exportable", "AI/model usage ledger without raw user content."
    ),
    TableOwnershipEntry("billing_usage_weeks", "owned_exportable", "User usage counters."),
    TableOwnershipEntry(
        "billing_subscriptions",
        "owned_exportable",
        "Read-only subscription history; provider billing is not reactivated on self-host.",
    ),
    TableOwnershipEntry("billing_invoices", "owned_exportable", "Read-only invoice history."),
    TableOwnershipEntry("billing_events", "owned_exportable", "Read-only billing event history."),
    TableOwnershipEntry(
        "billing_promo_redemptions", "owned_exportable", "Read-only promo redemption history."
    ),
    TableOwnershipEntry(
        "billing_plans",
        "hosted_control_plane",
        "Pricing catalog is Wai Cloud configuration, not user-owned app data.",
    ),
    TableOwnershipEntry(
        "billing_promo_codes",
        "hosted_control_plane",
        "Promo-code inventory is Wai Cloud control-plane data.",
    ),
    TableOwnershipEntry(
        "staff_members",
        "excluded_with_reason",
        "Wai staff profiles are not user-owned and are not imported to self-host.",
    ),
    TableOwnershipEntry(
        "admin_roles",
        "excluded_with_reason",
        "Wai staff roles are not imported; self-host creates its own owner/admin.",
    ),
    TableOwnershipEntry(
        "admin_audit_logs",
        "hosted_control_plane",
        "Cloud operator audit logs stay with the cloud service; "
        "self-host creates local audit logs.",
    ),
)

ARTIFACT_OWNERSHIP: tuple[ArtifactOwnershipEntry, ...] = (
    ArtifactOwnershipEntry(
        "document_uploads",
        "owned_exportable",
        "Original document uploads stored in item metadata must move with the user's data.",
        contains_user_content=True,
        path_hint="${UPLOAD_STAGING_DIR}/items/<user_id>/*",
    ),
    ArtifactOwnershipEntry(
        "summary_audio_files",
        "owned_exportable",
        "Generated MP3 files for recording and item summaries are user-owned exports.",
        contains_user_content=True,
        path_hint="${SUMMARY_AUDIO_STORAGE_DIR}/<user_id>/*.mp3",
    ),
    ArtifactOwnershipEntry(
        "recording_audio_staging",
        "self_host_local",
        "Temporary audio upload input is deleted after processing and is not retained by default.",
        contains_user_content=True,
        path_hint="${UPLOAD_STAGING_DIR}/<user_id>/*",
    ),
    ArtifactOwnershipEntry(
        "media_upload_staging",
        "self_host_local",
        "Temporary audio/video import input is deleted after processing "
        "and is not retained by default.",
        contains_user_content=True,
        path_hint="${UPLOAD_STAGING_DIR}/items/<user_id>/*",
    ),
    ArtifactOwnershipEntry(
        "migration_archives",
        "owned_exportable",
        "Encrypted export archives are user-owned and downloadable.",
        contains_user_content=True,
    ),
    ArtifactOwnershipEntry(
        "self_host_backups",
        "owned_exportable",
        "Self-host database and file backups belong to the server owner.",
        contains_user_content=True,
    ),
    ArtifactOwnershipEntry(
        "speechbrain_cache",
        "self_host_local",
        "Downloaded model cache is operational state and can be rebuilt.",
        path_hint="speechbrain_cache",
    ),
    ArtifactOwnershipEntry(
        "caddy_data",
        "self_host_local",
        "TLS certificates and ACME account material are local server operational state.",
        path_hint="caddy_data",
    ),
    ArtifactOwnershipEntry(
        "telegram_bot_api_data",
        "self_host_local",
        "Telegram Bot API cache is local operational state and can be rebuilt.",
        path_hint="telegram_bot_api_data",
    ),
)


def table_ownership_by_name() -> dict[str, TableOwnershipEntry]:
    return {entry.table: entry for entry in DATA_OWNERSHIP}


def _entry_dict(entry: DataOwnershipEntry) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": entry.name,
        "classification": entry.classification,
        "reason": entry.reason,
        "contains_user_content": entry.contains_user_content,
        "requires_reconnect": entry.requires_reconnect,
    }
    if isinstance(entry, TableOwnershipEntry):
        payload["table"] = entry.table
    if isinstance(entry, ArtifactOwnershipEntry):
        payload["path_hint"] = entry.path_hint
    return payload


def ownership_map_response() -> dict[str, object]:
    """Return the public data map shown in Settings and used by migration preflight."""
    return {
        "audio_retention_policy": "delete_after_processing",
        "tables": [_entry_dict(entry) for entry in DATA_OWNERSHIP],
        "artifacts": [_entry_dict(entry) for entry in ARTIFACT_OWNERSHIP],
    }
