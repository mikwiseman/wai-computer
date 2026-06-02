"""API + build tests for comparison sets."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core import comparison_build
from app.core.comparison import ComparisonItem, ComparisonResult
from app.core.comparison_build import build_comparison_set
from app.core.item_ingest import ingest_item
from app.models.comparison import ComparisonSet
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _embedder(texts):
    return [[0.01] * 1536 for _ in texts]


async def _two_items(client, auth_headers) -> list[str]:
    ids = []
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        for i in range(3):
            r = await client.post(
                "/api/items",
                json={"source": "paste", "kind": "article", "body": f"body {i} about topic {i}"},
                headers=auth_headers,
            )
            ids.append(r.json()["id"])
    return ids


async def test_create_comparison_requires_two_items(client, auth_headers) -> None:
    ids = await _two_items(client, auth_headers)
    resp = await client.post(
        "/api/comparisons", json={"item_ids": [ids[0]]}, headers=auth_headers
    )
    assert resp.status_code == 422  # min_length=2


async def test_create_comparison_enqueues_and_lists(client, auth_headers) -> None:
    ids = await _two_items(client, auth_headers)
    with patch(
        "app.tasks.comparison_generation.generate_comparison_task.delay"
    ) as delay:
        resp = await client.post(
            "/api/comparisons",
            json={"item_ids": ids[:3], "title": "Topics", "intent": "by topic"},
            headers=auth_headers,
        )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "generating"
    assert len(data["item_ids"]) == 3
    delay.assert_called_once()

    listing = await client.get("/api/comparisons", headers=auth_headers)
    assert listing.status_code == 200
    assert listing.json()[0]["item_count"] == 3


async def test_create_comparison_enqueue_failure_marks_failed(client, auth_headers) -> None:
    ids = await _two_items(client, auth_headers)
    with patch(
        "app.tasks.comparison_generation.generate_comparison_task.delay",
        side_effect=RuntimeError("broker down"),
    ):
        resp = await client.post(
            "/api/comparisons", json={"item_ids": ids[:2]}, headers=auth_headers
        )
    # No-fallback: a broker outage must not leave a permanently "generating" row.
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "failed"


async def test_create_comparison_rejects_unowned_item(client, auth_headers) -> None:
    ids = await _two_items(client, auth_headers)
    resp = await client.post(
        "/api/comparisons",
        json={"item_ids": [ids[0], str(uuid4())]},
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_build_comparison_set_persists_table(db_session, monkeypatch) -> None:
    user = User(email=f"cmp-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()

    item_ids = []
    for i in range(2):
        item, _ = await ingest_item(
            db_session, user.id, source="paste", title=f"Item {i}",
            body=f"content {i}", embedder=_embedder,
        )
        item_ids.append(str(item.id))

    cs = ComparisonSet(user_id=user.id, item_ids=item_ids, status="generating")
    db_session.add(cs)
    await db_session.flush()

    async def fake_build(items, *, intent=None, **kwargs):
        assert len(items) == 2
        assert all(isinstance(i, ComparisonItem) for i in items)
        return ComparisonResult(
            columns=[{"name": "Topic", "type": "text"}],
            rows=[
                {"item_id": items[0].item_id, "title": items[0].title,
                 "values": {"Topic": "a"}},
                {"item_id": items[1].item_id, "title": items[1].title,
                 "values": {"Topic": None}},
            ],
            rationale="differentiates topics",
        )

    monkeypatch.setattr(comparison_build, "build_comparison", fake_build)
    await build_comparison_set(db_session, cs.id, intent="by topic")

    refreshed = (
        await db_session.execute(select(ComparisonSet).where(ComparisonSet.id == cs.id))
    ).scalar_one()
    assert refreshed.status == "ready"
    assert refreshed.columns[0]["name"] == "Topic"
    assert len(refreshed.rows) == 2
    assert refreshed.rows[1]["values"]["Topic"] is None
    assert refreshed.title  # auto-titled


async def test_create_comparison_dedupes_and_requires_two_distinct(client, auth_headers) -> None:
    ids = await _two_items(client, auth_headers)
    # Two references to the SAME item dedupe to 1 distinct -> 422 (not a self-compare).
    resp = await client.post(
        "/api/comparisons", json={"item_ids": [ids[0], ids[0]]}, headers=auth_headers
    )
    assert resp.status_code == 422


async def test_create_comparison_persists_and_echoes_intent(client, auth_headers) -> None:
    ids = await _two_items(client, auth_headers)
    with patch("app.tasks.comparison_generation.generate_comparison_task.delay"):
        resp = await client.post(
            "/api/comparisons",
            json={"item_ids": ids[:2], "intent": "which is cheaper"},
            headers=auth_headers,
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["intent"] == "which is cheaper"
    cid = resp.json()["id"]
    got = await client.get(f"/api/comparisons/{cid}", headers=auth_headers)
    assert got.json()["intent"] == "which is cheaper"


async def test_rebuild_comparison_re_enqueues_with_stored_intent(client, auth_headers) -> None:
    ids = await _two_items(client, auth_headers)
    with patch("app.tasks.comparison_generation.generate_comparison_task.delay"):
        created = await client.post(
            "/api/comparisons",
            json={"item_ids": ids[:2], "intent": "by topic"},
            headers=auth_headers,
        )
    cid = created.json()["id"]
    with patch("app.tasks.comparison_generation.generate_comparison_task.delay") as delay:
        resp = await client.post(f"/api/comparisons/{cid}/rebuild", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "generating"
    delay.assert_called_once_with(comparison_id=cid, intent="by topic")


async def test_rebuild_comparison_404_for_unknown(client, auth_headers) -> None:
    resp = await client.post(f"/api/comparisons/{uuid4()}/rebuild", headers=auth_headers)
    assert resp.status_code == 404


async def test_build_fails_when_too_few_items_survive(db_session) -> None:
    from datetime import datetime, timezone

    user = User(email=f"cmpd-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    items = []
    for i in range(2):
        it, _ = await ingest_item(
            db_session, user.id, source="paste", title=f"D{i}", body=f"c{i}",
            embedder=_embedder,
        )
        items.append(it)
    cs = ComparisonSet(
        user_id=user.id, item_ids=[str(it.id) for it in items], status="generating"
    )
    db_session.add(cs)
    await db_session.flush()
    # Soft-delete one -> only 1 distinct item survives -> can't compare.
    items[0].deleted_at = datetime.now(timezone.utc)
    await db_session.flush()

    result = await build_comparison_set(db_session, cs.id)
    assert result is not None and result.status == "failed"
    assert "available" in (result.schema_rationale or "").lower()


async def test_build_excludes_deleted_items_and_notes_it(db_session, monkeypatch) -> None:
    from datetime import datetime, timezone

    user = User(email=f"cmpx-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    items = []
    for i in range(3):
        it, _ = await ingest_item(
            db_session, user.id, source="paste", title=f"X{i}", body=f"c{i}",
            embedder=_embedder,
        )
        items.append(it)
    cs = ComparisonSet(
        user_id=user.id, item_ids=[str(it.id) for it in items], status="generating"
    )
    db_session.add(cs)
    await db_session.flush()
    items[1].deleted_at = datetime.now(timezone.utc)
    await db_session.flush()

    async def fake_build(items_arg, *, intent=None, **kwargs):
        assert len(items_arg) == 2  # the deleted item is excluded, not silently kept
        return ComparisonResult(
            columns=[{"name": "Topic", "type": "text"}],
            rows=[
                {"item_id": items_arg[0].item_id, "title": items_arg[0].title,
                 "values": {"Topic": "a"}},
            ],
            rationale="ok",
        )

    monkeypatch.setattr(comparison_build, "build_comparison", fake_build)
    result = await build_comparison_set(db_session, cs.id)
    assert result.status == "ready"
    assert "excluded" in (result.schema_rationale or "").lower()
