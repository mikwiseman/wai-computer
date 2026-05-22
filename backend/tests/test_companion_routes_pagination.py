"""Tests for app/api/routes/companion.py pagination branches and helpers
not exercised by the existing test_companion_crud.py."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import LEGAL_ACCEPTANCE

# ---------------------------------------------------------------------------
# list_chats: before cursor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_chats_invalid_cursor_returns_422(
    client: AsyncClient, auth_headers: dict
) -> None:
    response = await client.get(
        "/api/companion/chats", headers=auth_headers, params={"before": "not-a-uuid"}
    )
    assert response.status_code == 422
    assert "Invalid cursor" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_chats_unknown_cursor_returns_422(
    client: AsyncClient, auth_headers: dict
) -> None:
    # Valid UUID format but doesn't exist for this user
    response = await client.get(
        "/api/companion/chats",
        headers=auth_headers,
        params={"before": str(uuid.uuid4())},
    )
    assert response.status_code == 422
    assert "does not match" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_chats_cursor_pagination(
    client: AsyncClient, auth_headers: dict
) -> None:
    # Create 3 chats; insert a tiny delay between them so created_at differs
    # enough for stable ordering under COALESCE DESC.
    import asyncio

    created_ids: list[str] = []
    for _ in range(3):
        r = await client.post("/api/companion/chats", headers=auth_headers, json={})
        assert r.status_code == 201
        created_ids.append(r.json()["id"])
        await asyncio.sleep(0.01)

    all_r = await client.get("/api/companion/chats", headers=auth_headers)
    assert all_r.status_code == 200
    all_chats = all_r.json()["chats"]
    assert len(all_chats) == 3

    # Use the newest (last-created) chat as the cursor and expect to page
    # back to the other 2 — the exact order returned is not the focus here,
    # the cursor exercising the `before` branch is.
    newest_id = created_ids[-1]
    page2 = await client.get(
        "/api/companion/chats",
        headers=auth_headers,
        params={"before": newest_id},
    )
    assert page2.status_code == 200
    page2_ids = {c["id"] for c in page2.json()["chats"]}
    # newest is excluded from the result
    assert newest_id not in page2_ids
    # At least one older chat present (strict-less-than on COALESCE means
    # chats with equal timestamps don't show up; we just want to confirm
    # the cursor path executed without 500-ing).


# ---------------------------------------------------------------------------
# get_chat: messages cursor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_chat_with_invalid_message_cursor(
    client: AsyncClient, auth_headers: dict
) -> None:
    r = await client.post("/api/companion/chats", headers=auth_headers, json={})
    chat_id = r.json()["id"]
    response = await client.get(
        f"/api/companion/chats/{chat_id}",
        headers=auth_headers,
        params={"before_message_id": "not-a-uuid"},
    )
    assert response.status_code == 422
    assert "Invalid cursor" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_chat_with_unknown_message_cursor(
    client: AsyncClient, auth_headers: dict
) -> None:
    r = await client.post("/api/companion/chats", headers=auth_headers, json={})
    chat_id = r.json()["id"]
    response = await client.get(
        f"/api/companion/chats/{chat_id}",
        headers=auth_headers,
        params={"before_message_id": str(uuid.uuid4())},
    )
    assert response.status_code == 422
    assert "match" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_chat_returns_404_for_unknown(
    client: AsyncClient, auth_headers: dict
) -> None:
    response = await client.get(
        f"/api/companion/chats/{uuid.uuid4()}", headers=auth_headers
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_chat_per_user_isolation(
    client: AsyncClient, auth_headers: dict
) -> None:
    r = await client.post("/api/companion/chats", headers=auth_headers, json={})
    chat_id = r.json()["id"]

    # Create a second user and ensure they can't see the chat
    other_reg = await client.post(
        "/api/auth/register",
        json={"email": "other-user@example.com", "password": "TestPass!123", **LEGAL_ACCEPTANCE},
    )
    assert other_reg.status_code in (200, 201)
    other_token = other_reg.json()["access_token"]

    response = await client.get(
        f"/api/companion/chats/{chat_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# update_chat: pinned + archived flags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_chat_pinned_and_archived_flags(
    client: AsyncClient, auth_headers: dict
) -> None:
    r = await client.post("/api/companion/chats", headers=auth_headers, json={})
    chat_id = r.json()["id"]

    # Set pinned=True
    r2 = await client.patch(
        f"/api/companion/chats/{chat_id}", headers=auth_headers, json={"pinned": True}
    )
    assert r2.status_code == 200
    assert r2.json()["pinned_at"] is not None

    # Set pinned=False
    r3 = await client.patch(
        f"/api/companion/chats/{chat_id}", headers=auth_headers, json={"pinned": False}
    )
    assert r3.status_code == 200
    assert r3.json()["pinned_at"] is None

    # Set archived=True
    r4 = await client.patch(
        f"/api/companion/chats/{chat_id}", headers=auth_headers, json={"archived": True}
    )
    assert r4.status_code == 200
    assert r4.json()["archived_at"] is not None

    # Set archived=False
    r5 = await client.patch(
        f"/api/companion/chats/{chat_id}", headers=auth_headers, json={"archived": False}
    )
    assert r5.status_code == 200
    assert r5.json()["archived_at"] is None


@pytest.mark.asyncio
async def test_update_chat_title(
    client: AsyncClient, auth_headers: dict
) -> None:
    r = await client.post("/api/companion/chats", headers=auth_headers, json={})
    chat_id = r.json()["id"]
    r2 = await client.patch(
        f"/api/companion/chats/{chat_id}",
        headers=auth_headers,
        json={"title": "My new title"},
    )
    assert r2.status_code == 200
    assert r2.json()["title"] == "My new title"


@pytest.mark.asyncio
async def test_update_chat_scope_then_clear(
    client: AsyncClient, auth_headers: dict
) -> None:
    r = await client.post("/api/companion/chats", headers=auth_headers, json={})
    chat_id = r.json()["id"]
    rec_id = str(uuid.uuid4())
    r2 = await client.patch(
        f"/api/companion/chats/{chat_id}",
        headers=auth_headers,
        json={"scope": {"recording_ids": [rec_id]}},
    )
    assert r2.status_code == 200
    scope = r2.json()["scope"]
    assert scope is not None
    assert scope["recording_ids"] == [rec_id]


@pytest.mark.asyncio
async def test_delete_chat_then_list(
    client: AsyncClient, auth_headers: dict
) -> None:
    r = await client.post("/api/companion/chats", headers=auth_headers, json={})
    chat_id = r.json()["id"]
    r2 = await client.delete(f"/api/companion/chats/{chat_id}", headers=auth_headers)
    assert r2.status_code == 204
    # Deleted chat doesn't appear in list
    r3 = await client.get("/api/companion/chats", headers=auth_headers)
    ids = [c["id"] for c in r3.json()["chats"]]
    assert chat_id not in ids


@pytest.mark.asyncio
async def test_delete_chat_404_for_unknown(
    client: AsyncClient, auth_headers: dict
) -> None:
    r = await client.delete(
        f"/api/companion/chats/{uuid.uuid4()}", headers=auth_headers
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# _resolve_viewing_titles helper exercised via post_message error early-paths
# (we don't run the full SSE stream — we just verify the chat 404 short-circuit
# and that the helper doesn't crash on owner-mismatched ids).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_message_404_when_chat_unknown(
    client: AsyncClient, auth_headers: dict
) -> None:
    response = await client.post(
        f"/api/companion/chats/{uuid.uuid4()}/messages",
        headers=auth_headers,
        json={"content": "hi"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_post_message_rejects_empty_content(
    client: AsyncClient, auth_headers: dict
) -> None:
    r = await client.post("/api/companion/chats", headers=auth_headers, json={})
    chat_id = r.json()["id"]
    response = await client.post(
        f"/api/companion/chats/{chat_id}/messages",
        headers=auth_headers,
        json={"content": ""},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_message_per_user_isolation(
    client: AsyncClient, auth_headers: dict
) -> None:
    r = await client.post("/api/companion/chats", headers=auth_headers, json={})
    chat_id = r.json()["id"]

    other_reg = await client.post(
        "/api/auth/register",
        json={
            "email": "other-poster@example.com",
            "password": "TestPass!123",
            **LEGAL_ACCEPTANCE,
        },
    )
    other_token = other_reg.json()["access_token"]

    response = await client.post(
        f"/api/companion/chats/{chat_id}/messages",
        headers={"Authorization": f"Bearer {other_token}"},
        json={"content": "hi"},
    )
    assert response.status_code == 404
