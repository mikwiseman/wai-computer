"""Tests for the universal inbox read model."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.companion import ChatMessage, Conversation
from app.models.item import Item, ItemSummary
from app.models.recording import Folder, Recording, Summary
from app.models.user import User
from tests.conftest import LEGAL_ACCEPTANCE

pytestmark = pytest.mark.asyncio


def _encoded_cursor(payload: dict[str, str]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


async def _current_user_id(client: AsyncClient, headers: dict) -> str:
    resp = await client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _seed_mixed_inbox(db: AsyncSession, user_id) -> dict[str, object]:
    now = datetime.now(timezone.utc).replace(microsecond=0)

    folder = Folder(user_id=user_id, name="Research")
    db.add(folder)
    await db.flush()

    recording = Recording(
        user_id=user_id,
        folder_id=folder.id,
        title="Product sync",
        type="meeting",
        status="ready",
        duration_seconds=1840,
        language="en",
        created_at=now - timedelta(minutes=30),
    )
    processing_recording = Recording(
        user_id=user_id,
        title="Voice memo",
        type="note",
        status="processing",
        created_at=now - timedelta(minutes=25),
    )
    failed_recording = Recording(
        user_id=user_id,
        title="Bad import",
        type="meeting",
        status="failed",
        failure_code="transcription_failed",
        failure_message="The file could not be transcribed.",
        created_at=now - timedelta(minutes=20),
    )
    db.add_all([recording, processing_recording, failed_recording])
    await db.flush()
    db.add(Summary(recording_id=recording.id, summary="A private summary."))

    item = Item(
        user_id=user_id,
        folder_id=folder.id,
        source="upload",
        kind="pdf",
        title="Market memo",
        body="This body is private and must not appear in inbox rows.",
        content_hash=uuid4().hex,
        created_at=now - timedelta(minutes=10),
    )
    needs_input_item = Item(
        user_id=user_id,
        source="url",
        kind="article",
        title="Blocked article",
        url="https://example.com/blocked",
        content_hash=uuid4().hex,
        state="needs_input",
        metadata_={
            "fetch_error": {
                "code": "source_needs_login",
                "message": "Open the source and paste the text.",
            }
        },
        created_at=now - timedelta(minutes=5),
    )
    db.add_all([item, needs_input_item])
    await db.flush()
    db.add(ItemSummary(item_id=item.id, summary="A private material summary."))

    chat = Conversation(
        user_id=user_id,
        title="Ask Wai about launch",
        last_message_at=now,
        created_at=now - timedelta(hours=1),
    )
    archived_chat = Conversation(
        user_id=user_id,
        title="Archived chat",
        archived_at=now,
        last_message_at=now + timedelta(minutes=1),
        created_at=now - timedelta(hours=1),
    )
    db.add_all([chat, archived_chat])
    await db.flush()
    db.add(
        ChatMessage(
            conversation_id=chat.id,
            role="user",
            content={"text": "Private chat prompt that must not be previewed."},
        )
    )

    other = User(email=f"inbox-other-{uuid4().hex}@example.com", password_hash="x")
    db.add(other)
    await db.flush()
    db.add(
        Recording(
            user_id=other.id,
            title="Other user recording",
            type="meeting",
            status="ready",
            created_at=now + timedelta(minutes=5),
        )
    )

    await db.commit()
    return {
        "folder": folder,
        "recording": recording,
        "processing_recording": processing_recording,
        "failed_recording": failed_recording,
        "item": item,
        "needs_input_item": needs_input_item,
        "chat": chat,
        "archived_chat": archived_chat,
    }


async def test_inbox_returns_mixed_newest_first_privacy_safe_rows(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
) -> None:
    user_id = await _current_user_id(client, auth_headers)
    seeded = await _seed_mixed_inbox(db_session, user_id)

    resp = await client.get("/api/inbox", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    rows = data["rows"]
    assert [row["source_kind"] for row in rows] == [
        "item",
        "item",
        "recording",
        "recording",
        "recording",
    ]
    assert rows[0]["status"] == "needs_input"
    assert rows[1]["has_summary"] is True
    assert rows[2]["status"] == "failed"
    assert rows[2]["error"]["code"] == "transcription_failed"
    assert rows[4]["folder_id"] == str(seeded["folder"].id)
    assert f"chat:{seeded['chat'].id}" not in {row["id"] for row in rows}
    assert all("body" not in row for row in rows)
    assert all("messages" not in row for row in rows)
    assert "Private" not in str(rows)
    assert data["has_more"] is False
    assert data["next_cursor"] is None


async def test_inbox_filters_by_source_status_and_folder(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
) -> None:
    user_id = await _current_user_id(client, auth_headers)
    seeded = await _seed_mixed_inbox(db_session, user_id)

    material_resp = await client.get(
        "/api/inbox", headers=auth_headers, params={"source_kind": "item"}
    )
    assert material_resp.status_code == 200
    assert {row["source_kind"] for row in material_resp.json()["rows"]} == {"item"}

    processing_resp = await client.get(
        "/api/inbox", headers=auth_headers, params={"status": "processing"}
    )
    assert processing_resp.status_code == 200
    assert processing_resp.json()["rows"] == [
        {
            **processing_resp.json()["rows"][0],
            "id": f"recording:{seeded['processing_recording'].id}",
            "status": "processing",
        }
    ]

    attention_resp = await client.get(
        "/api/inbox", headers=auth_headers, params={"status": "needs_attention"}
    )
    assert attention_resp.status_code == 200
    assert {row["id"] for row in attention_resp.json()["rows"]} == {
        f"recording:{seeded['failed_recording'].id}",
        f"item:{seeded['needs_input_item'].id}",
    }

    folder_resp = await client.get(
        "/api/inbox",
        headers=auth_headers,
        params={"folder_id": str(seeded["folder"].id)},
    )
    assert folder_resp.status_code == 200
    folder_rows = folder_resp.json()["rows"]
    assert {row["id"] for row in folder_rows} == {
        f"recording:{seeded['recording'].id}",
        f"item:{seeded['item'].id}",
    }
    assert {row["source_kind"] for row in folder_rows} == {"recording", "item"}
    assert all(row["folder_id"] == str(seeded["folder"].id) for row in folder_rows)


async def test_inbox_ready_status_includes_summaries_without_chats(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
) -> None:
    user_id = await _current_user_id(client, auth_headers)
    seeded = await _seed_mixed_inbox(db_session, user_id)

    resp = await client.get("/api/inbox", headers=auth_headers, params={"status": "ready"})

    assert resp.status_code == 200, resp.text
    assert {row["id"] for row in resp.json()["rows"]} == {
        f"item:{seeded['item'].id}",
        f"recording:{seeded['recording'].id}",
    }
    assert all(row["source_kind"] != "chat" for row in resp.json()["rows"])


async def test_inbox_item_processing_and_processing_error_attention_filters(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
) -> None:
    user_id = await _current_user_id(client, auth_headers)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    processing_item = Item(
        user_id=user_id,
        source="paste",
        kind="note",
        title="Processing note",
        body="Needs summary.",
        content_hash=uuid4().hex,
        created_at=now,
    )
    failed_item = Item(
        user_id=user_id,
        source="paste",
        kind="note",
        title="Failed note",
        body="Could not summarize.",
        content_hash=uuid4().hex,
        metadata_={
            "processing_error": {
                "code": "summary_failed",
                "message": "The summary job failed.",
            }
        },
        created_at=now - timedelta(minutes=1),
    )
    db_session.add_all([processing_item, failed_item])
    await db_session.commit()

    processing_resp = await client.get(
        "/api/inbox",
        headers=auth_headers,
        params={"source_kind": "item", "status": "processing"},
    )
    attention_resp = await client.get(
        "/api/inbox",
        headers=auth_headers,
        params={"source_kind": "item", "status": "needs_attention"},
    )

    assert processing_resp.status_code == 200, processing_resp.text
    assert [row["id"] for row in processing_resp.json()["rows"]] == [
        f"item:{processing_item.id}"
    ]
    assert processing_resp.json()["rows"][0]["status"] == "processing"
    assert attention_resp.status_code == 200, attention_resp.text
    assert [row["id"] for row in attention_resp.json()["rows"]] == [
        f"item:{failed_item.id}"
    ]
    assert attention_resp.json()["rows"][0]["error"] == {
        "code": "summary_failed",
        "message": "The summary job failed.",
    }


async def test_inbox_cursor_paginates_with_stable_tiebreaker(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
) -> None:
    user_id = await _current_user_id(client, auth_headers)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    recs = [
        Recording(
            user_id=user_id,
            title=f"Same time {idx}",
            type="note",
            status="ready",
            created_at=now,
        )
        for idx in range(3)
    ]
    db_session.add_all(recs)
    await db_session.commit()

    page1 = await client.get("/api/inbox", headers=auth_headers, params={"limit": 2})
    assert page1.status_code == 200, page1.text
    body1 = page1.json()
    assert len(body1["rows"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"] is not None

    page2 = await client.get(
        "/api/inbox",
        headers=auth_headers,
        params={"limit": 2, "cursor": body1["next_cursor"]},
    )
    assert page2.status_code == 200, page2.text
    body2 = page2.json()
    returned_ids = [row["source_id"] for row in body1["rows"] + body2["rows"]]
    assert returned_ids == sorted(returned_ids, reverse=True)
    assert set(returned_ids) == {str(rec.id) for rec in recs}


async def test_inbox_cursor_paginates_across_source_tiebreakers(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
) -> None:
    user_id = await _current_user_id(client, auth_headers)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    recording = Recording(
        user_id=user_id,
        title="Same time recording",
        type="note",
        status="ready",
        created_at=now,
    )
    item = Item(
        user_id=user_id,
        source="paste",
        kind="note",
        title="Same time item",
        body="Ready material.",
        content_hash=uuid4().hex,
        created_at=now,
    )
    db_session.add_all([recording, item])
    await db_session.flush()
    db_session.add(ItemSummary(item_id=item.id, summary="Ready."))
    await db_session.commit()

    page1 = await client.get("/api/inbox", headers=auth_headers, params={"limit": 1})
    assert page1.status_code == 200, page1.text
    assert [row["source_kind"] for row in page1.json()["rows"]] == ["item"]

    page2 = await client.get(
        "/api/inbox",
        headers=auth_headers,
        params={"limit": 1, "cursor": page1.json()["next_cursor"]},
    )
    assert page2.status_code == 200, page2.text
    assert [row["id"] for row in page2.json()["rows"]] == [f"recording:{recording.id}"]


async def test_inbox_item_cursor_uses_source_specific_ids_and_rejects_chat_source(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
) -> None:
    user_id = await _current_user_id(client, auth_headers)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    items = [
        Item(
            user_id=user_id,
            source="paste",
            kind="note",
            title=f"Item {idx}",
            body="Ready material.",
            content_hash=uuid4().hex,
            created_at=now,
        )
        for idx in range(3)
    ]
    chats = [
        Conversation(user_id=user_id, title=f"Chat {idx}", created_at=now)
        for idx in range(3)
    ]
    db_session.add_all([*items, *chats])
    await db_session.flush()
    db_session.add_all([ItemSummary(item_id=item.id, summary="Ready.") for item in items])
    await db_session.commit()

    item_page1 = await client.get(
        "/api/inbox",
        headers=auth_headers,
        params={"source_kind": "item", "limit": 2},
    )
    item_page2 = await client.get(
        "/api/inbox",
        headers=auth_headers,
        params={
            "source_kind": "item",
            "limit": 2,
            "cursor": item_page1.json()["next_cursor"],
        },
    )
    chats_only = await client.get(
        "/api/inbox", headers=auth_headers, params={"source_kind": "chat", "limit": 2}
    )

    assert item_page1.status_code == 200, item_page1.text
    assert item_page2.status_code == 200, item_page2.text
    assert len(item_page1.json()["rows"]) == 2
    assert len(item_page2.json()["rows"]) == 1
    assert chats_only.status_code == 422


async def test_inbox_rejects_invalid_cursor_and_requires_auth(
    client: AsyncClient, auth_headers: dict
) -> None:
    client.cookies.clear()
    unauthenticated = await client.get("/api/inbox")
    assert unauthenticated.status_code == 401

    invalid = await client.get(
        "/api/inbox", headers=auth_headers, params={"cursor": "not-a-cursor"}
    )
    assert invalid.status_code == 422

    unknown_source_cursor = _encoded_cursor(
        {
            "activity_at": datetime.now(timezone.utc).isoformat(),
            "source_kind": "unknown",
            "source_id": str(uuid4()),
        }
    )
    unknown = await client.get(
        "/api/inbox", headers=auth_headers, params={"cursor": unknown_source_cursor}
    )
    assert unknown.status_code == 422

    naive_datetime_cursor = _encoded_cursor(
        {
            "activity_at": datetime.now().replace(microsecond=0).isoformat(),
            "source_kind": "recording",
            "source_id": str(uuid4()),
        }
    )
    naive = await client.get(
        "/api/inbox", headers=auth_headers, params={"cursor": naive_datetime_cursor}
    )
    assert naive.status_code == 422


async def test_inbox_is_scoped_to_authenticated_user(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
) -> None:
    user_id = await _current_user_id(client, auth_headers)
    await _seed_mixed_inbox(db_session, user_id)

    other = await client.post(
        "/api/auth/register",
        json={
            "email": f"inbox-viewer-{uuid4().hex}@example.com",
            "password": "testpassword123",
            **LEGAL_ACCEPTANCE,
        },
    )
    assert other.status_code in (200, 201), other.text
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    resp = await client.get("/api/inbox", headers=other_headers)
    assert resp.status_code == 200
    assert resp.json()["rows"] == []


async def test_inbox_folder_scope_excludes_filed_chats(
    client: AsyncClient, auth_headers: dict
) -> None:
    """A filed Wai chat stays searchable, but it is not Inbox content."""
    folder_resp = await client.post(
        "/api/folders", json={"name": "Launch"}, headers=auth_headers
    )
    assert folder_resp.status_code == 201, folder_resp.text
    folder_id = folder_resp.json()["id"]

    chat_resp = await client.post(
        "/api/companion/chats", json={}, headers=auth_headers
    )
    assert chat_resp.status_code == 201, chat_resp.text
    chat_id = chat_resp.json()["id"]

    moved = await client.patch(
        f"/api/companion/chats/{chat_id}",
        json={"folder_id": folder_id},
        headers=auth_headers,
    )
    assert moved.status_code == 200, moved.text

    scoped = await client.get(
        "/api/inbox", headers=auth_headers, params={"folder_id": folder_id}
    )
    assert scoped.status_code == 200
    scoped_rows = scoped.json()["rows"]
    assert f"chat:{chat_id}" not in {row["id"] for row in scoped_rows}

    chats_only = await client.get(
        "/api/inbox",
        headers=auth_headers,
        params={"folder_id": folder_id, "source_kind": "chat"},
    )
    assert chats_only.status_code == 422

    all_chats = await client.get(
        "/api/inbox", headers=auth_headers, params={"source_kind": "chat"}
    )
    assert all_chats.status_code == 422
