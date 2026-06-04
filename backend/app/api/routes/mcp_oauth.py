"""Browser consent and connection-management routes for MCP OAuth."""

from __future__ import annotations

import html
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, Database, _extract_access_token, bearer_security
from app.config import get_settings
from app.core.mcp_oauth import (
    ACCESS_TOKEN_TYPE,
    McpAuthorizationRequestError,
    auto_complete_authorization_if_consented,
    complete_authorization_request,
    load_authorization_request_view,
)
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.mcp_oauth import McpOAuthClient, McpOAuthConsent, McpOAuthToken
from app.models.user import User

router = APIRouter(prefix="/mcp/oauth", tags=["mcp-oauth"])


async def _optional_browser_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    db: AsyncSession,
) -> User | None:
    token = _extract_access_token(request, credentials)
    if token is None:
        return None
    user_id = decode_access_token(token)
    if user_id is None:
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


def _frontend_login_url(request: Request) -> str:
    settings = get_settings()
    return_to = f"{settings.frontend_url.rstrip('/')}{request.url.path}"
    if request.url.query:
        return_to = f"{return_to}?{request.url.query}"
    return f"{settings.frontend_url.rstrip('/')}/login?returnTo={quote(return_to, safe='')}"


def _consent_html(
    *,
    request_token: str,
    csrf_token: str,
    client_name: str,
    client_uri: str | None,
    redirect_uri: str,
    scopes: list[str],
) -> str:
    escaped_client = html.escape(client_name)
    escaped_uri = html.escape(client_uri or "")
    escaped_redirect_uri = html.escape(redirect_uri)
    escaped_request = html.escape(request_token)
    escaped_csrf = html.escape(csrf_token)
    scope_rows = "\n".join(
        (
            f"<li>{html.escape(scope)}: read your WaiComputer recordings, transcripts, "
            "summaries, and action items.</li>"
        )
        for scope in scopes
    )
    uri_markup = (
        f'<p class="client-uri">{escaped_uri}</p>'
        if escaped_uri
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Authorize WaiComputer MCP</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: #f7f7f4;
      color: #171717;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      width: min(92vw, 520px);
      background: #ffffff;
      border: 1px solid #deded8;
      border-radius: 8px;
      padding: 28px;
      box-shadow: 0 18px 45px rgba(0, 0, 0, 0.08);
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: 24px;
      line-height: 1.2;
    }}
    p, li {{
      color: #3f3f3a;
      line-height: 1.55;
    }}
    ul {{
      padding-left: 22px;
    }}
    .client-uri {{
      margin-top: -4px;
      font-size: 13px;
      color: #6b6b63;
      word-break: break-word;
    }}
    .redirect {{
      margin-top: 18px;
      padding: 12px;
      border: 1px solid #deded8;
      border-radius: 6px;
      background: #f7f7f4;
      font-size: 13px;
      color: #3f3f3a;
      word-break: break-word;
    }}
    .redirect strong {{
      display: block;
      color: #171717;
      margin-bottom: 4px;
    }}
    .actions {{
      display: flex;
      gap: 12px;
      margin-top: 24px;
    }}
    button {{
      border-radius: 6px;
      border: 1px solid #1f1f1b;
      padding: 10px 16px;
      font: inherit;
      cursor: pointer;
    }}
    .approve {{
      background: #1f1f1b;
      color: #fff;
    }}
    .deny {{
      background: #fff;
      color: #1f1f1b;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Authorize {escaped_client}</h1>
    {uri_markup}
    <p>This MCP client is requesting read-only access to your WaiComputer library.</p>
    <ul>{scope_rows}</ul>
    <p class="redirect"><strong>Redirect URI</strong>{escaped_redirect_uri}</p>
    <form method="post" action="/api/mcp/oauth/consent">
      <input type="hidden" name="request" value="{escaped_request}" />
      <input type="hidden" name="csrf" value="{escaped_csrf}" />
      <div class="actions">
        <button class="approve" type="submit" name="decision" value="approve">Allow</button>
        <button class="deny" type="submit" name="decision" value="deny">Deny</button>
      </div>
    </form>
  </main>
</body>
</html>"""


@router.get("/consent", response_class=HTMLResponse, response_model=None)
async def get_consent(
    request: Request,
    request_token: str = Query(alias="request"),
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_security),
) -> Response:
    user = await _optional_browser_user(request, credentials, db)
    if user is None:
        return RedirectResponse(_frontend_login_url(request), status_code=status.HTTP_302_FOUND)

    try:
        redirect = await auto_complete_authorization_if_consented(db, request_token, user.id)
        if redirect is not None:
            return RedirectResponse(redirect, status_code=status.HTTP_302_FOUND)
        view = await load_authorization_request_view(db, request_token)
    except McpAuthorizationRequestError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    return HTMLResponse(
        _consent_html(
            request_token=view.request_token,
            csrf_token=view.csrf_token,
            client_name=view.client_name,
            client_uri=view.client_uri,
            redirect_uri=view.redirect_uri,
            scopes=view.scopes,
        ),
        headers={"Cache-Control": "no-store"},
    )


@router.post("/consent")
async def post_consent(
    raw_request: Request,
    request_token: str = Form(alias="request"),
    csrf: str = Form(),
    decision: str = Form(),
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_security),
) -> RedirectResponse:
    user = await _optional_browser_user(raw_request, credentials, db)
    if user is None:
        return RedirectResponse(_frontend_login_url(raw_request), status_code=status.HTTP_302_FOUND)
    try:
        redirect = await complete_authorization_request(
            db,
            request_token,
            user.id,
            csrf_token=csrf,
            approved=decision == "approve",
        )
    except McpAuthorizationRequestError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return RedirectResponse(redirect, status_code=status.HTTP_302_FOUND)


class McpConnection(BaseModel):
    """A connected MCP client — an approved, non-revoked consent."""

    client_id: str
    client_name: str
    client_uri: str | None
    scopes: list[str]
    approved_at: datetime
    last_active_at: datetime | None


@router.get("/connections")
async def list_connections(user: CurrentUser, db: Database) -> list[McpConnection]:
    """List the MCP clients the current user has connected."""
    result = await db.execute(
        select(McpOAuthConsent, McpOAuthClient)
        .join(McpOAuthClient, McpOAuthConsent.client_id == McpOAuthClient.client_id)
        .where(
            McpOAuthConsent.user_id == user.id,
            McpOAuthConsent.revoked_at.is_(None),
        )
        .order_by(McpOAuthConsent.approved_at.desc())
    )
    rows = result.all()

    # "Last active" ≈ newest access token issued (auth-code exchange or refresh).
    last_active_result = await db.execute(
        select(McpOAuthToken.client_id, func.max(McpOAuthToken.created_at))
        .where(
            McpOAuthToken.user_id == user.id,
            McpOAuthToken.token_type == ACCESS_TOKEN_TYPE,
        )
        .group_by(McpOAuthToken.client_id)
    )
    last_active = dict(last_active_result.all())

    return [
        McpConnection(
            client_id=consent.client_id,
            client_name=client.client_name or "MCP client",
            client_uri=client.client_uri,
            scopes=consent.scopes,
            approved_at=consent.approved_at,
            last_active_at=last_active.get(consent.client_id),
        )
        for consent, client in rows
    ]


@router.post(
    "/connections/{client_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def revoke_connection(client_id: str, user: CurrentUser, db: Database) -> Response:
    """Revoke a connected MCP client: cut its consent and all of its tokens."""
    result = await db.execute(
        select(McpOAuthConsent).where(
            McpOAuthConsent.user_id == user.id,
            McpOAuthConsent.client_id == client_id,
            McpOAuthConsent.revoked_at.is_(None),
        )
    )
    consent = result.scalar_one_or_none()
    if consent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")

    now = datetime.now(timezone.utc)
    consent.revoked_at = now
    await db.execute(
        update(McpOAuthToken)
        .where(
            McpOAuthToken.user_id == user.id,
            McpOAuthToken.client_id == client_id,
            McpOAuthToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
