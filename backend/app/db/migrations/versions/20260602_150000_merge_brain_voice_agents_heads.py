"""merge brain + voice/agents migration heads

Revision ID: 20260602_150000
Revises: 20260602_110000, 20260602_140000
Create Date: 2026-06-02 08:46:58.360859+00:00

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "20260602_150000"
down_revision: Union[str, None] = ("20260602_110000", "20260602_140000")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
