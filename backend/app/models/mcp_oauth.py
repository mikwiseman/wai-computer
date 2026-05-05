"""OAuth state for the remote WaiSay MCP connector."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class McpOAuthClient(Base, TimestampMixin):
    """Dynamically registered MCP OAuth client."""

    __tablename__ = "mcp_oauth_clients"

    client_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    client_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_id_issued_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_secret_expires_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    redirect_uris: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    token_endpoint_auth_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grant_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    response_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    logo_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    contacts: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    tos_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    policy_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    jwks_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    jwks: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    software_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    software_version: Mapped[str | None] = mapped_column(String(255), nullable=True)

    authorization_requests: Mapped[list["McpOAuthAuthorizationRequest"]] = relationship(
        "McpOAuthAuthorizationRequest", back_populates="client", cascade="all, delete-orphan"
    )
    authorization_codes: Mapped[list["McpOAuthAuthorizationCode"]] = relationship(
        "McpOAuthAuthorizationCode", back_populates="client", cascade="all, delete-orphan"
    )
    tokens: Mapped[list["McpOAuthToken"]] = relationship(
        "McpOAuthToken", back_populates="client", cascade="all, delete-orphan"
    )


class McpOAuthAuthorizationRequest(Base, UUIDMixin, TimestampMixin):
    """Pending browser consent request created by /authorize."""

    __tablename__ = "mcp_oauth_authorization_requests"

    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(255), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(Boolean, nullable=False)
    resource: Mapped[str] = mapped_column(String(1000), nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    client: Mapped[McpOAuthClient] = relationship(
        "McpOAuthClient", back_populates="authorization_requests"
    )


class McpOAuthAuthorizationCode(Base, UUIDMixin, TimestampMixin):
    """One-use PKCE authorization code issued after user consent."""

    __tablename__ = "mcp_oauth_authorization_codes"

    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(255), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(Boolean, nullable=False)
    resource: Mapped[str] = mapped_column(String(1000), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    client: Mapped[McpOAuthClient] = relationship(
        "McpOAuthClient", back_populates="authorization_codes"
    )
    user: Mapped["User"] = relationship("User")


class McpOAuthToken(Base, UUIDMixin, TimestampMixin):
    """Hashed access and refresh tokens for MCP OAuth clients."""

    __tablename__ = "mcp_oauth_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    token_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    resource: Mapped[str] = mapped_column(String(1000), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    client: Mapped[McpOAuthClient] = relationship("McpOAuthClient", back_populates="tokens")
    user: Mapped["User"] = relationship("User")


class McpOAuthConsent(Base, UUIDMixin, TimestampMixin):
    """Persisted per-user MCP client approval."""

    __tablename__ = "mcp_oauth_consents"
    __table_args__ = (
        UniqueConstraint("user_id", "client_id", name="uq_mcp_oauth_consents_user_client"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"), nullable=False
    )
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    client: Mapped[McpOAuthClient] = relationship("McpOAuthClient")
    user: Mapped["User"] = relationship("User")


from app.models.user import User  # noqa: E402
