"""API tests for the universal /items routes (Phase 1).

Background summarization is disabled in these tests by stubbing the Celery
task's ``.delay`` (the route imports it lazily), so we assert the synchronous
capture + feed + detail behaviour without a broker or OpenAI.
"""

from unittest.mock import patch

import pytest

from app.api.routes.items import _derive_status, _item_error
from app.models.item import Item

pytestmark = pytest.mark.asyncio


async def test_create_item_requires_body_or_url(client, auth_headers) -> None:
    resp = await client.post("/api/items", json={"source": "paste"}, headers=auth_headers)
    assert resp.status_code == 400


async def test_create_item_paste_and_fetch_detail(client, auth_headers) -> None:
    with patch(
        "app.tasks.item_summary_generation.generate_item_summary_task.delay"
    ) as delay:
        resp = await client.post(
            "/api/items",
            json={
                "source": "paste",
                "kind": "note",
                "title": "My note",
                "body": "A paragraph about solar energy and storage economics.",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["title"] == "My note"
    assert data["state"] == "raw"
    item_id = data["id"]
    # Background summarization was enqueued (not run inline).
    delay.assert_called_once()

    # Detail round-trips.
    detail = await client.get(f"/api/items/{item_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == item_id


async def test_create_item_is_idempotent(client, auth_headers) -> None:
    payload = {"source": "paste", "title": "Dup", "body": "same content here"}
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        first = await client.post("/api/items", json=payload, headers=auth_headers)
        second = await client.post("/api/items", json=payload, headers=auth_headers)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    listing = await client.get("/api/items", headers=auth_headers)
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1


async def test_list_items_filters_by_kind(client, auth_headers) -> None:
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        await client.post(
            "/api/items",
            json={"source": "paste", "kind": "article", "body": "article body one"},
            headers=auth_headers,
        )
        await client.post(
            "/api/items",
            json={"source": "paste", "kind": "note", "body": "note body two"},
            headers=auth_headers,
        )
    articles = await client.get("/api/items?kind=article", headers=auth_headers)
    assert articles.status_code == 200
    data = articles.json()
    assert data["total"] == 1
    assert data["items"][0]["kind"] == "article"


async def test_items_scoped_to_user(client, auth_headers) -> None:
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        created = await client.post(
            "/api/items",
            json={"source": "paste", "body": "private to user A"},
            headers=auth_headers,
        )
    item_id = created.json()["id"]

    # A different user cannot read it.
    from uuid import uuid4

    other = await client.post(
        "/api/auth/register",
        json={
            "email": f"other-{uuid4().hex}@example.com",
            "password": "testpassword123",
            "accepted_legal_terms": True,
            "legal_terms_version": "2026-05-22",
            "legal_privacy_version": "2026-05-22",
        },
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    denied = await client.get(f"/api/items/{item_id}", headers=other_headers)
    assert denied.status_code == 404


async def test_delete_item_soft_deletes(client, auth_headers) -> None:
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        created = await client.post(
            "/api/items",
            json={"source": "paste", "body": "to be deleted"},
            headers=auth_headers,
        )
    item_id = created.json()["id"]
    deleted = await client.delete(f"/api/items/{item_id}", headers=auth_headers)
    assert deleted.status_code == 204
    gone = await client.get(f"/api/items/{item_id}", headers=auth_headers)
    assert gone.status_code == 404
    listing = await client.get("/api/items", headers=auth_headers)
    assert listing.json()["total"] == 0


async def test_derive_status_covers_every_state() -> None:
    assert _derive_status(Item(state="needs_input"), False) == "needs_input"
    assert _derive_status(Item(state="failed"), False) == "failed"
    assert (
        _derive_status(
            Item(state="raw", metadata_={"processing_error": {"code": "x", "message": "y"}}),
            False,
        )
        == "failed"
    )
    assert _derive_status(Item(state="raw", body="hello"), True) == "ready"
    assert _derive_status(Item(state="promoted", body="x"), True) == "ready"
    assert (
        _derive_status(Item(state="raw", url="https://e.com", body=None), False) == "fetching"
    )
    assert (
        _derive_status(Item(state="raw", body="has body", url=None), False) == "summarizing"
    )


async def test_item_error_surfaces_fetch_and_processing_errors() -> None:
    assert _item_error(Item(metadata_=None)) is None
    assert _item_error(Item(metadata_={})) is None
    fe = _item_error(
        Item(
            metadata_={
                "fetch_error": {"code": "youtube_no_transcript", "message": "Share the file"}
            }
        )
    )
    assert fe is not None and fe.code == "youtube_no_transcript"
    pe = _item_error(
        Item(metadata_={"processing_error": {"code": "enqueue_failed", "message": "Retry"}})
    )
    assert pe is not None and pe.code == "enqueue_failed"


async def test_create_item_exposes_summarizing_status(client, auth_headers) -> None:
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        resp = await client.post(
            "/api/items",
            json={"source": "paste", "body": "notes on solar storage economics"},
            headers=auth_headers,
        )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "summarizing"
    assert data["error"] is None


async def test_create_item_enqueue_failure_is_visible_not_swallowed(
    client, auth_headers
) -> None:
    with patch(
        "app.tasks.item_summary_generation.generate_item_summary_task.delay",
        side_effect=RuntimeError("broker down"),
    ):
        resp = await client.post(
            "/api/items",
            json={"source": "paste", "body": "this item cannot be enqueued"},
            headers=auth_headers,
        )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["state"] == "failed"
    assert data["status"] == "failed"
    assert data["error"]["code"] == "enqueue_failed"

    # The failure is also visible in the unified feed (not silently dropped).
    listing = await client.get("/api/items", headers=auth_headers)
    entry = next(e for e in listing.json()["items"] if e["id"] == data["id"])
    assert entry["status"] == "failed"
    assert entry["error"]["code"] == "enqueue_failed"
