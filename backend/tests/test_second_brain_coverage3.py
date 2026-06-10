"""Third coverage pass: comparison routes GET/DELETE."""

from unittest.mock import patch
from uuid import uuid4

import pytest


async def _fake_embeddings(texts):
    return [[0.01] * 1536 for _ in texts]


async def _make_two_items(client, auth_headers) -> list[str]:
    ids = []
    with (
        patch("app.core.item_ingest.generate_embeddings", _fake_embeddings),
        patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"),
    ):
        for i in range(2):
            r = await client.post(
                "/api/items",
                json={"source": "paste", "kind": "note", "body": f"b{i} content"},
                headers=auth_headers,
            )
            ids.append(r.json()["id"])
    return ids


@pytest.mark.asyncio
async def test_comparison_get_and_delete_roundtrip(client, auth_headers) -> None:
    ids = await _make_two_items(client, auth_headers)
    with patch("app.tasks.comparison_generation.generate_comparison_task.delay"):
        created = await client.post(
            "/api/comparisons", json={"item_ids": ids}, headers=auth_headers
        )
    cid = created.json()["id"]

    # GET happy path.
    got = await client.get(f"/api/comparisons/{cid}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["id"] == cid

    # DELETE happy path, then 404 on re-get + re-delete.
    deleted = await client.delete(f"/api/comparisons/{cid}", headers=auth_headers)
    assert deleted.status_code == 204
    assert (await client.get(f"/api/comparisons/{cid}", headers=auth_headers)).status_code == 404
    assert (
        await client.delete(f"/api/comparisons/{cid}", headers=auth_headers)
    ).status_code == 404


@pytest.mark.asyncio
async def test_comparison_get_missing_404(client, auth_headers) -> None:
    resp = await client.get(f"/api/comparisons/{uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
