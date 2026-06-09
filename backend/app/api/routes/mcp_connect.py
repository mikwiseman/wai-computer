"""One-tap agent-connect provisioning (P0c).

Session-only (a token cannot mint a token). For a PAT-style client this mints a
scoped ``wc_live_`` token, smoke-tests it through the exact resolver the ``/mcp``
server uses, and returns paste-ready connect material with the plaintext token
shown exactly once. For an OAuth client it returns token-free material (the
client authorizes via OAuth on connect). The whole point is that a bad/mis-scoped
connection fails HERE, at setup, not silently mid-chat.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import Database, SessionUser
from app.config import get_settings
from app.core.api_keys import (
    API_KEY_READ_SCOPE,
    API_KEY_WRITE_SCOPE,
    generate_api_key,
    resolve_api_key,
)
from app.core.mcp_connect import build_connect_material, clients_catalog, get_client
from app.models.api_key import ApiKey

router = APIRouter(prefix="/mcp/connect", tags=["mcp-connect"])


class ConnectClientsResponse(BaseModel):
    clients: list[dict]
    mcp_url: str


class ProvisionRequest(BaseModel):
    client: str = Field(min_length=1, max_length=64)
    mode: Literal["read", "readwrite"] = "read"


class SmokeTest(BaseModel):
    ok: bool
    detail: str


class ProvisionResponse(BaseModel):
    client: str
    name: str
    auth: str
    mcp_url: str
    mode: str
    token: str | None  # plaintext, shown exactly once; None for OAuth clients
    smoke_test: SmokeTest
    config: str
    deeplink: str | None
    install_command: str | None
    docs_url: str | None


@router.get("/clients", response_model=ConnectClientsResponse)
async def list_connect_clients() -> ConnectClientsResponse:
    """The connect-grid catalog + the canonical MCP URL — one source of truth."""
    settings = get_settings()
    return ConnectClientsResponse(
        clients=clients_catalog(), mcp_url=settings.mcp_resource_url_resolved
    )


@router.post("/provision", response_model=ProvisionResponse)
async def provision_connection(
    payload: ProvisionRequest, user: SessionUser, db: Database
) -> ProvisionResponse:
    """Provision a one-tap connection for ``payload.client``."""
    client = get_client(payload.client)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown client")

    settings = get_settings()
    mcp_url = settings.mcp_resource_url_resolved
    want_write = payload.mode == "readwrite"

    # OAuth clients connect by URL — no token to mint or smoke-test server-side.
    if client.auth == "oauth":
        material = build_connect_material(payload.client, mcp_url, None)
        return ProvisionResponse(
            client=payload.client,
            name=material["name"],
            auth=material["auth"],
            mcp_url=mcp_url,
            mode=payload.mode,
            token=None,
            smoke_test=SmokeTest(
                ok=True, detail=f"Authorize Wai in {client.name} — it connects via OAuth."
            ),
            config=material["config"],
            deeplink=material["deeplink"],
            install_command=material["install_command"],
            docs_url=material["docs_url"],
        )

    scopes = [API_KEY_READ_SCOPE] + ([API_KEY_WRITE_SCOPE] if want_write else [])
    plaintext, token_hash_value, prefix, last4 = generate_api_key()
    api_key = ApiKey(
        user_id=user.id,
        name=client.name,
        token_hash=token_hash_value,
        prefix=prefix,
        last4=last4,
        scopes=scopes,
    )
    db.add(api_key)
    await db.flush()

    # Server-side smoke-test: resolve the just-minted token through the same path
    # the /mcp server authenticates with, and confirm the granted scope matches
    # what the user asked for. Catches a mis-scoped or non-resolving credential
    # before the user ever pastes it.
    resolved = await resolve_api_key(db, plaintext)
    if resolved is None or resolved.id != api_key.id:
        smoke = SmokeTest(ok=False, detail="Token did not resolve — try again.")
    elif (API_KEY_WRITE_SCOPE in (resolved.scopes or [])) != want_write:
        smoke = SmokeTest(ok=False, detail="Scope mismatch — try again.")
    else:
        label = "read + save memories" if want_write else "read-only"
        smoke = SmokeTest(ok=True, detail=f"Wai verified this {label} connection.")

    material = build_connect_material(payload.client, mcp_url, plaintext)
    return ProvisionResponse(
        client=payload.client,
        name=material["name"],
        auth=material["auth"],
        mcp_url=mcp_url,
        mode=payload.mode,
        token=plaintext,
        smoke_test=smoke,
        config=material["config"],
        deeplink=material["deeplink"],
        install_command=material["install_command"],
        docs_url=material["docs_url"],
    )
