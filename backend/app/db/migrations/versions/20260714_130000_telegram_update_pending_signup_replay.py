"""telegram_updates pending-signup replay payload

A brand-new Telegram user's first message (often a voice note) used to be
dropped: the webhook offered the consent button but never re-processed the
message after signup. To close that funnel leak we stash the raw update on the
idempotency row (``payload``, keyed by ``telegram_user_id``) with
``status="pending_signup"`` and replay it once the account is provisioned.

Revision ID: 20260714_130000
Revises: 20260714_120000
Create Date: 2026-07-14 13:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260714_130000"
down_revision: Union[str, tuple[str, str], None] = "20260714_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "telegram_updates",
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "telegram_updates",
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        op.f("ix_telegram_updates_telegram_user_id"),
        "telegram_updates",
        ["telegram_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_telegram_updates_telegram_user_id"),
        table_name="telegram_updates",
    )
    op.drop_column("telegram_updates", "telegram_user_id")
    op.drop_column("telegram_updates", "payload")
