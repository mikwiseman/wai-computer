"""WaiBrain Spaces: shareable canonical mini-brains.

Spaces are the product-level container for "palaces" in the Brain: Personal,
Work, Wai School, or a shared partnership/project. The canonical human-readable
body is Markdown stored in ``brain_pages``; typed ``brain_claims`` index the
parts that governance/retrieval need to query.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class BrainSpace(Base, UUIDMixin, TimestampMixin):
    """A coherent, shareable mini-brain owned by one user."""

    __tablename__ = "brain_spaces"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("owner_user_id", "slug", name="uq_brain_spaces_owner_slug"),
        Index("ix_brain_spaces_owner", "owner_user_id"),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(40), nullable=False, default="personal", server_default="personal"
    )
    engine_profile: Mapped[str] = mapped_column(
        String(40), nullable=False, default="waibrain", server_default="waibrain"
    )
    visibility: Mapped[str] = mapped_column(
        String(40), nullable=False, default="private", server_default="private"
    )
    description: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)

    owner: Mapped["User"] = relationship("User")
    members: Mapped[list["BrainSpaceMember"]] = relationship(
        "BrainSpaceMember",
        back_populates="space",
        cascade="all, delete-orphan",
    )
    pages: Mapped[list["BrainPage"]] = relationship(
        "BrainPage",
        back_populates="space",
        cascade="all, delete-orphan",
    )


class BrainSpaceMember(Base, UUIDMixin, TimestampMixin):
    """Membership in a shared Space."""

    __tablename__ = "brain_space_members"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("space_id", "user_id", name="uq_brain_space_members_space_user"),
        Index("ix_brain_space_members_user", "user_id"),
        Index("ix_brain_space_members_space_role", "space_id", "role"),
    )

    space_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("brain_spaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="viewer", server_default="viewer"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    space: Mapped["BrainSpace"] = relationship("BrainSpace", back_populates="members")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])


class BrainSpaceSource(Base, UUIDMixin, TimestampMixin):
    """A source explicitly linked into a Space."""

    __tablename__ = "brain_space_sources"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint(
            "space_id",
            "source_kind",
            "source_id",
            name="uq_brain_space_sources_space_source",
        ),
        Index("ix_brain_space_sources_space", "space_id"),
        Index("ix_brain_space_sources_source", "source_kind", "source_id"),
    )

    space_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("brain_spaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    added_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_title: Mapped[str | None] = mapped_column(String(500))
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)


class BrainPage(Base, UUIDMixin, TimestampMixin):
    """A canonical Markdown page inside a Space."""

    __tablename__ = "brain_pages"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("space_id", "slug", name="uq_brain_pages_space_slug"),
        Index("ix_brain_pages_space_kind", "space_id", "kind"),
        Index("ix_brain_pages_space_status", "space_id", "status"),
    )

    space_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("brain_spaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    slug: Mapped[str] = mapped_column(String(320), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(40), nullable=False, default="note", server_default="note"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    frontmatter: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    space: Mapped["BrainSpace"] = relationship("BrainSpace", back_populates="pages")
    claims: Mapped[list["BrainClaim"]] = relationship(
        "BrainClaim",
        back_populates="page",
        cascade="all, delete-orphan",
    )


class BrainClaim(Base, UUIDMixin, TimestampMixin):
    """Structured index entry for canonical evaluated Brain knowledge."""

    __tablename__ = "brain_claims"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("space_id", "dedup_key", name="uq_brain_claims_space_dedup"),
        Index("ix_brain_claims_space_kind_status", "space_id", "kind", "status"),
        Index("ix_brain_claims_page", "page_id"),
    )

    space_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("brain_spaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("brain_pages.id", ondelete="SET NULL"),
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5, server_default="0.5"
    )
    authority: Mapped[str] = mapped_column(
        String(40), nullable=False, default="self", server_default="self"
    )
    salience: Mapped[float | None] = mapped_column(Float)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False)
    source_refs: Mapped[list | None] = mapped_column(JSONB)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("brain_claims.id", ondelete="SET NULL"),
    )

    page: Mapped["BrainPage | None"] = relationship("BrainPage", back_populates="claims")


class BrainReviewPack(Base, UUIDMixin, TimestampMixin):
    """Grouped AI proposal for a Space owner to accept or reject."""

    __tablename__ = "brain_review_packs"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        Index("ix_brain_review_packs_space_status", "space_id", "status"),
        Index("ix_brain_review_packs_space_created", "space_id", "created_at"),
    )

    space_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("brain_spaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(
        String(40), nullable=False, default="bridge", server_default="bridge"
    )
    risk: Mapped[str] = mapped_column(
        String(20), nullable=False, default="medium", server_default="medium"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    proposals: Mapped[list] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[list | None] = mapped_column(JSONB)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
