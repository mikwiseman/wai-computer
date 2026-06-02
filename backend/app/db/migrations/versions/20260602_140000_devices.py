"""devices (Mac-edge channel presence)

Revision ID: 20260602_140000
Revises: 20260602_120000
Create Date: 2026-06-02 14:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260602_140000"
down_revision: Union[str, None] = "20260602_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "user_id", "platform", "name", name="uq_devices_user_platform_name"
        ),
    )
    op.create_index("ix_devices_user_id", "devices", ["user_id"])
    op.create_index("ix_devices_last_seen_at", "devices", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_devices_last_seen_at", table_name="devices")
    op.drop_index("ix_devices_user_id", table_name="devices")
    op.drop_table("devices")
