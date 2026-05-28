"""add user identity fields (first_name, last_name, self_person_id)

Revision ID: 20260528_140000
Revises: 20260528_120000
Create Date: 2026-05-28 14:00:00.000000+00:00

Adds a per-user public-identity surface used by the upcoming voice-sharing
directory:
- first_name, last_name: shown to other WaiComputer users in their recordings
  when this user opts into the directory. Nullable so existing accounts stay
  valid until the user fills them in via Settings.
- self_person_id: pointer to the user's own Person row in their address book,
  set automatically on the first voice enrollment. Lets the directory pick
  the canonical voiceprint without guessing by display_name.
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260528_140000"
down_revision: Union[str, None] = "20260528_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("first_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("last_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "self_person_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("people.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "self_person_id")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
