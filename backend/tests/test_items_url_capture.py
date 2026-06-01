"""Route test: POST /items with a URL (no body) enqueues processing."""

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.asyncio


async def test_post_url_only_item_enqueues_processing(client, auth_headers) -> None:
    with patch(
        "app.tasks.item_summary_generation.generate_item_summary_task.delay"
    ) as delay:
        resp = await client.post(
            "/api/items",
            json={"source": "url", "kind": "video", "url": "https://youtu.be/dQw4w9WgXcQ"},
            headers=auth_headers,
        )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["url"] == "https://youtu.be/dQw4w9WgXcQ"
    assert data["state"] == "raw"
    # Background processing (fetch + summarize) was enqueued even with no body.
    delay.assert_called_once()


async def test_post_url_only_item_is_idempotent_by_url(client, auth_headers) -> None:
    payload = {"source": "url", "url": "https://example.com/article-1"}
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        first = await client.post("/api/items", json=payload, headers=auth_headers)
        second = await client.post("/api/items", json=payload, headers=auth_headers)
    assert first.json()["id"] == second.json()["id"]
    listing = await client.get("/api/items", headers=auth_headers)
    assert listing.json()["total"] == 1
