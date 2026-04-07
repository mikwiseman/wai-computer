"""drop agents and chat tables

Revision ID: 20260407_120000
Revises: 20260406_120000
Create Date: 2026-04-07 12:00:00.000000+00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260407_120000"
down_revision: Union[str, None] = "20260406_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("digital_agents")


def downgrade() -> None:
    raise NotImplementedError("Downgrade for feature removal not supported")
