"""Add recording folders and trash support.

Revision ID: 000002
Revises: 000001
Create Date: 2026-03-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "000002"
down_revision: Union[str, None] = "000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "folders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_folders_user_id", "folders", ["user_id"])

    op.add_column("recordings", sa.Column("folder_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("recordings", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_recordings_folder_id", "recordings", ["folder_id"])
    op.create_index("ix_recordings_deleted_at", "recordings", ["deleted_at"])
    op.create_foreign_key(
        "fk_recordings_folder_id_folders",
        "recordings",
        "folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_recordings_folder_id_folders", "recordings", type_="foreignkey")
    op.drop_index("ix_recordings_deleted_at", table_name="recordings")
    op.drop_index("ix_recordings_folder_id", table_name="recordings")
    op.drop_column("recordings", "deleted_at")
    op.drop_column("recordings", "folder_id")

    op.drop_index("ix_folders_user_id", table_name="folders")
    op.drop_table("folders")
