"""OAuth 2.1 provider for the remote WaiComputer MCP server."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import AsyncContextManager
from urllib.parse import ParseResult, urlencode, urlparse, urlunparse
from uuid import UUID

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    OAuthClientInformationFull,
    OAuthToken,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.api_keys import is_api_key, resolve_api_key
from app.db.session import get_db_context
from app.models.mcp_oauth import (
    McpOAuthAuthorizationCode,
    McpOAuthAuthorizationRequest,
    McpOAuthClient,
    McpOAuthConsent,
    McpOAuthToken,
)

MCP_READ_SCOPE = "mcp:read"
MCP_SCOPES = [MCP_READ_SCOPE]
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"
McpDbContextFactory = Callable[[], AsyncContextManager[AsyncSession]]
_mcp_db_context_override: ContextVar[McpDbContextFactory | None] = ContextVar(
    "mcp_db_context_override",
    default=None,
)


class McpAuthorizationRequestError(Exception):
    """Raised when a browser consent request is invalid or expired."""


@dataclass(frozen=True)
class McpAuthorizationRequestView:
    """Safe view model for rendering the consent page."""

    request_token: str
    csrf_token: str
    client_name: str
    client_uri: str | None
    redirect_uri: str
    scopes: list[str]
    expires_at: datetime


def token_hash(token: str) -> str:
    """Hash an OAuth token for storage and lookup."""
    return hashlib.sha256(token.encode()).hexdigest()


def override_mcp_db_context(factory: McpDbContextFactory) -> Token[McpDbContextFactory | None]:
    """Override the MCP DB context, used by integration tests."""
    return _mcp_db_context_override.set(factory)


def reset_mcp_db_context(token: Token[McpDbContextFactory | None]) -> None:
    """Reset a previously installed MCP DB context override."""
    _mcp_db_context_override.reset(token)


def _mcp_db_context() -> AsyncContextManager[AsyncSession]:
    override = _mcp_db_context_override.get()
    if override is not None:
        return override()
    return get_db_context()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expires_in_seconds(value: datetime) -> int:
    return max(0, int((value - _now()).total_seconds()))


def _as_timestamp(value: datetime) -> int:
    return int(value.timestamp())


def _scope_list(
    scopes: list[str] | None,
    client: OAuthClientInformationFull | None = None,
) -> list[str]:
    if scopes:
        requested = scopes
    elif client and client.scope:
        requested = client.scope.split()
    else:
        requested = [MCP_READ_SCOPE]

    invalid = sorted(set(requested) - set(MCP_SCOPES))
    if invalid:
        raise AuthorizeError("invalid_scope", f"Unsupported MCP scope: {' '.join(invalid)}")
    return requested


def _redirect_uri(base: str, **params: str | None) -> str:
    parsed = urlparse(base)
    existing = parsed.query
    query = urlencode({key: value for key, value in params.items() if value is not None})
    combined = "&".join(part for part in [existing, query] if part)
    return urlunparse(parsed._replace(query=combined))


def _resource_parts(value: str) -> ParseResult | None:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc or parsed.params or parsed.query or parsed.fragment:
        return None
    return parsed


def resource_matches(value: str | None) -> bool:
    """Validate an OAuth resource indicator against the canonical MCP URL."""
    if not value:
        return False

    expected = _resource_parts(get_settings().mcp_resource_url_resolved)
    actual = _resource_parts(value)
    if expected is None or actual is None:
        return False

    return (
        actual.scheme.lower() == expected.scheme.lower()
        and actual.netloc.lower() == expected.netloc.lower()
        and actual.path.rstrip("/") == expected.path.rstrip("/")
    )


def _client_from_model(client: McpOAuthClient) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client.client_id,
        client_secret=client.client_secret,
        client_id_issued_at=client.client_id_issued_at,
        client_secret_expires_at=client.client_secret_expires_at,
        redirect_uris=client.redirect_uris,
        token_endpoint_auth_method=client.token_endpoint_auth_method,
        grant_types=client.grant_types,
        response_types=client.response_types,
        scope=client.scope,
        client_name=client.client_name,
        client_uri=client.client_uri,
        logo_uri=client.logo_uri,
        contacts=client.contacts,
        tos_uri=client.tos_uri,
        policy_uri=client.policy_uri,
        jwks_uri=client.jwks_uri,
        jwks=client.jwks,
        software_id=client.software_id,
        software_version=client.software_version,
    )


def _validate_redirect_uris(client_info: OAuthClientInformationFull) -> None:
    for redirect_uri in client_info.redirect_uris or []:
        parsed = urlparse(str(redirect_uri))
        is_loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme == "https":
            continue
        if parsed.scheme == "http" and is_loopback:
            continue
        raise RegistrationError(
            "invalid_redirect_uri",
            "redirect_uris must use https, except localhost loopback callbacks",
        )


async def _load_pending_request(
    db: AsyncSession,
    request_token: str,
) -> McpOAuthAuthorizationRequest | None:
    result = await db.execute(
        select(McpOAuthAuthorizationRequest).where(
            McpOAuthAuthorizationRequest.request_hash == token_hash(request_token),
            McpOAuthAuthorizationRequest.consumed_at.is_(None),
            McpOAuthAuthorizationRequest.expires_at > _now(),
        )
        .options(selectinload(McpOAuthAuthorizationRequest.client))
    )
    return result.scalar_one_or_none()


async def _find_active_consent(
    db: AsyncSession,
    user_id: UUID,
    client_id: str,
    scopes: list[str],
) -> McpOAuthConsent | None:
    result = await db.execute(
        select(McpOAuthConsent).where(
            McpOAuthConsent.user_id == user_id,
            McpOAuthConsent.client_id == client_id,
            McpOAuthConsent.revoked_at.is_(None),
        )
    )
    consent = result.scalar_one_or_none()
    if consent is None:
        return None
    if not set(scopes).issubset(set(consent.scopes)):
        return None
    return consent


async def load_authorization_request_view(
    db: AsyncSession,
    request_token: str,
) -> McpAuthorizationRequestView:
    request = await _load_pending_request(db, request_token)
    if request is None:
        raise McpAuthorizationRequestError("Authorization request is invalid or expired")
    return McpAuthorizationRequestView(
        request_token=request_token,
        csrf_token=request.csrf_token,
        client_name=request.client.client_name or "MCP client",
        client_uri=request.client.client_uri,
        redirect_uri=request.redirect_uri,
        scopes=request.scopes,
        expires_at=request.expires_at,
    )


async def complete_authorization_request(
    db: AsyncSession,
    request_token: str,
    user_id: UUID,
    *,
    csrf_token: str | None,
    approved: bool,
    require_csrf: bool = True,
) -> str:
    """Complete a pending browser consent request and return the OAuth redirect URI."""
    request = await _load_pending_request(db, request_token)
    if request is None:
        raise McpAuthorizationRequestError("Authorization request is invalid or expired")

    csrf_invalid = not csrf_token or not secrets.compare_digest(request.csrf_token, csrf_token)
    if require_csrf and csrf_invalid:
        raise McpAuthorizationRequestError("Authorization request failed CSRF validation")

    request.consumed_at = _now()
    if not approved:
        await db.flush()
        return _redirect_uri(request.redirect_uri, error="access_denied", state=request.state)

    consent = await _find_active_consent(db, user_id, request.client_id, request.scopes)
    if consent is None:
        consent = McpOAuthConsent(
            user_id=user_id,
            client_id=request.client_id,
            scopes=request.scopes,
            approved_at=_now(),
        )
        db.add(consent)
    else:
        consent.approved_at = _now()

    settings = get_settings()
    code = secrets.token_urlsafe(48)
    db.add(
        McpOAuthAuthorizationCode(
            code_hash=token_hash(code),
            client_id=request.client_id,
            user_id=user_id,
            scopes=request.scopes,
            code_challenge=request.code_challenge,
            redirect_uri=request.redirect_uri,
            redirect_uri_provided_explicitly=request.redirect_uri_provided_explicitly,
            resource=request.resource,
            expires_at=_now() + timedelta(minutes=settings.mcp_authorization_code_expire_minutes),
        )
    )
    await db.flush()
    return _redirect_uri(request.redirect_uri, code=code, state=request.state)


async def auto_complete_authorization_if_consented(
    db: AsyncSession,
    request_token: str,
    user_id: UUID,
) -> str | None:
    """Return an OAuth redirect URI when a user already approved this client/scope set."""
    request = await _load_pending_request(db, request_token)
    if request is None:
        raise McpAuthorizationRequestError("Authorization request is invalid or expired")
    consent = await _find_active_consent(db, user_id, request.client_id, request.scopes)
    if consent is None:
        return None
    return await complete_authorization_request(
        db,
        request_token,
        user_id,
        csrf_token=None,
        approved=True,
        require_csrf=False,
    )


async def resolve_mcp_access_token_user_id(token: str) -> UUID | None:
    """Resolve a valid MCP access token (OAuth token or wc_live_ API key) to the user id."""
    async with _mcp_db_context() as db:
        if is_api_key(token):
            api_key = await resolve_api_key(db, token)
            return api_key.user_id if api_key else None
        result = await db.execute(
            select(McpOAuthToken).where(
                McpOAuthToken.token_hash == token_hash(token),
                McpOAuthToken.token_type == ACCESS_TOKEN_TYPE,
                McpOAuthToken.revoked_at.is_(None),
                McpOAuthToken.expires_at > _now(),
            )
        )
        db_token = result.scalar_one_or_none()
        if db_token is None or not resource_matches(db_token.resource):
            return None
        return db_token.user_id


class WaiComputerMcpOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """FastMCP-compatible authorization server backed by WaiComputer's database."""

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with _mcp_db_context() as db:
            result = await db.execute(
                select(McpOAuthClient).where(McpOAuthClient.client_id == client_id)
            )
            client = result.scalar_one_or_none()
            if client is None:
                return None
            secret_expired = (
                client.client_secret_expires_at
                and client.client_secret_expires_at < int(time.time())
            )
            if secret_expired:
                return None
            return _client_from_model(client)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        _validate_redirect_uris(client_info)
        async with _mcp_db_context() as db:
            db.add(
                McpOAuthClient(
                    client_id=client_info.client_id or secrets.token_urlsafe(32),
                    client_secret=client_info.client_secret,
                    client_id_issued_at=client_info.client_id_issued_at,
                    client_secret_expires_at=client_info.client_secret_expires_at,
                    redirect_uris=[str(uri) for uri in client_info.redirect_uris or []],
                    token_endpoint_auth_method=client_info.token_endpoint_auth_method,
                    grant_types=list(client_info.grant_types),
                    response_types=list(client_info.response_types),
                    scope=client_info.scope or MCP_READ_SCOPE,
                    client_name=client_info.client_name,
                    client_uri=str(client_info.client_uri) if client_info.client_uri else None,
                    logo_uri=str(client_info.logo_uri) if client_info.logo_uri else None,
                    contacts=client_info.contacts,
                    tos_uri=str(client_info.tos_uri) if client_info.tos_uri else None,
                    policy_uri=str(client_info.policy_uri) if client_info.policy_uri else None,
                    jwks_uri=str(client_info.jwks_uri) if client_info.jwks_uri else None,
                    jwks=client_info.jwks,
                    software_id=client_info.software_id,
                    software_version=client_info.software_version,
                )
            )

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        if not resource_matches(params.resource):
            raise AuthorizeError("invalid_request", "Invalid or missing MCP resource parameter")

        request_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        settings = get_settings()
        async with _mcp_db_context() as db:
            db.add(
                McpOAuthAuthorizationRequest(
                    request_hash=token_hash(request_token),
                    client_id=client.client_id or "",
                    state=params.state,
                    scopes=_scope_list(params.scopes, client),
                    code_challenge=params.code_challenge,
                    redirect_uri=str(params.redirect_uri),
                    redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                    resource=params.resource or settings.mcp_resource_url_resolved,
                    csrf_token=csrf_token,
                    expires_at=_now()
                    + timedelta(minutes=settings.mcp_authorization_request_expire_minutes),
                )
            )
        return f"/api/mcp/oauth/consent?request={request_token}"

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        async with _mcp_db_context() as db:
            result = await db.execute(
                select(McpOAuthAuthorizationCode).where(
                    McpOAuthAuthorizationCode.code_hash == token_hash(authorization_code),
                    McpOAuthAuthorizationCode.client_id == client.client_id,
                    McpOAuthAuthorizationCode.used_at.is_(None),
                )
            )
            code = result.scalar_one_or_none()
            if code is None:
                return None
            return AuthorizationCode(
                code=authorization_code,
                scopes=code.scopes,
                expires_at=_as_timestamp(code.expires_at),
                client_id=code.client_id,
                code_challenge=code.code_challenge,
                redirect_uri=code.redirect_uri,
                redirect_uri_provided_explicitly=code.redirect_uri_provided_explicitly,
                resource=code.resource,
            )

    async def _issue_token_pair(
        self,
        db: AsyncSession,
        *,
        client_id: str,
        user_id: UUID,
        scopes: list[str],
        resource: str,
    ) -> OAuthToken:
        settings = get_settings()
        access_token = secrets.token_urlsafe(48)
        refresh_token = secrets.token_urlsafe(64)
        access_expires_at = _now() + timedelta(minutes=settings.mcp_access_token_expire_minutes)
        refresh_expires_at = _now() + timedelta(days=settings.mcp_refresh_token_expire_days)
        db.add_all(
            [
                McpOAuthToken(
                    token_hash=token_hash(access_token),
                    token_type=ACCESS_TOKEN_TYPE,
                    client_id=client_id,
                    user_id=user_id,
                    scopes=scopes,
                    resource=resource,
                    expires_at=access_expires_at,
                ),
                McpOAuthToken(
                    token_hash=token_hash(refresh_token),
                    token_type=REFRESH_TOKEN_TYPE,
                    client_id=client_id,
                    user_id=user_id,
                    scopes=scopes,
                    resource=resource,
                    expires_at=refresh_expires_at,
                ),
            ]
        )
        await db.flush()
        return OAuthToken(
            access_token=access_token,
            expires_in=_expires_in_seconds(access_expires_at),
            scope=" ".join(scopes),
            refresh_token=refresh_token,
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        async with _mcp_db_context() as db:
            result = await db.execute(
                select(McpOAuthAuthorizationCode).where(
                    McpOAuthAuthorizationCode.code_hash == token_hash(authorization_code.code),
                    McpOAuthAuthorizationCode.client_id == client.client_id,
                    McpOAuthAuthorizationCode.used_at.is_(None),
                )
            )
            code = result.scalar_one_or_none()
            if code is None:
                raise TokenError("invalid_grant", "authorization code does not exist")
            code.used_at = _now()
            return await self._issue_token_pair(
                db,
                client_id=code.client_id,
                user_id=code.user_id,
                scopes=code.scopes,
                resource=code.resource,
            )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        async with _mcp_db_context() as db:
            result = await db.execute(
                select(McpOAuthToken).where(
                    McpOAuthToken.token_hash == token_hash(refresh_token),
                    McpOAuthToken.token_type == REFRESH_TOKEN_TYPE,
                    McpOAuthToken.client_id == client.client_id,
                    McpOAuthToken.revoked_at.is_(None),
                )
            )
            db_token = result.scalar_one_or_none()
            if db_token is None:
                return None
            return RefreshToken(
                token=refresh_token,
                client_id=db_token.client_id,
                scopes=db_token.scopes,
                expires_at=_as_timestamp(db_token.expires_at),
            )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        async with _mcp_db_context() as db:
            result = await db.execute(
                select(McpOAuthToken).where(
                    McpOAuthToken.token_hash == token_hash(refresh_token.token),
                    McpOAuthToken.token_type == REFRESH_TOKEN_TYPE,
                    McpOAuthToken.client_id == client.client_id,
                    McpOAuthToken.revoked_at.is_(None),
                )
            )
            db_token = result.scalar_one_or_none()
            if db_token is None:
                raise TokenError("invalid_grant", "refresh token does not exist")
            db_token.revoked_at = _now()
            return await self._issue_token_pair(
                db,
                client_id=db_token.client_id,
                user_id=db_token.user_id,
                scopes=scopes,
                resource=db_token.resource,
            )

    async def load_access_token(self, token: str) -> AccessToken | None:
        return await self.verify_token(token)

    async def verify_token(self, token: str) -> AccessToken | None:
        async with _mcp_db_context() as db:
            if is_api_key(token):
                api_key = await resolve_api_key(db, token)
                if api_key is None:
                    return None
                return AccessToken(
                    token=token,
                    client_id=f"api_key:{api_key.id}",
                    scopes=[MCP_READ_SCOPE],
                    expires_at=_as_timestamp(api_key.expires_at) if api_key.expires_at else None,
                    resource=get_settings().mcp_resource_url_resolved,
                )
            result = await db.execute(
                select(McpOAuthToken).where(
                    McpOAuthToken.token_hash == token_hash(token),
                    McpOAuthToken.token_type == ACCESS_TOKEN_TYPE,
                    McpOAuthToken.revoked_at.is_(None),
                    McpOAuthToken.expires_at > _now(),
                )
            )
            db_token = result.scalar_one_or_none()
            if db_token is None or not resource_matches(db_token.resource):
                return None
            return AccessToken(
                token=token,
                client_id=db_token.client_id,
                scopes=db_token.scopes,
                expires_at=_as_timestamp(db_token.expires_at),
                resource=db_token.resource,
            )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        async with _mcp_db_context() as db:
            result = await db.execute(
                select(McpOAuthToken).where(McpOAuthToken.token_hash == token_hash(token.token))
            )
            db_token = result.scalar_one_or_none()
            if db_token is not None:
                db_token.revoked_at = _now()


mcp_oauth_provider = WaiComputerMcpOAuthProvider()
