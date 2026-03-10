"""Add recording upload lifecycle fields.

Revision ID: 000006
Revises: 000005
Create Date: 2026-03-10

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "000006"
down_revision: Union[str, None] = "000005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recordings",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_upload"),
    )
    op.add_column("recordings", sa.Column("failure_code", sa.String(length=100), nullable=True))
    op.add_column("recordings", sa.Column("failure_message", sa.Text(), nullable=True))
    op.add_column("recordings", sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        """
        UPDATE recordings
        SET status = CASE
            WHEN audio_url IS NOT NULL THEN 'ready'
            ELSE 'pending_upload'
        END
        """
    )

    op.alter_column("recordings", "status", server_default=None)


def downgrade() -> None:
    op.drop_column("recordings", "uploaded_at")
    op.drop_column("recordings", "failure_message")
    op.drop_column("recordings", "failure_code")
    op.drop_column("recordings", "status")
