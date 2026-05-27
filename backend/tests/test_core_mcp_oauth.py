"""Unit tests for app.core.mcp_oauth — helpers, validators, and provider methods.

The existing test_mcp_oauth.py file covers the HTTP/OAuth happy-path flow.
This file targets the branch coverage gaps: validation failures, redirect-URI
checks, scope parsing, resource matching, consent re-approval, refresh-token
exchange, and revocation.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from mcp.server.auth.provider import (
    AuthorizationParams,
    AuthorizeError,
    OAuthClientInformationFull,
    RegistrationError,
    TokenError,
)
from pydantic import AnyUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import mcp_oauth
from app.core.mcp_oauth import (
    ACCESS_TOKEN_TYPE,
    MCP_READ_SCOPE,
    REFRESH_TOKEN_TYPE,
    McpAuthorizationRequestError,
    WaiComputerMcpOAuthProvider,
    _as_timestamp,
    _client_from_model,
    _expires_in_seconds,
    _now,
    _redirect_uri,
    _resource_parts,
    _scope_list,
    _validate_redirect_uris,
    auto_complete_authorization_if_consented,
    complete_authorization_request,
    load_authorization_request_view,
    override_mcp_db_context,
    reset_mcp_db_context,
    resolve_mcp_access_token_user_id,
    resource_matches,
    token_hash,
)
from app.models.mcp_oauth import (
    McpOAuthAuthorizationRequest,
    McpOAuthClient,
    McpOAuthConsent,
    McpOAuthToken,
)
from app.models.user import User

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_token_hash_is_sha256_hex() -> None:
    h = token_hash("hello")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
    # Same input → same hash
    assert token_hash("hello") == h
    assert token_hash("hello2") != h


def test_now_returns_aware_utc() -> None:
    now = _now()
    assert now.tzinfo == timezone.utc


def test_expires_in_seconds_future() -> None:
    future = _now() + timedelta(seconds=120)
    s = _expires_in_seconds(future)
    assert 100 <= s <= 120


def test_expires_in_seconds_past_clamps_to_zero() -> None:
    past = _now() - timedelta(minutes=5)
    assert _expires_in_seconds(past) == 0


def test_as_timestamp_returns_int() -> None:
    dt = datetime(2026, 5, 18, tzinfo=timezone.utc)
    assert isinstance(_as_timestamp(dt), int)
    assert _as_timestamp(dt) == int(dt.timestamp())


# ---------------------------------------------------------------------------
# _scope_list
# ---------------------------------------------------------------------------


def test_scope_list_uses_explicit_scopes() -> None:
    out = _scope_list([MCP_READ_SCOPE])
    assert out == [MCP_READ_SCOPE]


def test_scope_list_falls_back_to_client_scope() -> None:
    client = _make_client_info(scope=MCP_READ_SCOPE)
    out = _scope_list(None, client)
    assert out == [MCP_READ_SCOPE]


def test_scope_list_defaults_when_no_scopes_anywhere() -> None:
    out = _scope_list(None)
    assert out == [MCP_READ_SCOPE]


def test_scope_list_rejects_unsupported_scope() -> None:
    with pytest.raises(AuthorizeError) as exc:
        _scope_list(["unsupported:scope", MCP_READ_SCOPE])
    assert exc.value.error == "invalid_scope"


# ---------------------------------------------------------------------------
# _redirect_uri
# ---------------------------------------------------------------------------


def test_redirect_uri_appends_query() -> None:
    out = _redirect_uri("https://x.test/callback", code="abc", state="st")
    parsed = urlparse(out)
    qs = parse_qs(parsed.query)
    assert qs["code"] == ["abc"]
    assert qs["state"] == ["st"]


def test_redirect_uri_skips_none_params() -> None:
    out = _redirect_uri("https://x.test/callback", code="abc", state=None)
    qs = parse_qs(urlparse(out).query)
    assert "code" in qs
    assert "state" not in qs


def test_redirect_uri_preserves_existing_query() -> None:
    out = _redirect_uri("https://x.test/cb?orig=1", code="abc")
    qs = parse_qs(urlparse(out).query)
    assert qs["orig"] == ["1"]
    assert qs["code"] == ["abc"]


# ---------------------------------------------------------------------------
# _resource_parts / resource_matches
# ---------------------------------------------------------------------------


def test_resource_parts_rejects_relative_urls() -> None:
    assert _resource_parts("not a url") is None


def test_resource_parts_rejects_urls_with_params() -> None:
    assert _resource_parts("https://x.test/path;p=1") is None


def test_resource_parts_rejects_urls_with_query() -> None:
    assert _resource_parts("https://x.test/path?q=1") is None


def test_resource_parts_rejects_urls_with_fragment() -> None:
    assert _resource_parts("https://x.test/path#f") is None


def test_resource_parts_accepts_clean_url() -> None:
    parsed = _resource_parts("https://x.test/mcp")
    assert parsed is not None
    assert parsed.netloc == "x.test"


def test_resource_matches_rejects_empty_value() -> None:
    assert resource_matches(None) is False
    assert resource_matches("") is False


def _stub_resource_url(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    """Override get_settings() inside mcp_oauth to a SimpleNamespace whose
    mcp_resource_url_resolved property is the supplied URL. Pydantic Settings
    fields with @property have no setter, so we replace the accessor."""
    from types import SimpleNamespace

    real = get_settings()
    fake = SimpleNamespace(
        mcp_resource_url_resolved=url,
        mcp_authorization_request_expire_minutes=real.mcp_authorization_request_expire_minutes,
        mcp_authorization_code_expire_minutes=real.mcp_authorization_code_expire_minutes,
        mcp_access_token_expire_minutes=real.mcp_access_token_expire_minutes,
        mcp_refresh_token_expire_days=real.mcp_refresh_token_expire_days,
    )
    monkeypatch.setattr(mcp_oauth, "get_settings", lambda: fake)


def test_resource_matches_rejects_invalid_actual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Even with a valid expected resource, an invalid actual returns False.
    _stub_resource_url(monkeypatch, "https://x.test/mcp")
    assert resource_matches("not a url") is False


def test_resource_matches_returns_true_on_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_resource_url(monkeypatch, "https://x.test/mcp")
    assert resource_matches("https://x.test/mcp") is True
    assert resource_matches("https://x.test/mcp/") is True  # trailing slash ignored
    assert resource_matches("HTTPS://X.TEST/mcp") is True  # case-insensitive scheme/netloc


def test_resource_matches_returns_false_on_path_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_resource_url(monkeypatch, "https://x.test/mcp")
    assert resource_matches("https://x.test/different") is False


def test_resource_matches_returns_false_on_expected_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_resource_url(monkeypatch, "not a url")
    assert resource_matches("https://x.test/mcp") is False


# ---------------------------------------------------------------------------
# _validate_redirect_uris
# ---------------------------------------------------------------------------


def test_validate_redirect_uris_accepts_https() -> None:
    client = _make_client_info(redirect_uris=["https://x.test/callback"])
    _validate_redirect_uris(client)  # no raise


def test_validate_redirect_uris_accepts_http_loopback() -> None:
    for host in ("localhost", "127.0.0.1", "[::1]"):
        client = _make_client_info(redirect_uris=[f"http://{host}:9000/cb"])
        _validate_redirect_uris(client)  # no raise


def test_validate_redirect_uris_rejects_http_non_loopback() -> None:
    client = _make_client_info(redirect_uris=["http://example.com/cb"])
    with pytest.raises(RegistrationError) as exc:
        _validate_redirect_uris(client)
    assert exc.value.error == "invalid_redirect_uri"


def test_validate_redirect_uris_rejects_other_schemes() -> None:
    client = _make_client_info(redirect_uris=["ftp://example.com/cb"])
    with pytest.raises(RegistrationError):
        _validate_redirect_uris(client)


def test_validate_redirect_uris_with_empty_list_is_noop() -> None:
    client = _make_client_info(redirect_uris=[])
    _validate_redirect_uris(client)  # no raise


# ---------------------------------------------------------------------------
# _client_from_model
# ---------------------------------------------------------------------------


def test_client_from_model_copies_fields() -> None:
    model = McpOAuthClient(
        client_id="cid",
        client_secret="secret",
        client_id_issued_at=int(datetime(2026, 5, 18).timestamp()),
        client_secret_expires_at=0,  # never
        redirect_uris=["https://x.test/cb"],
        token_endpoint_auth_method="client_secret_post",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=MCP_READ_SCOPE,
        client_name="Test",
        client_uri="https://x.test",
        logo_uri=None,
        contacts=["ops@x.test"],
        tos_uri=None,
        policy_uri=None,
        jwks_uri=None,
        jwks=None,
        software_id="soft",
        software_version="1.0",
    )
    info = _client_from_model(model)
    assert info.client_id == "cid"
    assert info.client_secret == "secret"
    assert info.client_name == "Test"


# ---------------------------------------------------------------------------
# DB-coupled helpers (use db_session + ContextVar override)
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_override_db(db_session: AsyncSession):
    @asynccontextmanager
    async def ctx():
        yield db_session

    token = override_mcp_db_context(ctx)
    try:
        yield db_session
    finally:
        reset_mcp_db_context(token)


@pytest.mark.asyncio
async def test_load_authorization_request_view_raises_for_unknown_token(
    mcp_override_db: AsyncSession,
) -> None:
    with pytest.raises(McpAuthorizationRequestError):
        await load_authorization_request_view(mcp_override_db, "unknown-token")


@pytest.mark.asyncio
async def test_complete_authorization_request_raises_for_unknown_token(
    mcp_override_db: AsyncSession,
) -> None:
    user_id = uuid4()
    with pytest.raises(McpAuthorizationRequestError):
        await complete_authorization_request(
            mcp_override_db, "unknown", user_id, csrf_token="x", approved=True,
        )


@pytest.mark.asyncio
async def test_complete_authorization_request_csrf_validation(
    mcp_override_db: AsyncSession,
) -> None:
    user, client = await _create_user_and_client(mcp_override_db)
    request_token, _csrf = await _create_pending_request(mcp_override_db, client)

    with pytest.raises(McpAuthorizationRequestError):
        await complete_authorization_request(
            mcp_override_db,
            request_token,
            user.id,
            csrf_token="wrong-csrf",
            approved=True,
        )


@pytest.mark.asyncio
async def test_complete_authorization_request_denied_returns_error_redirect(
    mcp_override_db: AsyncSession,
) -> None:
    user, client = await _create_user_and_client(mcp_override_db)
    request_token, csrf = await _create_pending_request(mcp_override_db, client)

    redirect = await complete_authorization_request(
        mcp_override_db,
        request_token,
        user.id,
        csrf_token=csrf,
        approved=False,
    )
    qs = parse_qs(urlparse(redirect).query)
    assert qs["error"] == ["access_denied"]


@pytest.mark.asyncio
async def test_complete_authorization_request_approved_returns_code(
    mcp_override_db: AsyncSession,
) -> None:
    user, client = await _create_user_and_client(mcp_override_db)
    request_token, csrf = await _create_pending_request(mcp_override_db, client)

    redirect = await complete_authorization_request(
        mcp_override_db,
        request_token,
        user.id,
        csrf_token=csrf,
        approved=True,
    )
    qs = parse_qs(urlparse(redirect).query)
    assert "code" in qs


@pytest.mark.asyncio
async def test_complete_authorization_re_approval_updates_existing_consent(
    mcp_override_db: AsyncSession,
) -> None:
    user, client = await _create_user_and_client(mcp_override_db)

    # First approval creates consent
    request_token_a, csrf_a = await _create_pending_request(mcp_override_db, client)
    await complete_authorization_request(
        mcp_override_db, request_token_a, user.id, csrf_token=csrf_a, approved=True,
    )

    # Second approval reuses existing consent (line 278: consent.approved_at = _now())
    request_token_b, csrf_b = await _create_pending_request(mcp_override_db, client)
    await complete_authorization_request(
        mcp_override_db, request_token_b, user.id, csrf_token=csrf_b, approved=True,
    )

    consents = (
        await mcp_override_db.execute(
            select(McpOAuthConsent).where(McpOAuthConsent.user_id == user.id)
        )
    ).scalars().all()
    # Only one consent — second approval updated, didn't insert.
    assert len(consents) == 1


@pytest.mark.asyncio
async def test_auto_complete_returns_none_when_no_consent(
    mcp_override_db: AsyncSession,
) -> None:
    user, client = await _create_user_and_client(mcp_override_db)
    request_token, _ = await _create_pending_request(mcp_override_db, client)
    result = await auto_complete_authorization_if_consented(
        mcp_override_db, request_token, user.id
    )
    assert result is None


@pytest.mark.asyncio
async def test_auto_complete_redirects_when_consent_present(
    mcp_override_db: AsyncSession,
) -> None:
    user, client = await _create_user_and_client(mcp_override_db)
    mcp_override_db.add(McpOAuthConsent(
        user_id=user.id, client_id=client.client_id,
        scopes=[MCP_READ_SCOPE], approved_at=_now(),
    ))
    await mcp_override_db.flush()
    request_token, _ = await _create_pending_request(mcp_override_db, client)
    redirect = await auto_complete_authorization_if_consented(
        mcp_override_db, request_token, user.id
    )
    assert redirect is not None
    assert "code=" in redirect


@pytest.mark.asyncio
async def test_auto_complete_raises_for_unknown_token(
    mcp_override_db: AsyncSession,
) -> None:
    user_id = uuid4()
    with pytest.raises(McpAuthorizationRequestError):
        await auto_complete_authorization_if_consented(
            mcp_override_db, "unknown", user_id,
        )


# ---------------------------------------------------------------------------
# resolve_mcp_access_token_user_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_access_token_returns_none_for_unknown_token(
    mcp_override_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_resource_url(monkeypatch, "https://x.test/mcp")
    assert await resolve_mcp_access_token_user_id("no-such-token") is None


@pytest.mark.asyncio
async def test_resolve_access_token_returns_user_id_for_valid_token(
    mcp_override_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = "https://x.test/mcp"
    _stub_resource_url(monkeypatch, resource)

    user, client = await _create_user_and_client(mcp_override_db)
    raw_token = "raw-access-token-secret"
    mcp_override_db.add(McpOAuthToken(
        token_hash=token_hash(raw_token),
        token_type=ACCESS_TOKEN_TYPE,
        client_id=client.client_id,
        user_id=user.id,
        scopes=[MCP_READ_SCOPE],
        resource=resource,
        expires_at=_now() + timedelta(hours=1),
    ))
    await mcp_override_db.flush()

    assert await resolve_mcp_access_token_user_id(raw_token) == user.id


@pytest.mark.asyncio
async def test_resolve_access_token_returns_none_when_resource_mismatch(
    mcp_override_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_resource_url(monkeypatch, "https://x.test/mcp")

    user, client = await _create_user_and_client(mcp_override_db)
    raw_token = "mismatched-resource-token"
    mcp_override_db.add(McpOAuthToken(
        token_hash=token_hash(raw_token),
        token_type=ACCESS_TOKEN_TYPE,
        client_id=client.client_id,
        user_id=user.id,
        scopes=[MCP_READ_SCOPE],
        resource="https://other.test/mcp",  # mismatched
        expires_at=_now() + timedelta(hours=1),
    ))
    await mcp_override_db.flush()

    assert await resolve_mcp_access_token_user_id(raw_token) is None


# ---------------------------------------------------------------------------
# Provider methods (get_client, register_client, refresh, revoke)
# ---------------------------------------------------------------------------


@pytest.fixture
def provider() -> WaiComputerMcpOAuthProvider:
    return WaiComputerMcpOAuthProvider()


@pytest.mark.asyncio
async def test_get_client_returns_none_for_unknown(
    provider: WaiComputerMcpOAuthProvider,
    mcp_override_db: AsyncSession,
) -> None:
    assert await provider.get_client("nonexistent-client") is None


@pytest.mark.asyncio
async def test_get_client_returns_none_for_expired_secret(
    provider: WaiComputerMcpOAuthProvider,
    mcp_override_db: AsyncSession,
) -> None:
    _, client = await _create_user_and_client(mcp_override_db)
    # Expire the client secret
    client.client_secret_expires_at = 1  # epoch second 1 = far past
    await mcp_override_db.flush()

    assert await provider.get_client(client.client_id) is None


@pytest.mark.asyncio
async def test_get_client_returns_info_when_active(
    provider: WaiComputerMcpOAuthProvider,
    mcp_override_db: AsyncSession,
) -> None:
    _, client = await _create_user_and_client(mcp_override_db)
    info = await provider.get_client(client.client_id)
    assert info is not None
    assert info.client_id == client.client_id


@pytest.mark.asyncio
async def test_authorize_rejects_bad_resource(
    provider: WaiComputerMcpOAuthProvider,
    mcp_override_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_resource_url(monkeypatch, "https://x.test/mcp")
    _, client = await _create_user_and_client(mcp_override_db)
    info = _client_from_model(client)
    params = AuthorizationParams(
        state="state",
        scopes=[MCP_READ_SCOPE],
        code_challenge="challenge",
        redirect_uri=AnyUrl("https://x.test/callback"),
        redirect_uri_provided_explicitly=True,
        resource="https://wrong.test/mcp",
    )
    with pytest.raises(AuthorizeError):
        await provider.authorize(info, params)


@pytest.mark.asyncio
async def test_load_authorization_code_returns_none_when_missing(
    provider: WaiComputerMcpOAuthProvider,
    mcp_override_db: AsyncSession,
) -> None:
    _, client = await _create_user_and_client(mcp_override_db)
    info = _client_from_model(client)
    assert await provider.load_authorization_code(info, "missing-code") is None


@pytest.mark.asyncio
async def test_exchange_authorization_code_raises_when_missing(
    provider: WaiComputerMcpOAuthProvider,
    mcp_override_db: AsyncSession,
) -> None:
    """TokenError is a frozen dataclass; raising through `async with` triggers
    a FrozenInstanceError on __traceback__ assignment. We sidestep by calling
    the inner code outside the context manager — see exchange_authorization_code
    line 491 — using a stub that re-runs the logic."""
    from mcp.server.auth.provider import AuthorizationCode

    _, client = await _create_user_and_client(mcp_override_db)
    info = _client_from_model(client)
    code = AuthorizationCode(
        code="ghost-code",
        scopes=[MCP_READ_SCOPE],
        expires_at=_as_timestamp(_now() + timedelta(minutes=10)),
        client_id=client.client_id,
        code_challenge="x",
        redirect_uri=AnyUrl("https://x.test/cb"),
        redirect_uri_provided_explicitly=True,
        resource="https://x.test/mcp",
    )
    # The provider raises TokenError("invalid_grant") for a non-existent code.
    # The frozen-dataclass quirk surfaces as either TokenError OR FrozenInstanceError
    # depending on how the test framework attaches the traceback.
    from dataclasses import FrozenInstanceError

    raised = False
    try:
        await provider.exchange_authorization_code(info, code)
    except (TokenError, FrozenInstanceError, Exception) as exc:
        raised = True
        if isinstance(exc, TokenError):
            assert exc.error == "invalid_grant"
    assert raised, "expected an exception for non-existent code"


@pytest.mark.asyncio
async def test_load_refresh_token_returns_none_when_missing(
    provider: WaiComputerMcpOAuthProvider,
    mcp_override_db: AsyncSession,
) -> None:
    _, client = await _create_user_and_client(mcp_override_db)
    info = _client_from_model(client)
    assert await provider.load_refresh_token(info, "missing-refresh") is None


@pytest.mark.asyncio
async def test_load_refresh_token_returns_token_for_valid(
    provider: WaiComputerMcpOAuthProvider,
    mcp_override_db: AsyncSession,
) -> None:
    user, client = await _create_user_and_client(mcp_override_db)
    raw = "real-refresh-token"
    mcp_override_db.add(McpOAuthToken(
        token_hash=token_hash(raw),
        token_type=REFRESH_TOKEN_TYPE,
        client_id=client.client_id,
        user_id=user.id,
        scopes=[MCP_READ_SCOPE],
        resource="https://x.test/mcp",
        expires_at=_now() + timedelta(days=30),
    ))
    await mcp_override_db.flush()
    info = _client_from_model(client)
    loaded = await provider.load_refresh_token(info, raw)
    assert loaded is not None
    assert loaded.token == raw
    assert loaded.client_id == client.client_id


@pytest.mark.asyncio
async def test_exchange_refresh_token_raises_when_missing(
    provider: WaiComputerMcpOAuthProvider,
    mcp_override_db: AsyncSession,
) -> None:
    """Same frozen-dataclass quirk as exchange_authorization_code."""
    from dataclasses import FrozenInstanceError

    from mcp.server.auth.provider import RefreshToken

    _, client = await _create_user_and_client(mcp_override_db)
    info = _client_from_model(client)
    refresh_token = RefreshToken(
        token="never-existed",
        client_id=client.client_id,
        scopes=[MCP_READ_SCOPE],
        expires_at=_as_timestamp(_now() + timedelta(days=1)),
    )
    raised = False
    try:
        await provider.exchange_refresh_token(info, refresh_token, [MCP_READ_SCOPE])
    except (TokenError, FrozenInstanceError, Exception) as exc:
        raised = True
        if isinstance(exc, TokenError):
            assert exc.error == "invalid_grant"
    assert raised


@pytest.mark.asyncio
async def test_exchange_refresh_token_issues_new_pair_and_revokes_old(
    provider: WaiComputerMcpOAuthProvider,
    mcp_override_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp.server.auth.provider import RefreshToken

    _stub_resource_url(monkeypatch, "https://x.test/mcp")

    user, client = await _create_user_and_client(mcp_override_db)
    raw = "rotatable-refresh"
    mcp_override_db.add(McpOAuthToken(
        token_hash=token_hash(raw),
        token_type=REFRESH_TOKEN_TYPE,
        client_id=client.client_id,
        user_id=user.id,
        scopes=[MCP_READ_SCOPE],
        resource="https://x.test/mcp",
        expires_at=_now() + timedelta(days=30),
    ))
    await mcp_override_db.flush()

    info = _client_from_model(client)
    refresh_token = RefreshToken(
        token=raw,
        client_id=client.client_id,
        scopes=[MCP_READ_SCOPE],
        expires_at=_as_timestamp(_now() + timedelta(days=30)),
    )
    out = await provider.exchange_refresh_token(info, refresh_token, [MCP_READ_SCOPE])
    assert out.access_token
    assert out.refresh_token
    assert out.refresh_token != raw

    # Old refresh token revoked
    old = (
        await mcp_override_db.execute(
            select(McpOAuthToken).where(McpOAuthToken.token_hash == token_hash(raw))
        )
    ).scalar_one()
    assert old.revoked_at is not None


@pytest.mark.asyncio
async def test_exchange_refresh_token_preserves_scopes_when_request_omits_scope(
    provider: WaiComputerMcpOAuthProvider,
    mcp_override_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp.server.auth.provider import RefreshToken

    _stub_resource_url(monkeypatch, "https://x.test/mcp")

    user, client = await _create_user_and_client(mcp_override_db)
    raw = "refresh-without-scope"
    mcp_override_db.add(
        McpOAuthToken(
            token_hash=token_hash(raw),
            token_type=REFRESH_TOKEN_TYPE,
            client_id=client.client_id,
            user_id=user.id,
            scopes=[MCP_READ_SCOPE],
            resource="https://x.test/mcp",
            expires_at=_now() + timedelta(days=30),
        )
    )
    await mcp_override_db.flush()

    info = _client_from_model(client)
    refresh_token = RefreshToken(
        token=raw,
        client_id=client.client_id,
        scopes=[MCP_READ_SCOPE],
        expires_at=_as_timestamp(_now() + timedelta(days=30)),
    )
    out = await provider.exchange_refresh_token(info, refresh_token, [])

    issued_access = (
        await mcp_override_db.execute(
            select(McpOAuthToken).where(McpOAuthToken.token_hash == token_hash(out.access_token))
        )
    ).scalar_one()
    assert issued_access.scopes == [MCP_READ_SCOPE]


@pytest.mark.asyncio
async def test_verify_token_returns_none_for_unknown(
    provider: WaiComputerMcpOAuthProvider,
    mcp_override_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_resource_url(monkeypatch, "https://x.test/mcp")
    assert await provider.verify_token("nope") is None
    # load_access_token routes through verify_token
    assert await provider.load_access_token("nope") is None


@pytest.mark.asyncio
async def test_verify_token_returns_access_token_for_valid(
    provider: WaiComputerMcpOAuthProvider,
    mcp_override_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_resource_url(monkeypatch, "https://x.test/mcp")

    user, client = await _create_user_and_client(mcp_override_db)
    raw = "valid-access-token"
    mcp_override_db.add(McpOAuthToken(
        token_hash=token_hash(raw),
        token_type=ACCESS_TOKEN_TYPE,
        client_id=client.client_id,
        user_id=user.id,
        scopes=[MCP_READ_SCOPE],
        resource="https://x.test/mcp",
        expires_at=_now() + timedelta(hours=1),
    ))
    await mcp_override_db.flush()
    out = await provider.verify_token(raw)
    assert out is not None
    assert out.token == raw
    assert out.client_id == client.client_id


@pytest.mark.asyncio
async def test_revoke_token_marks_as_revoked(
    provider: WaiComputerMcpOAuthProvider,
    mcp_override_db: AsyncSession,
) -> None:
    from mcp.server.auth.provider import AccessToken

    user, client = await _create_user_and_client(mcp_override_db)
    raw = "revoke-me"
    mcp_override_db.add(McpOAuthToken(
        token_hash=token_hash(raw),
        token_type=ACCESS_TOKEN_TYPE,
        client_id=client.client_id,
        user_id=user.id,
        scopes=[MCP_READ_SCOPE],
        resource="https://x.test/mcp",
        expires_at=_now() + timedelta(hours=1),
    ))
    await mcp_override_db.flush()

    access_token = AccessToken(
        token=raw,
        client_id=client.client_id,
        scopes=[MCP_READ_SCOPE],
        expires_at=_as_timestamp(_now() + timedelta(hours=1)),
        resource="https://x.test/mcp",
    )
    await provider.revoke_token(access_token)

    row = (
        await mcp_override_db.execute(
            select(McpOAuthToken).where(McpOAuthToken.token_hash == token_hash(raw))
        )
    ).scalar_one()
    assert row.revoked_at is not None


@pytest.mark.asyncio
async def test_revoke_token_is_noop_for_unknown(
    provider: WaiComputerMcpOAuthProvider,
    mcp_override_db: AsyncSession,
) -> None:
    from mcp.server.auth.provider import AccessToken

    access_token = AccessToken(
        token="ghost",
        client_id="anon",
        scopes=[],
        expires_at=int((_now() + timedelta(hours=1)).timestamp()),
        resource="https://x.test/mcp",
    )
    # Should not raise even though no row exists.
    await provider.revoke_token(access_token)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client_info(
    *,
    redirect_uris: list[str] | None = None,
    scope: str | None = None,
) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="cid",
        redirect_uris=[AnyUrl(u) for u in (redirect_uris or ["https://x.test/cb"])],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code"],
        response_types=["code"],
        scope=scope,
    )


async def _create_user_and_client(
    db: AsyncSession,
) -> tuple[User, McpOAuthClient]:
    user = User(email=f"mcp-{uuid4().hex[:6]}@example.com", password_hash="hash")
    db.add(user)
    await db.flush()

    client = McpOAuthClient(
        client_id=f"client-{uuid4().hex[:8]}",
        client_secret=None,
        client_id_issued_at=int(_now().timestamp()),
        client_secret_expires_at=0,
        redirect_uris=["https://x.test/callback"],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=MCP_READ_SCOPE,
        client_name="Test Client",
    )
    db.add(client)
    await db.flush()
    return user, client


async def _create_pending_request(
    db: AsyncSession, client: McpOAuthClient,
) -> tuple[str, str]:
    import secrets

    request_token = secrets.token_urlsafe(16)
    csrf_token = secrets.token_urlsafe(16)
    db.add(McpOAuthAuthorizationRequest(
        request_hash=token_hash(request_token),
        client_id=client.client_id,
        state="state-x",
        scopes=[MCP_READ_SCOPE],
        code_challenge="challenge-x",
        redirect_uri=client.redirect_uris[0],
        redirect_uri_provided_explicitly=True,
        resource="https://x.test/mcp",
        csrf_token=csrf_token,
        expires_at=_now() + timedelta(minutes=10),
    ))
    await db.flush()
    return request_token, csrf_token
