"""User App models — user-created mini-apps with Collections API.

UserApp defines the app schema and metadata.
AppItem stores individual data records as JSONB.
"""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class UserApp(Base, UUIDMixin, TimestampMixin):
    """A user-created mini-app (collection) with a defined schema."""

    __tablename__ = "user_apps"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # slug: "habits", "expenses"
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(10))  # emoji
    template: Mapped[str | None] = mapped_column(
        String(50)
    )  # checklist, logger, counter, board, custom
    schema_def: Mapped[dict | None] = mapped_column(JSONB)  # field definitions
    app_url: Mapped[str | None] = mapped_column(String(500))  # deployed frontend URL
    settings: Mapped[dict | None] = mapped_column(JSONB)  # app-specific config
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    items: Mapped[list["AppItem"]] = relationship(
        "AppItem", back_populates="app", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_user_apps_user_name", "user_id", "name", unique=True),)


class AppItem(Base, UUIDMixin, TimestampMixin):
    """An individual data record within a user app."""

    __tablename__ = "app_items"

    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_apps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))

    # Relationships
    app: Mapped["UserApp"] = relationship("UserApp", back_populates="items")

    __table_args__ = (Index("ix_app_items_data", "data", postgresql_using="gin"),)
