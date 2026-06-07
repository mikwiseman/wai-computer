"""Tests for the source catalog: data integrity, endpoint, and catalog connect."""

from unittest.mock import patch

import pytest

from app.core.source_catalog import (
    BACKFILL_DEPTHS,
    CatalogEntry,
    catalog_payload,
    get_entry,
)

pytestmark = pytest.mark.asyncio


# ── data integrity (pure) ───────────────────────────────────────────────────
def test_catalog_payload_is_consistent():
    payload = catalog_payload()
    assert payload["version"] >= 1
    cat_ids = {c["id"] for c in payload["categories"]}
    assert payload["default_backfill_depth"] in payload["backfill_depths"]
    assert set(payload["backfill_depths"]) == set(BACKFILL_DEPTHS)
    assert payload["entries"], "catalog must list providers"
    for e in payload["entries"]:
        assert e["category"] in cat_ids, e["id"]
        assert e["auth_type"] in {"none", "pat", "oauth"}, e["id"]
        assert e["status"] in {"available", "coming_soon"}, e["id"]
        assert e["server_url"].startswith("https://"), e["id"]
        assert e["tagline_en"] and e["tagline_ru"], e["id"]


def test_get_entry():
    assert get_entry("notion") is not None
    assert get_entry("nope") is None


# ── endpoint ────────────────────────────────────────────────────────────────
async def test_source_catalog_endpoint(client, auth_headers):
    resp = await client.get("/api/source-catalog", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert {e["id"] for e in data["entries"]} >= {"gmail", "notion", "telegram"}


async def test_source_catalog_requires_auth(client):
    resp = await client.get("/api/source-catalog")
    assert resp.status_code == 401


# ── connect via catalog tile ────────────────────────────────────────────────
class _FakeIntro:
    tools = ["search", "fetch"]
    resources = []


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    async def introspect(self):
        return _FakeIntro()


def _entry(**kw) -> CatalogEntry:
    base = dict(
        id="testsrc", name="Test Source", category="notes", icon="custom",
        tagline_en="t", tagline_ru="т", syncs_en="s", syncs_ru="с",
        auth_type="none", server_url="https://mcp.example.com/test", status="available",
    )
    base.update(kw)
    return CatalogEntry(**base)


async def test_connect_via_catalog_id(client, auth_headers):
    fake = _entry(auth_type="none", status="available")
    with patch("app.api.routes.mcp_connections.get_entry", return_value=fake), \
         patch("app.core.mcp_client.McpClient", _FakeClient):
        resp = await client.post(
            "/api/mcp-connections",
            json={"catalog_id": "testsrc", "backfill_depth": "recent_90d"},
            headers=auth_headers,
        )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["catalog_id"] == "testsrc"
    assert data["source_type"] == "testsrc"
    assert data["backfill_depth"] == "recent_90d"
    assert data["server_label"] == "Test Source"  # defaulted from the tile
    assert data["item_count"] == 0


async def test_connect_coming_soon_tile_rejected(client, auth_headers):
    fake = _entry(status="coming_soon")
    with patch("app.api.routes.mcp_connections.get_entry", return_value=fake):
        resp = await client.post(
            "/api/mcp-connections", json={"catalog_id": "testsrc"}, headers=auth_headers
        )
    assert resp.status_code == 400


async def test_connect_oauth_tile_not_implemented(client, auth_headers):
    fake = _entry(auth_type="oauth", status="available")
    with patch("app.api.routes.mcp_connections.get_entry", return_value=fake):
        resp = await client.post(
            "/api/mcp-connections", json={"catalog_id": "testsrc"}, headers=auth_headers
        )
    assert resp.status_code == 501


async def test_connect_requires_exactly_one_source(client, auth_headers):
    # Neither catalog_id nor server_url.
    r1 = await client.post("/api/mcp-connections", json={"server_label": "X"}, headers=auth_headers)
    assert r1.status_code == 422
    # Both.
    r2 = await client.post(
        "/api/mcp-connections",
        json={"catalog_id": "notion", "server_url": "https://x.com/mcp"},
        headers=auth_headers,
    )
    assert r2.status_code == 422
