"""add mcp oauth state

Revision ID: 20260505_120000
Revises: 20260504_120000
Create Date: 2026-05-05 12:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260505_120000"
down_revision: Union[str, None] = "20260504_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_oauth_clients",
        sa.Column("client_id", sa.String(length=128), nullable=False),
        sa.Column("client_secret", sa.String(length=255), nullable=True),
        sa.Column("client_id_issued_at", sa.Integer(), nullable=True),
        sa.Column("client_secret_expires_at", sa.Integer(), nullable=True),
        sa.Column("redirect_uris", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("token_endpoint_auth_method", sa.String(length=64), nullable=True),
        sa.Column("grant_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("response_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("client_name", sa.String(length=255), nullable=True),
        sa.Column("client_uri", sa.String(length=1000), nullable=True),
        sa.Column("logo_uri", sa.String(length=1000), nullable=True),
        sa.Column("contacts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tos_uri", sa.String(length=1000), nullable=True),
        sa.Column("policy_uri", sa.String(length=1000), nullable=True),
        sa.Column("jwks_uri", sa.String(length=1000), nullable=True),
        sa.Column("jwks", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("software_id", sa.String(length=255), nullable=True),
        sa.Column("software_version", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("client_id"),
    )
    op.create_table(
        "mcp_oauth_authorization_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=128), nullable=False),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("code_challenge", sa.String(length=255), nullable=False),
        sa.Column("redirect_uri", sa.String(length=1000), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False),
        sa.Column("resource", sa.String(length=1000), nullable=False),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["client_id"], ["mcp_oauth_clients.client_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
    )
    op.create_index(
        "ix_mcp_oauth_authorization_requests_consumed_at",
        "mcp_oauth_authorization_requests",
        ["consumed_at"],
    )
    op.create_index(
        "ix_mcp_oauth_authorization_requests_expires_at",
        "mcp_oauth_authorization_requests",
        ["expires_at"],
    )
    op.create_index(
        "ix_mcp_oauth_authorization_requests_request_hash",
        "mcp_oauth_authorization_requests",
        ["request_hash"],
    )
    op.create_table(
        "mcp_oauth_authorization_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("code_challenge", sa.String(length=255), nullable=False),
        sa.Column("redirect_uri", sa.String(length=1000), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False),
        sa.Column("resource", sa.String(length=1000), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["client_id"], ["mcp_oauth_clients.client_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index(
        "ix_mcp_oauth_authorization_codes_code_hash",
        "mcp_oauth_authorization_codes",
        ["code_hash"],
    )
    op.create_index(
        "ix_mcp_oauth_authorization_codes_expires_at",
        "mcp_oauth_authorization_codes",
        ["expires_at"],
    )
    op.create_index(
        "ix_mcp_oauth_authorization_codes_used_at",
        "mcp_oauth_authorization_codes",
        ["used_at"],
    )
    op.create_index(
        "ix_mcp_oauth_authorization_codes_user_id",
        "mcp_oauth_authorization_codes",
        ["user_id"],
    )
    op.create_table(
        "mcp_oauth_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_type", sa.String(length=16), nullable=False),
        sa.Column("client_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resource", sa.String(length=1000), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["client_id"], ["mcp_oauth_clients.client_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_mcp_oauth_tokens_expires_at", "mcp_oauth_tokens", ["expires_at"])
    op.create_index("ix_mcp_oauth_tokens_revoked_at", "mcp_oauth_tokens", ["revoked_at"])
    op.create_index("ix_mcp_oauth_tokens_token_hash", "mcp_oauth_tokens", ["token_hash"])
    op.create_index("ix_mcp_oauth_tokens_token_type", "mcp_oauth_tokens", ["token_type"])
    op.create_index("ix_mcp_oauth_tokens_user_id", "mcp_oauth_tokens", ["user_id"])
    op.create_table(
        "mcp_oauth_consents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", sa.String(length=128), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["client_id"], ["mcp_oauth_clients.client_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "client_id", name="uq_mcp_oauth_consents_user_client"),
    )
    op.create_index("ix_mcp_oauth_consents_revoked_at", "mcp_oauth_consents", ["revoked_at"])
    op.create_index("ix_mcp_oauth_consents_user_id", "mcp_oauth_consents", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_oauth_consents_user_id", table_name="mcp_oauth_consents")
    op.drop_index("ix_mcp_oauth_consents_revoked_at", table_name="mcp_oauth_consents")
    op.drop_table("mcp_oauth_consents")
    op.drop_index("ix_mcp_oauth_tokens_user_id", table_name="mcp_oauth_tokens")
    op.drop_index("ix_mcp_oauth_tokens_token_type", table_name="mcp_oauth_tokens")
    op.drop_index("ix_mcp_oauth_tokens_token_hash", table_name="mcp_oauth_tokens")
    op.drop_index("ix_mcp_oauth_tokens_revoked_at", table_name="mcp_oauth_tokens")
    op.drop_index("ix_mcp_oauth_tokens_expires_at", table_name="mcp_oauth_tokens")
    op.drop_table("mcp_oauth_tokens")
    op.drop_index("ix_mcp_oauth_authorization_codes_user_id", table_name="mcp_oauth_authorization_codes")
    op.drop_index("ix_mcp_oauth_authorization_codes_used_at", table_name="mcp_oauth_authorization_codes")
    op.drop_index("ix_mcp_oauth_authorization_codes_expires_at", table_name="mcp_oauth_authorization_codes")
    op.drop_index("ix_mcp_oauth_authorization_codes_code_hash", table_name="mcp_oauth_authorization_codes")
    op.drop_table("mcp_oauth_authorization_codes")
    op.drop_index(
        "ix_mcp_oauth_authorization_requests_request_hash",
        table_name="mcp_oauth_authorization_requests",
    )
    op.drop_index(
        "ix_mcp_oauth_authorization_requests_expires_at",
        table_name="mcp_oauth_authorization_requests",
    )
    op.drop_index(
        "ix_mcp_oauth_authorization_requests_consumed_at",
        table_name="mcp_oauth_authorization_requests",
    )
    op.drop_table("mcp_oauth_authorization_requests")
    op.drop_table("mcp_oauth_clients")
