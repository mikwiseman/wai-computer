"""API tests for the Schemes board surface.

Schemes are the product-facing board view over the existing Brain Maps engine:
they expose a cited projection plus an editable infinite-canvas layout without
duplicating the underlying map/revision tables.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_create_list_get_and_update_scheme_layout(client, auth_headers, monkeypatch) -> None:
    async def fake_search(*_args, **_kwargs):
        return []

    monkeypatch.setattr("app.core.brain_maps.unified_search", fake_search)

    created = await client.post(
        "/api/schemes",
        headers=auth_headers,
        json={"prompt": "Map my active projects and risks"},
    )

    assert created.status_code == 201, created.text
    payload = created.json()
    scheme_id = payload["id"]
    assert payload["title"] == "Map my active projects and risks"
    assert payload["scheme_type"] == "project_state"
    assert payload["current_revision"]["projection"]["nodes"]

    node_id = payload["current_revision"]["projection"]["nodes"][0]["id"]
    layout = {
        "version": 8,
        "snap_to_grid": True,
        "grid_size": 40,
        "viewport": {"x": 20, "y": -10, "zoom": 1.2},
        "node_positions": {node_id: {"x": 128.5, "y": -64.25}},
        "strokes": [
            {
                "id": "stroke-1",
                "points": [{"x": 1, "y": 2, "pressure": 0.5}, {"x": 12, "y": 18, "pressure": 0.72}],
                "kind": "highlighter",
                "color": "#facc15",
                "width": 14,
                "opacity": 0.35,
                "locked": True,
                "z_index": 11,
            }
        ],
        "cards": [
            {
                "id": "card-1",
                "x": 50,
                "y": 80,
                "width": 220,
                "height": 140,
                "text": "Open issue",
                "color": "#f7d774",
                "locked": True,
                "z_index": 60,
            }
        ],
        "shapes": [
            {
                "id": "shape-1",
                "kind": "rectangle",
                "x": -100,
                "y": 20,
                "width": 240,
                "height": 120,
                "color": "#2563eb",
                "fill": "transparent",
                "locked": True,
                "z_index": 30,
            }
        ],
        "frames": [
            {
                "id": "frame-1",
                "x": -180,
                "y": -120,
                "width": 520,
                "height": 360,
                "title": "Launch plan",
                "color": "#0f766e",
                "fill": "transparent",
                "locked": True,
                "z_index": 20,
            }
        ],
        "texts": [
            {
                "id": "text-1",
                "x": 280,
                "y": 160,
                "width": 260,
                "height": 120,
                "text": "Decision context",
                "color": "#111827",
                "font_size": 22,
                "locked": True,
                "z_index": 50,
            }
        ],
        "sources": [
            {
                "id": "source-block-item-1",
                "source_kind": "item",
                "source_id": "11111111-1111-1111-1111-111111111111",
                "citation_id": "item:11111111-1111-1111-1111-111111111111",
                "x": -520,
                "y": 120,
                "width": 320,
                "height": 170,
                "title": "Launch memo",
                "subtitle": "material",
                "excerpt": "Evidence captured from materials.",
                "color": "#eef2ff",
                "locked": True,
                "z_index": 55,
            }
        ],
        "connectors": [
            {
                "id": "connector-1",
                "source_id": node_id,
                "target_id": "card-1",
                "points": [],
                "label": "blocks",
                "color": "#475569",
                "locked": True,
                "z_index": 10,
            }
        ],
    }
    updated = await client.patch(
        f"/api/schemes/{scheme_id}",
        headers=auth_headers,
        json={"layout": layout},
    )

    assert updated.status_code == 200, updated.text
    updated_payload = updated.json()
    assert updated_payload["layout"] == layout
    assert updated_payload["layout"]["sources"][0]["citation_id"].startswith("item:")
    updated_node = next(
        node
        for node in updated_payload["current_revision"]["projection"]["nodes"]
        if node["id"] == node_id
    )
    assert updated_node["position"] == {"x": 128.5, "y": -64.25}

    listing = await client.get("/api/schemes", headers=auth_headers)
    assert listing.status_code == 200
    assert listing.json()["schemes"][0]["id"] == scheme_id

    detail = await client.get(f"/api/schemes/{scheme_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == scheme_id


async def test_scheme_routes_migrate_legacy_node_position_layout(
    client, auth_headers, monkeypatch
) -> None:
    async def fake_search(*_args, **_kwargs):
        return []

    monkeypatch.setattr("app.core.brain_maps.unified_search", fake_search)

    created = await client.post(
        "/api/schemes",
        headers=auth_headers,
        json={"prompt": "Map recent decisions"},
    )
    assert created.status_code == 201, created.text
    node_id = created.json()["current_revision"]["projection"]["nodes"][0]["id"]

    migrated = await client.patch(
        f"/api/schemes/{created.json()['id']}",
        headers=auth_headers,
        json={"layout": {node_id: {"x": 40, "y": 80}}},
    )

    assert migrated.status_code == 200, migrated.text
    assert migrated.json()["layout"]["version"] == 8
    assert migrated.json()["layout"]["snap_to_grid"] is False
    assert migrated.json()["layout"]["grid_size"] == 40
    assert migrated.json()["layout"]["node_positions"] == {node_id: {"x": 40.0, "y": 80.0}}
    assert migrated.json()["layout"]["cards"] == []
    assert migrated.json()["layout"]["sources"] == []


async def test_scheme_routes_validate_layout_shape(client, auth_headers, monkeypatch) -> None:
    async def fake_search(*_args, **_kwargs):
        return []

    monkeypatch.setattr("app.core.brain_maps.unified_search", fake_search)

    created = await client.post(
        "/api/schemes",
        headers=auth_headers,
        json={"prompt": "Map recent decisions"},
    )
    assert created.status_code == 201, created.text

    invalid = await client.patch(
        f"/api/schemes/{created.json()['id']}",
        headers=auth_headers,
        json={"layout": {"version": 2, "node_positions": {"lens:root": {"x": "left", "y": 0}}}},
    )

    assert invalid.status_code == 422

    invalid_grid = await client.patch(
        f"/api/schemes/{created.json()['id']}",
        headers=auth_headers,
        json={"layout": {"version": 8, "grid_size": 4}},
    )

    assert invalid_grid.status_code == 422

    unsupported_shape = await client.patch(
        f"/api/schemes/{created.json()['id']}",
        headers=auth_headers,
        json={
            "layout": {
                "version": 8,
                "shapes": [
                    {
                        "id": "shape-bad",
                        "kind": "star",
                        "x": 0,
                        "y": 0,
                        "width": 120,
                        "height": 90,
                    }
                ],
            }
        },
    )

    assert unsupported_shape.status_code == 422

    unsupported_source = await client.patch(
        f"/api/schemes/{created.json()['id']}",
        headers=auth_headers,
        json={
            "layout": {
                "version": 8,
                "sources": [
                    {
                        "id": "source-bad",
                        "source_kind": "calendar",
                        "source_id": "calendar-1",
                        "citation_id": "calendar:calendar-1",
                        "x": 0,
                        "y": 0,
                        "width": 320,
                        "height": 160,
                        "title": "Calendar event",
                    }
                ],
            }
        },
    )

    assert unsupported_source.status_code == 422

    unsupported_stroke = await client.patch(
        f"/api/schemes/{created.json()['id']}",
        headers=auth_headers,
        json={
            "layout": {
                "version": 8,
                "strokes": [
                    {
                        "id": "stroke-bad",
                        "points": [{"x": 0, "y": 0}, {"x": 10, "y": 10}],
                        "kind": "airbrush",
                    }
                ],
            }
        },
    )

    assert unsupported_stroke.status_code == 422


async def test_scheme_routes_are_user_scoped(client, auth_headers, monkeypatch) -> None:
    async def fake_search(*_args, **_kwargs):
        return []

    monkeypatch.setattr("app.core.brain_maps.unified_search", fake_search)

    created = await client.post(
        "/api/schemes",
        headers=auth_headers,
        json={"prompt": "Map private work"},
    )
    assert created.status_code == 201, created.text

    other = await client.post(
        "/api/auth/register",
        json={
            "email": "scheme-other@example.com",
            "password": "testpassword123",
            "accepted_legal_terms": True,
            "legal_terms_version": "2026-05-22",
            "legal_privacy_version": "2026-05-22",
        },
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    denied = await client.get(f"/api/schemes/{created.json()['id']}", headers=other_headers)
    assert denied.status_code == 404
