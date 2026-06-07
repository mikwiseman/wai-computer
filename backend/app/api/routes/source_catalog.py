"""GET /api/source-catalog — the Hermes-style data-source catalog.

Backend-served single source of truth so web / Mac / iOS render the same
categorized connect list and we can add or flip providers without a client
release. Read-only; auth-gated like the rest of the app.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.core.source_catalog import catalog_payload

router = APIRouter(prefix="/source-catalog", tags=["source-catalog"])


@router.get("")
async def get_source_catalog(user: CurrentUser) -> dict:
    return catalog_payload()
