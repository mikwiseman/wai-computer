"""User App models — user-created mini-apps with Collections API.

UserApp defines the app schema and metadata.
AppItem stores individual data records as JSONB.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
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
    description: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(String(10))  # emoji
    template: Mapped[str | None] = mapped_column(
        String(50)
    )  # checklist, logger, counter, board, custom
    schema_def: Mapped[dict | None] = mapped_column(JSONB)  # field definitions
    app_url: Mapped[str | None] = mapped_column(String(500))  # deployed frontend URL
    settings: Mapped[dict | None] = mapped_column(JSONB)  # app-specific config
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="private")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    items: Mapped[list["AppItem"]] = relationship(
        "AppItem", back_populates="app", cascade="all, delete-orphan"
    )
    deployments: Mapped[list["UserAppDeployment"]] = relationship(
        "UserAppDeployment",
        back_populates="app",
        cascade="all, delete-orphan",
        order_by="desc(UserAppDeployment.created_at)",
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


class UserAppDeployment(Base, UUIDMixin, TimestampMixin):
    """A historical deployment event for a generated user app."""

    __tablename__ = "user_app_deployments"

    user_app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_apps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_deployment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_app_deployments.id", ondelete="SET NULL"),
        nullable=True,
    )
    deployment_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    deployment_target: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="cloudflare-pages",
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="succeeded")
    generated_slug: Mapped[str] = mapped_column(String(120), nullable=False)
    bundle_cache_key: Mapped[str] = mapped_column(String(180), nullable=False)
    cloudflare_project_name: Mapped[str | None] = mapped_column(String(100))
    deployment_url: Mapped[str | None] = mapped_column(String(500))
    alias_url: Mapped[str | None] = mapped_column(String(500))
    live_url: Mapped[str | None] = mapped_column(String(500))
    bundle_kind: Mapped[str | None] = mapped_column(String(50))
    framework: Mapped[str | None] = mapped_column(String(50))
    generation_provider: Mapped[str | None] = mapped_column(String(50))
    build_output_dir: Mapped[str | None] = mapped_column(String(120))
    build_command: Mapped[str | None] = mapped_column(Text)

    app: Mapped["UserApp"] = relationship("UserApp", back_populates="deployments")
    source_deployment: Mapped["UserAppDeployment | None"] = relationship(
        "UserAppDeployment",
        remote_side="UserAppDeployment.id",
    )

    __table_args__ = (
        Index(
            "ix_user_app_deployments_app_created",
            "user_app_id",
            "created_at",
        ),
    )
