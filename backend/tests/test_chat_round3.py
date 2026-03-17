"""Round 3 chat route tests — coverage gaps and edge cases."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User


async def _register(client: AsyncClient, email: str) -> tuple[dict[str, str], str]:
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, token


async def _user_from_token(db_session: AsyncSession, token: str) -> User:
    user_id = decode_access_token(token)
    assert user_id is not None
    user = await db_session.get(User, user_id)
    assert user is not None
    return user


# --- Pin / Unpin ---


@pytest.mark.asyncio
async def test_pin_then_verify_via_list(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Pin a session via POST /pin, then verify GET /sessions shows pinned_at set."""
    headers, token = await _register(client, "r3.pin.list@example.com")
    user = await _user_from_token(db_session, token)
    session = ChatSession(user_id=user.id, title="Pin List Check", recording_ids=None)
    db_session.add(session)
    await db_session.flush()

    pin_resp = await client.post(
        f"/api/chat/sessions/{session.id}/pin", headers=headers
    )
    assert pin_resp.status_code == 200

    list_resp = await client.get("/api/chat/sessions", headers=headers)
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["id"] == str(session.id)
    assert items[0]["pinned_at"] is not None


@pytest.mark.asyncio
async def test_unpin_already_unpinned_session(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Unpinning a session that was never pinned should still succeed with pinned_at=None."""
    headers, token = await _register(client, "r3.unpin.noop@example.com")
    user = await _user_from_token(db_session, token)
    session = ChatSession(
        user_id=user.id, title="Never Pinned", recording_ids=None, pinned_at=None
    )
    db_session.add(session)
    await db_session.flush()

    response = await client.delete(
        f"/api/chat/sessions/{session.id}/pin", headers=headers
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pinned_at"] is None


@pytest.mark.asyncio
async def test_pin_unpin_roundtrip(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Pin then unpin a session — pinned_at should go from set back to None."""
    headers, token = await _register(client, "r3.pin.roundtrip@example.com")
    user = await _user_from_token(db_session, token)
    session = ChatSession(user_id=user.id, title="Roundtrip", recording_ids=None)
    db_session.add(session)
    await db_session.flush()

    # Pin
    pin_resp = await client.post(
        f"/api/chat/sessions/{session.id}/pin", headers=headers
    )
    assert pin_resp.status_code == 200
    assert pin_resp.json()["pinned_at"] is not None

    # Unpin
    unpin_resp = await client.delete(
        f"/api/chat/sessions/{session.id}/pin", headers=headers
    )
    assert unpin_resp.status_code == 200
    assert unpin_resp.json()["pinned_at"] is None

    # Verify via list
    list_resp = await client.get("/api/chat/sessions", headers=headers)
    items = list_resp.json()
    assert items[0]["pinned_at"] is None


@pytest.mark.asyncio
async def test_multiple_pinned_sessions_ordered_by_pin_time(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Two pinned sessions should be ordered by pinned_at desc (most recently pinned first)."""
    headers, token = await _register(client, "r3.pin.multi@example.com")
    user = await _user_from_token(db_session, token)

    s1 = ChatSession(user_id=user.id, title="First Pin", recording_ids=None)
    s2 = ChatSession(user_id=user.id, title="Second Pin", recording_ids=None)
    s3 = ChatSession(user_id=user.id, title="Not Pinned", recording_ids=None)
    db_session.add_all([s1, s2, s3])
    await db_session.flush()

    # Pin s1 first
    r1 = await client.post(f"/api/chat/sessions/{s1.id}/pin", headers=headers)
    assert r1.status_code == 200

    await asyncio.sleep(0.01)

    # Pin s2 second (more recent pin)
    r2 = await client.post(f"/api/chat/sessions/{s2.id}/pin", headers=headers)
    assert r2.status_code == 200

    list_resp = await client.get("/api/chat/sessions", headers=headers)
    items = list_resp.json()
    assert len(items) == 3
    # s2 pinned most recently should come first
    assert items[0]["id"] == str(s2.id)
    assert items[0]["pinned_at"] is not None
    # s1 pinned earlier should come second
    assert items[1]["id"] == str(s1.id)
    assert items[1]["pinned_at"] is not None
    # s3 not pinned should come last
    assert items[2]["id"] == str(s3.id)
    assert items[2]["pinned_at"] is None


# --- Delete ---


@pytest.mark.asyncio
async def test_delete_session_cascades_messages(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Deleting a session should also remove all its messages."""
    headers, token = await _register(client, "r3.del.cascade@example.com")
    user = await _user_from_token(db_session, token)
    session = ChatSession(user_id=user.id, title="To Delete", recording_ids=None)
    db_session.add(session)
    await db_session.flush()

    msg = ChatMessage(
        session_id=session.id,
        role="user",
        content="Will be deleted",
        source_segment_ids=None,
        source_recording_ids=None,
    )
    db_session.add(msg)
    await db_session.flush()
    msg_id = msg.id

    del_resp = await client.delete(
        f"/api/chat/sessions/{session.id}", headers=headers
    )
    assert del_resp.status_code == 204

    # Session should be gone
    assert await db_session.get(ChatSession, session.id) is None
    # Message should also be gone (cascade)
    assert await db_session.get(ChatMessage, msg_id) is None


@pytest.mark.asyncio
async def test_delete_nonexistent_session_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Deleting a session that doesn't exist returns 404 with proper detail."""
    headers, _ = await _register(client, "r3.del.ghost@example.com")
    fake_id = str(uuid4())
    response = await client.delete(
        f"/api/chat/sessions/{fake_id}", headers=headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Chat session not found"


# --- Rename ---


@pytest.mark.asyncio
async def test_rename_session_whitespace_only_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Title that is only whitespace should be accepted if non-empty (min_length=1)."""
    headers, token = await _register(client, "r3.rename.ws@example.com")
    user = await _user_from_token(db_session, token)
    session = ChatSession(user_id=user.id, title="Original", recording_ids=None)
    db_session.add(session)
    await db_session.flush()

    # A single space is length 1, so should pass the min_length=1 validator
    response = await client.patch(
        f"/api/chat/sessions/{session.id}",
        headers=headers,
        json={"title": " "},
    )
    assert response.status_code == 200
    assert response.json()["title"] == " "


# --- Export ---


@pytest.mark.asyncio
async def test_export_content_disposition_header(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Export response should include Content-Disposition header with session ID filename."""
    headers, token = await _register(client, "r3.export.header@example.com")
    user = await _user_from_token(db_session, token)
    session = ChatSession(user_id=user.id, title="Header Check", recording_ids=None)
    db_session.add(session)
    await db_session.flush()

    response = await client.get(
        f"/api/chat/sessions/{session.id}/export", headers=headers
    )
    assert response.status_code == 200
    cd = response.headers.get("content-disposition")
    assert cd is not None
    assert f"chat-{session.id}.md" in cd


@pytest.mark.asyncio
async def test_export_messages_in_chronological_order(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Exported markdown should have messages in creation order."""
    headers, token = await _register(client, "r3.export.order@example.com")
    user = await _user_from_token(db_session, token)
    session = ChatSession(user_id=user.id, title="Order Test", recording_ids=None)
    db_session.add(session)
    await db_session.flush()

    db_session.add_all([
        ChatMessage(
            session_id=session.id,
            role="user",
            content="First question",
            source_segment_ids=None,
            source_recording_ids=None,
        ),
        ChatMessage(
            session_id=session.id,
            role="assistant",
            content="First answer",
            source_segment_ids=None,
            source_recording_ids=None,
        ),
        ChatMessage(
            session_id=session.id,
            role="user",
            content="Second question",
            source_segment_ids=None,
            source_recording_ids=None,
        ),
    ])
    await db_session.flush()

    response = await client.get(
        f"/api/chat/sessions/{session.id}/export", headers=headers
    )
    assert response.status_code == 200
    body = response.text
    # Verify ordering: first question before first answer before second question
    first_q_pos = body.index("First question")
    first_a_pos = body.index("First answer")
    second_q_pos = body.index("Second question")
    assert first_q_pos < first_a_pos < second_q_pos


# --- Search ---


@pytest.mark.asyncio
async def test_search_matches_assistant_messages(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Search should match content in assistant messages, not just user messages."""
    headers, token = await _register(client, "r3.search.assistant@example.com")
    user = await _user_from_token(db_session, token)
    session = ChatSession(user_id=user.id, title="AI Chat", recording_ids=None)
    db_session.add(session)
    await db_session.flush()

    db_session.add(
        ChatMessage(
            session_id=session.id,
            role="assistant",
            content="The quarterly revenue exceeded expectations.",
            source_segment_ids=None,
            source_recording_ids=None,
        )
    )
    await db_session.flush()

    response = await client.get(
        "/api/chat/sessions/search",
        headers=headers,
        params={"q": "quarterly revenue"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == str(session.id)


@pytest.mark.asyncio
async def test_search_does_not_match_title_only(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Search should match message content only, not session title."""
    headers, token = await _register(client, "r3.search.title@example.com")
    user = await _user_from_token(db_session, token)
    session = ChatSession(user_id=user.id, title="Budget Discussion", recording_ids=None)
    db_session.add(session)
    await db_session.flush()

    # Add a message that does NOT contain "Budget"
    db_session.add(
        ChatMessage(
            session_id=session.id,
            role="user",
            content="Tell me about the schedule.",
            source_segment_ids=None,
            source_recording_ids=None,
        )
    )
    await db_session.flush()

    response = await client.get(
        "/api/chat/sessions/search",
        headers=headers,
        params={"q": "Budget"},
    )
    assert response.status_code == 200
    # Should NOT match because "Budget" is only in the title, not in messages
    assert response.json() == []


@pytest.mark.asyncio
async def test_search_returns_message_count(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Search results should include correct message_count."""
    headers, token = await _register(client, "r3.search.count@example.com")
    user = await _user_from_token(db_session, token)
    session = ChatSession(user_id=user.id, title="Count Chat", recording_ids=None)
    db_session.add(session)
    await db_session.flush()

    db_session.add_all([
        ChatMessage(
            session_id=session.id,
            role="user",
            content="Tell me about infrastructure",
            source_segment_ids=None,
            source_recording_ids=None,
        ),
        ChatMessage(
            session_id=session.id,
            role="assistant",
            content="The infrastructure uses Docker.",
            source_segment_ids=None,
            source_recording_ids=None,
        ),
        ChatMessage(
            session_id=session.id,
            role="user",
            content="More details on infrastructure please",
            source_segment_ids=None,
            source_recording_ids=None,
        ),
    ])
    await db_session.flush()

    response = await client.get(
        "/api/chat/sessions/search",
        headers=headers,
        params={"q": "infrastructure"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["message_count"] == 3


@pytest.mark.asyncio
async def test_search_backslash_literal(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Backslash in search query should be treated as literal."""
    headers, token = await _register(client, "r3.search.backslash@example.com")
    user = await _user_from_token(db_session, token)
    session = ChatSession(user_id=user.id, title="Path Chat", recording_ids=None)
    db_session.add(session)
    await db_session.flush()

    db_session.add(
        ChatMessage(
            session_id=session.id,
            role="user",
            content="The path is C:\\Users\\admin\\docs",
            source_segment_ids=None,
            source_recording_ids=None,
        )
    )
    await db_session.flush()

    response = await client.get(
        "/api/chat/sessions/search",
        headers=headers,
        params={"q": "C:\\Users"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


# --- List sessions ---


@pytest.mark.asyncio
async def test_list_sessions_includes_recording_ids(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """List sessions should return the recording_ids field."""
    headers, token = await _register(client, "r3.list.recids@example.com")
    user = await _user_from_token(db_session, token)
    rec_id = str(uuid4())
    session = ChatSession(
        user_id=user.id, title="With Recordings", recording_ids=[rec_id]
    )
    db_session.add(session)
    await db_session.flush()

    response = await client.get("/api/chat/sessions", headers=headers)
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["recording_ids"] == [rec_id]


@pytest.mark.asyncio
async def test_list_sessions_null_recording_ids(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """List sessions with null recording_ids should return null."""
    headers, token = await _register(client, "r3.list.nullrec@example.com")
    user = await _user_from_token(db_session, token)
    session = ChatSession(
        user_id=user.id, title="No Recordings", recording_ids=None
    )
    db_session.add(session)
    await db_session.flush()

    response = await client.get("/api/chat/sessions", headers=headers)
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["recording_ids"] is None
