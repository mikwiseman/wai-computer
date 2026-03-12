"""Tests for chat API routes."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import chat as chat_routes
from app.core.chat import ChatResult, SourceSegment
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


@pytest.mark.asyncio
async def test_send_chat_message_parses_ids_and_serializes_sources(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    headers, token = await _register(client, "chat.route.send@example.com")
    user = await _user_from_token(db_session, token)
    requested_session_id = uuid4()
    requested_recording_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_chat_with_recordings(
        *,
        db,
        user_id,
        question,
        session_id=None,
        recording_ids=None,
    ):
        captured["user_id"] = user_id
        captured["question"] = question
        captured["session_id"] = session_id
        captured["recording_ids"] = recording_ids
        return ChatResult(
            answer="Alice owns the launch demo.",
            session_id=str(requested_session_id),
            message_id=str(uuid4()),
            source_segments=[
                SourceSegment(
                    segment_id=str(uuid4()),
                    recording_id=str(requested_recording_id),
                    recording_title="Launch Notes",
                    speaker="Alice",
                    content="Alice will own the launch demo.",
                    start_ms=0,
                    end_ms=1200,
                )
            ],
        )

    monkeypatch.setattr(chat_routes, "chat_with_recordings", fake_chat_with_recordings)

    response = await client.post(
        "/api/chat",
        headers=headers,
        json={
            "question": "Who owns the launch demo?",
            "session_id": str(requested_session_id),
            "recording_ids": [str(requested_recording_id)],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "Alice owns the launch demo."
    assert payload["session_id"] == str(requested_session_id)
    assert payload["sources"][0]["recording_title"] == "Launch Notes"
    assert captured == {
        "user_id": user.id,
        "question": "Who owns the launch demo?",
        "session_id": requested_session_id,
        "recording_ids": [requested_recording_id],
    }


@pytest.mark.asyncio
async def test_chat_session_endpoints_list_get_and_delete(
    client: AsyncClient,
    db_session: AsyncSession,
):
    headers, token = await _register(client, "chat.route.session@example.com")
    user = await _user_from_token(db_session, token)
    other = User(email="chat.route.other@example.com", password_hash="hashed")
    db_session.add(other)
    await db_session.flush()

    owned_session = ChatSession(
        user_id=user.id,
        title="Weekly sync",
        recording_ids=[str(uuid4())],
    )
    other_session = ChatSession(user_id=other.id, title="Other", recording_ids=None)
    db_session.add_all([owned_session, other_session])
    await db_session.flush()

    db_session.add_all(
        [
            ChatMessage(
                session_id=owned_session.id,
                role="user",
                content="What happened?",
                source_segment_ids=None,
                source_recording_ids=None,
            ),
            ChatMessage(
                session_id=owned_session.id,
                role="assistant",
                content="Alice owns the launch demo.",
                source_segment_ids=[str(uuid4())],
                source_recording_ids=[str(uuid4())],
            ),
            ChatMessage(
                session_id=other_session.id,
                role="user",
                content="Ignore me",
                source_segment_ids=None,
                source_recording_ids=None,
            ),
        ]
    )
    await db_session.flush()

    list_response = await client.get("/api/chat/sessions", headers=headers)
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert [item["id"] for item in list_payload] == [str(owned_session.id)]
    assert list_payload[0]["message_count"] == 2

    detail_response = await client.get(f"/api/chat/sessions/{owned_session.id}", headers=headers)
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["id"] == str(owned_session.id)
    assert [message["role"] for message in detail_payload["messages"]] == ["user", "assistant"]
    assert detail_payload["messages"][1]["source_segment_ids"] is not None

    delete_response = await client.delete(f"/api/chat/sessions/{owned_session.id}", headers=headers)
    assert delete_response.status_code == 204
    await db_session.flush()
    assert await db_session.get(ChatSession, owned_session.id) is None


@pytest.mark.asyncio
async def test_chat_session_endpoints_return_not_found_for_other_users(
    client: AsyncClient,
    db_session: AsyncSession,
):
    _, token = await _register(client, "chat.route.notfound@example.com")
    user = await _user_from_token(db_session, token)
    session = ChatSession(user_id=user.id, title="Mine", recording_ids=None)
    db_session.add(session)
    await db_session.flush()

    other_headers, _ = await _register(client, "chat.route.notfound.other@example.com")

    detail_response = await client.get(f"/api/chat/sessions/{session.id}", headers=other_headers)
    assert detail_response.status_code == 404
    assert detail_response.json()["detail"] == "Chat session not found"

    delete_response = await client.delete(f"/api/chat/sessions/{session.id}", headers=other_headers)
    assert delete_response.status_code == 404
    assert delete_response.json()["detail"] == "Chat session not found"


@pytest.mark.asyncio
async def test_send_chat_message_rejects_malformed_session_id(
    client: AsyncClient,
    db_session: AsyncSession,
):
    headers, _ = await _register(client, "chat.route.badsession@example.com")

    response = await client.post(
        "/api/chat",
        headers=headers,
        json={"question": "Hello?", "session_id": "not-a-uuid"},
    )
    assert response.status_code == 422
    assert "Invalid UUID" in response.json()["detail"]


@pytest.mark.asyncio
async def test_send_chat_message_rejects_malformed_recording_id(
    client: AsyncClient,
    db_session: AsyncSession,
):
    headers, _ = await _register(client, "chat.route.badrecording@example.com")

    response = await client.post(
        "/api/chat",
        headers=headers,
        json={
            "question": "Hello?",
            "recording_ids": [str(uuid4()), "garbage"],
        },
    )
    assert response.status_code == 422
    assert "Invalid UUID" in response.json()["detail"]


@pytest.mark.asyncio
async def test_send_chat_message_rejects_empty_question(
    client: AsyncClient,
    db_session: AsyncSession,
):
    headers, _ = await _register(client, "chat.route.emptyq@example.com")

    response = await client.post(
        "/api/chat",
        headers=headers,
        json={"question": ""},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_chat_sessions_empty(client: AsyncClient, db_session: AsyncSession):
    """User with no chat sessions should get an empty list."""
    headers, _ = await _register(client, "chat.route.empty@example.com")
    response = await client.get("/api/chat/sessions", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_chat_session_with_no_messages(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Session with no messages should return empty messages array."""
    headers, token = await _register(client, "chat.route.nomsg@example.com")
    user = await _user_from_token(db_session, token)
    session = ChatSession(user_id=user.id, title="Empty Session", recording_ids=None)
    db_session.add(session)
    await db_session.flush()

    response = await client.get(f"/api/chat/sessions/{session.id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Empty Session"
    assert data["messages"] == []


@pytest.mark.asyncio
async def test_delete_nonexistent_chat_session_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Deleting a nonexistent session should return 404."""
    headers, _ = await _register(client, "chat.route.delnone@example.com")
    fake_id = str(uuid4())
    response = await client.delete(f"/api/chat/sessions/{fake_id}", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_send_chat_message_without_optional_fields(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Sending just a question without session_id or recording_ids should succeed."""
    headers, token = await _register(client, "chat.route.minimal@example.com")

    async def fake_chat_with_recordings(
        *, db, user_id, question, session_id=None, recording_ids=None
    ):
        return ChatResult(
            answer="Here is a general answer.",
            session_id=str(uuid4()),
            message_id=str(uuid4()),
            source_segments=[],
        )

    monkeypatch.setattr(chat_routes, "chat_with_recordings", fake_chat_with_recordings)

    response = await client.post(
        "/api/chat",
        headers=headers,
        json={"question": "What happened today?"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "Here is a general answer."
    assert payload["session_id"] is not None
    assert payload["sources"] == []


@pytest.mark.asyncio
async def test_rename_chat_session(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Renaming a chat session should update the title."""
    headers, token = await _register(client, "chat.route.rename@example.com")
    user = await _user_from_token(db_session, token)
    session = ChatSession(
        user_id=user.id, title="Old Title", recording_ids=None
    )
    db_session.add(session)
    await db_session.flush()

    response = await client.patch(
        f"/api/chat/sessions/{session.id}",
        headers=headers,
        json={"title": "New Title"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(session.id)
    assert payload["title"] == "New Title"


@pytest.mark.asyncio
async def test_rename_chat_session_to_null(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Setting title to null should clear it."""
    headers, token = await _register(
        client, "chat.route.rename.null@example.com"
    )
    user = await _user_from_token(db_session, token)
    session = ChatSession(
        user_id=user.id, title="Has Title", recording_ids=None
    )
    db_session.add(session)
    await db_session.flush()

    response = await client.patch(
        f"/api/chat/sessions/{session.id}",
        headers=headers,
        json={"title": None},
    )
    assert response.status_code == 200
    assert response.json()["title"] is None


@pytest.mark.asyncio
async def test_rename_chat_session_not_found(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Renaming a nonexistent session should return 404."""
    headers, _ = await _register(
        client, "chat.route.rename.nf@example.com"
    )
    fake_id = str(uuid4())
    response = await client.patch(
        f"/api/chat/sessions/{fake_id}",
        headers=headers,
        json={"title": "X"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Chat session not found"


@pytest.mark.asyncio
async def test_rename_chat_session_other_user_denied(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Renaming another user's session should return 404."""
    _, owner_token = await _register(
        client, "chat.route.rename.owner@example.com"
    )
    owner = await _user_from_token(db_session, owner_token)
    session = ChatSession(
        user_id=owner.id, title="Owner Only", recording_ids=None
    )
    db_session.add(session)
    await db_session.flush()

    other_headers, _ = await _register(
        client, "chat.route.rename.other@example.com"
    )
    response = await client.patch(
        f"/api/chat/sessions/{session.id}",
        headers=other_headers,
        json={"title": "Hijacked"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rename_chat_session_empty_title_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Empty string title should be rejected."""
    headers, token = await _register(
        client, "chat.route.rename.empty@example.com"
    )
    user = await _user_from_token(db_session, token)
    session = ChatSession(
        user_id=user.id, title="Keep", recording_ids=None
    )
    db_session.add(session)
    await db_session.flush()

    response = await client.patch(
        f"/api/chat/sessions/{session.id}",
        headers=headers,
        json={"title": ""},
    )
    assert response.status_code == 422
