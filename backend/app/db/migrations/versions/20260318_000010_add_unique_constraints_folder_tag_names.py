"""Add unique constraints on folder and tag names per user

Revision ID: 000010
Revises: 000009
Create Date: 2026-03-18

Adds:
- UNIQUE(user_id, name) on folders table
- UNIQUE(user_id, name) on tags table

Handles existing duplicates by appending a numeric suffix before creating the constraint.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "000010"
down_revision: Union[str, None] = "000009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _deduplicate_names(table: str, order_col: str = "created_at") -> None:
    """Rename duplicate (user_id, name) rows by appending ' (2)', ' (3)', etc.

    Uses a CTE with ROW_NUMBER() to find duplicates and updates only the rows
    where row_num > 1 (i.e., the second, third, ... occurrence).
    """
    op.execute(f"""
        WITH numbered AS (
            SELECT id,
                   name,
                   ROW_NUMBER() OVER (
                       PARTITION BY user_id, LOWER(name)
                       ORDER BY {order_col}
                   ) AS row_num
            FROM {table}
        )
        UPDATE {table}
        SET name = {table}.name || ' (' || numbered.row_num || ')'
        FROM numbered
        WHERE {table}.id = numbered.id
          AND numbered.row_num > 1
    """)


def upgrade() -> None:
    # Deduplicate any existing rows before adding the constraint
    _deduplicate_names("folders", order_col="created_at")
    _deduplicate_names("tags", order_col="id")

    op.create_unique_constraint("uq_folders_user_id_name", "folders", ["user_id", "name"])
    op.create_unique_constraint("uq_tags_user_id_name", "tags", ["user_id", "name"])


def downgrade() -> None:
    op.drop_constraint("uq_tags_user_id_name", "tags", type_="unique")
    op.drop_constraint("uq_folders_user_id_name", "folders", type_="unique")
