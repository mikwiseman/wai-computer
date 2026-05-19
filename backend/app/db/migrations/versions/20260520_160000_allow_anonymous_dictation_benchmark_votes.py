"""allow anonymous dictation benchmark votes

Revision ID: 20260520_160000
Revises: 20260520_150000
Create Date: 2026-05-20 16:00:00.000000+00:00
"""

from typing import Sequence, Union  # noqa: F401

from alembic import op

revision: str = "20260520_160000"
down_revision: Union[str, None] = "20260520_150000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("dictation_benchmark_votes", "user_id", nullable=True)


def downgrade() -> None:
    op.alter_column("dictation_benchmark_votes", "user_id", nullable=False)
