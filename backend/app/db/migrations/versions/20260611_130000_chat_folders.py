"""Add folder_id to conversations so Wai chats can be filed into folders.

Recordings and materials already carry a folder assignment; chats were the
one inbox kind that couldn't be dragged into a folder. The inbox folder
scope, folder counts, and sidebar drag-and-drop all rely on this column.

Revision ID: 20260611_130000
Revises: 20260611_120000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260611_130000"
down_revision: Union[str, tuple[str, str], None] = "20260611_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("folder_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_conversations_folder_id_folders",
        "conversations",
        "folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_conversations_folder_id", "conversations", ["folder_id"])


def downgrade() -> None:
    op.drop_index("ix_conversations_folder_id", table_name="conversations")
    op.drop_constraint(
        "fk_conversations_folder_id_folders", "conversations", type_="foreignkey"
    )
    op.drop_column("conversations", "folder_id")
