"""add recording share links

Revision ID: 20260504_120000
Revises: 20260407_120000
Create Date: 2026-05-04 12:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260504_120000"
down_revision: Union[str, None] = "20260407_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recording_shares",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("recording_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
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
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_recording_shares_recording_id", "recording_shares", ["recording_id"])
    op.create_index("ix_recording_shares_revoked_at", "recording_shares", ["revoked_at"])
    op.create_index("ix_recording_shares_token_hash", "recording_shares", ["token_hash"])


def downgrade() -> None:
    op.drop_index("ix_recording_shares_token_hash", table_name="recording_shares")
    op.drop_index("ix_recording_shares_revoked_at", table_name="recording_shares")
    op.drop_index("ix_recording_shares_recording_id", table_name="recording_shares")
    op.drop_table("recording_shares")
