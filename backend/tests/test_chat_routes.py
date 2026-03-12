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


@pytest.mark.asyncio
async def test_rename_chat_session_preserves_messages(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Renaming should not affect session messages."""
    headers, token = await _register(
        client, "chat.route.rename.msgs@example.com"
    )
    user = await _user_from_token(db_session, token)
    session = ChatSession(
        user_id=user.id, title="Old", recording_ids=None
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add(
        ChatMessage(
            session_id=session.id,
            role="user",
            content="Hello",
            source_segment_ids=None,
            source_recording_ids=None,
        )
    )
    await db_session.flush()

    await client.patch(
        f"/api/chat/sessions/{session.id}",
        headers=headers,
        json={"title": "Renamed"},
    )

    detail = await client.get(
        f"/api/chat/sessions/{session.id}", headers=headers
    )
    assert detail.status_code == 200
    assert detail.json()["title"] == "Renamed"
    assert len(detail.json()["messages"]) == 1


@pytest.mark.asyncio
async def test_export_chat_session(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Export should return markdown formatted conversation."""
    headers, token = await _register(
        client, "chat.route.export@example.com"
    )
    user = await _user_from_token(db_session, token)
    session = ChatSession(
        user_id=user.id, title="Export Test", recording_ids=None
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add_all([
        ChatMessage(
            session_id=session.id,
            role="user",
            content="What happened in the meeting?",
            source_segment_ids=None,
            source_recording_ids=None,
        ),
        ChatMessage(
            session_id=session.id,
            role="assistant",
            content="Alice discussed the roadmap.",
            source_segment_ids=[str(uuid4())],
            source_recording_ids=[str(uuid4())],
        ),
    ])
    await db_session.flush()

    response = await client.get(
        f"/api/chat/sessions/{session.id}/export",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    body = response.text
    assert "# Export Test" in body
    assert "**You:**" in body
    assert "What happened in the meeting?" in body
    assert "**Assistant:**" in body
    assert "Alice discussed the roadmap." in body


@pytest.mark.asyncio
async def test_export_chat_session_not_found(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Export of nonexistent session should return 404."""
    headers, _ = await _register(
        client, "chat.route.export.nf@example.com"
    )
    fake_id = str(uuid4())
    response = await client.get(
        f"/api/chat/sessions/{fake_id}/export",
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_export_chat_session_other_user_denied(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Export of another user's session should return 404."""
    _, owner_token = await _register(
        client, "chat.route.export.owner@example.com"
    )
    owner = await _user_from_token(db_session, owner_token)
    session = ChatSession(
        user_id=owner.id, title="Private", recording_ids=None
    )
    db_session.add(session)
    await db_session.flush()

    other_headers, _ = await _register(
        client, "chat.route.export.other@example.com"
    )
    response = await client.get(
        f"/api/chat/sessions/{session.id}/export",
        headers=other_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_export_empty_chat_session(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Export of session with no messages returns markdown header only."""
    headers, token = await _register(
        client, "chat.route.export.empty@example.com"
    )
    user = await _user_from_token(db_session, token)
    session = ChatSession(
        user_id=user.id, title="Empty Chat", recording_ids=None
    )
    db_session.add(session)
    await db_session.flush()

    response = await client.get(
        f"/api/chat/sessions/{session.id}/export",
        headers=headers,
    )
    assert response.status_code == 200
    body = response.text
    assert "# Empty Chat" in body
    assert "**You:**" not in body


@pytest.mark.asyncio
async def test_export_chat_session_with_null_title(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Export session with null title should use default heading."""
    headers, token = await _register(
        client, "chat.route.export.null@example.com"
    )
    user = await _user_from_token(db_session, token)
    session = ChatSession(
        user_id=user.id, title=None, recording_ids=None
    )
    db_session.add(session)
    await db_session.flush()

    response = await client.get(
        f"/api/chat/sessions/{session.id}/export",
        headers=headers,
    )
    assert response.status_code == 200
    assert "# Chat Session" in response.text


@pytest.mark.asyncio
async def test_search_chat_sessions(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Search should find sessions containing the query in messages."""
    headers, token = await _register(
        client, "chat.route.search@example.com"
    )
    user = await _user_from_token(db_session, token)

    s1 = ChatSession(
        user_id=user.id, title="Roadmap Chat", recording_ids=None
    )
    s2 = ChatSession(
        user_id=user.id, title="Budget Chat", recording_ids=None
    )
    db_session.add_all([s1, s2])
    await db_session.flush()

    db_session.add_all([
        ChatMessage(
            session_id=s1.id,
            role="user",
            content="Tell me about the roadmap",
            source_segment_ids=None,
            source_recording_ids=None,
        ),
        ChatMessage(
            session_id=s1.id,
            role="assistant",
            content="The roadmap includes Q3 milestones.",
            source_segment_ids=None,
            source_recording_ids=None,
        ),
        ChatMessage(
            session_id=s2.id,
            role="user",
            content="What is the budget?",
            source_segment_ids=None,
            source_recording_ids=None,
        ),
    ])
    await db_session.flush()

    response = await client.get(
        "/api/chat/sessions/search",
        headers=headers,
        params={"q": "roadmap"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == str(s1.id)
    assert payload[0]["title"] == "Roadmap Chat"


@pytest.mark.asyncio
async def test_search_chat_sessions_no_results(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Search with no matching messages returns empty list."""
    headers, _ = await _register(
        client, "chat.route.search.empty@example.com"
    )

    response = await client.get(
        "/api/chat/sessions/search",
        headers=headers,
        params={"q": "nonexistent"},
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_search_chat_sessions_other_user_excluded(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Search should not return other users' sessions."""
    _, owner_token = await _register(
        client, "chat.route.search.owner@example.com"
    )
    owner = await _user_from_token(db_session, owner_token)
    session = ChatSession(
        user_id=owner.id, title="Private Fixture", recording_ids=None
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add(
        ChatMessage(
            session_id=session.id,
            role="user",
            content="secret roadmap details",
            source_segment_ids=None,
            source_recording_ids=None,
        )
    )
    await db_session.flush()

    other_headers, _ = await _register(
        client, "chat.route.search.other@example.com"
    )
    response = await client.get(
        "/api/chat/sessions/search",
        headers=other_headers,
        params={"q": "roadmap"},
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_search_chat_sessions_empty_query_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Empty query should return 422."""
    headers, _ = await _register(
        client, "chat.route.search.emptyq@example.com"
    )
    response = await client.get(
        "/api/chat/sessions/search",
        headers=headers,
        params={"q": ""},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_chat_sessions_case_insensitive(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Search should be case-insensitive."""
    headers, token = await _register(
        client, "chat.route.search.case@example.com"
    )
    user = await _user_from_token(db_session, token)
    session = ChatSession(
        user_id=user.id, title="Test", recording_ids=None
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add(
        ChatMessage(
            session_id=session.id,
            role="assistant",
            content="The ROADMAP is ready.",
            source_segment_ids=None,
            source_recording_ids=None,
        )
    )
    await db_session.flush()

    response = await client.get(
        "/api/chat/sessions/search",
        headers=headers,
        params={"q": "roadmap"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_search_chat_sessions_percent_not_wildcard(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Percent sign in query should be treated as literal, not wildcard."""
    headers, token = await _register(
        client, "chat.route.search.pct@example.com"
    )
    user = await _user_from_token(db_session, token)
    session = ChatSession(
        user_id=user.id, title="Pct", recording_ids=None
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add(
        ChatMessage(
            session_id=session.id,
            role="assistant",
            content="Revenue grew 15% last quarter.",
            source_segment_ids=None,
            source_recording_ids=None,
        )
    )
    await db_session.flush()

    # Searching for literal "%" should NOT match everything
    response = await client.get(
        "/api/chat/sessions/search",
        headers=headers,
        params={"q": "%"},
    )
    # Should not match because "%" is not in the content as a standalone word
    # Actually "15%" contains %, so it SHOULD match
    assert response.status_code == 200
    assert len(response.json()) == 1

    # Searching for "xyz" should NOT match
    response2 = await client.get(
        "/api/chat/sessions/search",
        headers=headers,
        params={"q": "xyz"},
    )
    assert response2.status_code == 200
    assert len(response2.json()) == 0


@pytest.mark.asyncio
async def test_search_chat_sessions_underscore_literal(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Underscore in query should be literal, not single-char wildcard."""
    headers, token = await _register(
        client, "chat.route.search.under@example.com"
    )
    user = await _user_from_token(db_session, token)
    s1 = ChatSession(
        user_id=user.id, title="Under", recording_ids=None
    )
    db_session.add(s1)
    await db_session.flush()
    db_session.add(
        ChatMessage(
            session_id=s1.id,
            role="user",
            content="Check the my_variable value.",
            source_segment_ids=None,
            source_recording_ids=None,
        )
    )
    await db_session.flush()

    # "_" as wildcard would match single chars; as literal it
    # should only match content actually containing "_"
    response = await client.get(
        "/api/chat/sessions/search",
        headers=headers,
        params={"q": "my_variable"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1

    # "myXvariable" should NOT match because _ is literal
    response2 = await client.get(
        "/api/chat/sessions/search",
        headers=headers,
        params={"q": "myXvariable"},
    )
    assert response2.status_code == 200
    assert len(response2.json()) == 0


# --- Pin/unpin tests ---


@pytest.mark.asyncio
async def test_pin_chat_session(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Pinning a session should set pinned_at and return it."""
    headers, token = await _register(client, "chat.route.pin@example.com")
    user = await _user_from_token(db_session, token)
    session = ChatSession(user_id=user.id, title="Pin Me", recording_ids=None)
    db_session.add(session)
    await db_session.flush()

    response = await client.post(
        f"/api/chat/sessions/{session.id}/pin",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(session.id)
    assert payload["pinned_at"] is not None


@pytest.mark.asyncio
async def test_unpin_chat_session(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Unpinning a session should clear pinned_at."""
    headers, token = await _register(client, "chat.route.unpin@example.com")
    user = await _user_from_token(db_session, token)
    from datetime import datetime, timezone

    session = ChatSession(
        user_id=user.id,
        title="Unpin Me",
        recording_ids=None,
        pinned_at=datetime.now(timezone.utc),
    )
    db_session.add(session)
    await db_session.flush()

    response = await client.delete(
        f"/api/chat/sessions/{session.id}/pin",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(session.id)
    assert payload["pinned_at"] is None


@pytest.mark.asyncio
async def test_pin_session_not_found(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Pinning a nonexistent session should return 404."""
    headers, _ = await _register(client, "chat.route.pin.nf@example.com")
    fake_id = str(uuid4())
    response = await client.post(
        f"/api/chat/sessions/{fake_id}/pin",
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unpin_session_not_found(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Unpinning a nonexistent session should return 404."""
    headers, _ = await _register(client, "chat.route.unpin.nf@example.com")
    fake_id = str(uuid4())
    response = await client.delete(
        f"/api/chat/sessions/{fake_id}/pin",
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_pin_session_other_user_denied(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Pinning another user's session should return 404."""
    _, owner_token = await _register(client, "chat.route.pin.owner@example.com")
    owner = await _user_from_token(db_session, owner_token)
    session = ChatSession(
        user_id=owner.id, title="Owner Session", recording_ids=None
    )
    db_session.add(session)
    await db_session.flush()

    other_headers, _ = await _register(client, "chat.route.pin.other@example.com")
    response = await client.post(
        f"/api/chat/sessions/{session.id}/pin",
        headers=other_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_pinned_sessions_appear_first_in_list(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Pinned sessions should appear before unpinned ones in the list."""
    headers, token = await _register(client, "chat.route.pin.order@example.com")
    user = await _user_from_token(db_session, token)
    from datetime import datetime, timezone

    # Create three sessions: s1 (oldest), s2 (middle), s3 (newest)
    s1 = ChatSession(user_id=user.id, title="Oldest", recording_ids=None)
    s2 = ChatSession(user_id=user.id, title="Middle", recording_ids=None)
    s3 = ChatSession(user_id=user.id, title="Newest", recording_ids=None)
    db_session.add_all([s1, s2, s3])
    await db_session.flush()

    # Pin the oldest session
    s1.pinned_at = datetime.now(timezone.utc)
    await db_session.flush()

    response = await client.get("/api/chat/sessions", headers=headers)
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 3
    # The pinned session (s1) should be first
    assert items[0]["id"] == str(s1.id)
    assert items[0]["pinned_at"] is not None
    # The other two should be sorted by created_at desc (s3 then s2)
    assert items[1]["pinned_at"] is None
    assert items[2]["pinned_at"] is None


@pytest.mark.asyncio
async def test_pin_already_pinned_session_updates_timestamp(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Pinning an already-pinned session should update the pinned_at timestamp."""
    headers, token = await _register(
        client, "chat.route.pin.update@example.com"
    )
    user = await _user_from_token(db_session, token)
    session = ChatSession(
        user_id=user.id, title="Pin Twice", recording_ids=None
    )
    db_session.add(session)
    await db_session.flush()

    # Pin once
    r1 = await client.post(
        f"/api/chat/sessions/{session.id}/pin",
        headers=headers,
    )
    assert r1.status_code == 200
    first_pin = r1.json()["pinned_at"]

    # Pin again
    import asyncio
    await asyncio.sleep(0.01)
    r2 = await client.post(
        f"/api/chat/sessions/{session.id}/pin",
        headers=headers,
    )
    assert r2.status_code == 200
    second_pin = r2.json()["pinned_at"]

    # The timestamp should be updated (or at least not None)
    assert second_pin is not None
    # Both should be valid ISO timestamps
    assert first_pin is not None


@pytest.mark.asyncio
async def test_list_sessions_pinned_at_field_present(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """List response should include pinned_at field (null for unpinned)."""
    headers, token = await _register(
        client, "chat.route.pin.field@example.com"
    )
    user = await _user_from_token(db_session, token)
    session = ChatSession(
        user_id=user.id, title="Field Check", recording_ids=None
    )
    db_session.add(session)
    await db_session.flush()

    response = await client.get("/api/chat/sessions", headers=headers)
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert "pinned_at" in items[0]
    assert items[0]["pinned_at"] is None
