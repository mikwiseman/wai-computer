"""ComparisonSet — a side-by-side table across several Items.

The second hero output: forward several similar things (Reels, products,
papers, recipes) and get a comparison table. The LLM induces the columns from
the items themselves (schema induction), then each item's row is extracted
against those columns.

Stored compactly as JSONB:
- ``item_ids``: ordered list of the Items being compared (provenance).
- ``columns``: ``[{"name": str, "type": "text|number|boolean|category|date"}]``.
- ``rows``: ``[{"item_id": str, "title": str, "values": {col: value|null},
  "edited": bool}]`` — null means "not specified" (never fabricated).
- ``schema_rationale``: one line on why these columns (from induction).
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class ComparisonSet(Base, UUIDMixin, TimestampMixin):
    """A multi-item comparison table."""

    __tablename__ = "comparison_sets"
    __table_args__ = (
        Index("ix_comparison_sets_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(500))
    # Ordered provenance: the items being compared.
    item_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    # Induced schema + extracted rows.
    columns: Mapped[list | None] = mapped_column(JSONB)
    rows: Mapped[list | None] = mapped_column(JSONB)
    schema_rationale: Mapped[str | None] = mapped_column(Text)
    # generating -> ready | failed
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ready", server_default="ready"
    )

    user: Mapped["User"] = relationship("User")
