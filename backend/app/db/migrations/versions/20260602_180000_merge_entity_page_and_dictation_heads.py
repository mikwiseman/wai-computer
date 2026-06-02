"""merge entity page snapshots and dictation cleanup heads

Revision ID: 20260602_180000
Revises: 20260602_160000, 20260602_170000
Create Date: 2026-06-02 18:00:00.000000
"""

from typing import Sequence, Union

revision: str = "20260602_180000"
down_revision: Union[str, tuple[str, str], None] = (
    "20260602_160000",
    "20260602_170000",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
