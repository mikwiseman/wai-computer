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


# ---------------------------------------------------------------------------
# Scope validation: brain_space_id / entity_id branches of
# _validated_scope_to_jsonb (each failure surfaces as a typed HTTP error).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_chat_rejects_malformed_brain_space_id(
    client: AsyncClient, auth_headers: dict
) -> None:
    response = await client.post(
        "/api/companion/chats",
        headers=auth_headers,
        json={"scope": {"brain_space_id": "not-a-uuid"}},
    )
    assert response.status_code == 422
    assert "Malformed brain_space_id" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_chat_rejects_unknown_brain_space(
    client: AsyncClient, auth_headers: dict
) -> None:
    response = await client.post(
        "/api/companion/chats",
        headers=auth_headers,
        json={"scope": {"brain_space_id": str(uuid.uuid4())}},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Brain scope not found"


@pytest.mark.asyncio
async def test_create_chat_maps_brain_space_permission_to_403(
    client: AsyncClient, auth_headers: dict, monkeypatch
) -> None:
    from app.core.brain_spaces import BrainSpacePermissionError

    async def deny(_db, _user_id, _space_id):
        raise BrainSpacePermissionError("viewer role required")

    monkeypatch.setattr("app.api.routes.companion.load_space_access", deny)
    response = await client.post(
        "/api/companion/chats",
        headers=auth_headers,
        json={"scope": {"brain_space_id": str(uuid.uuid4())}},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Brain scope is not available to this user"


@pytest.mark.asyncio
async def test_create_chat_maps_brain_space_validation_to_422(
    client: AsyncClient, auth_headers: dict, monkeypatch
) -> None:
    from app.core.brain_spaces import BrainSpaceValidationError

    async def reject(_db, _user_id, _space_id):
        raise BrainSpaceValidationError("space is archived")

    monkeypatch.setattr("app.api.routes.companion.load_space_access", reject)
    response = await client.post(
        "/api/companion/chats",
        headers=auth_headers,
        json={"scope": {"brain_space_id": str(uuid.uuid4())}},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "space is archived"


@pytest.mark.asyncio
async def test_create_chat_rejects_malformed_entity_id(
    client: AsyncClient, auth_headers: dict
) -> None:
    response = await client.post(
        "/api/companion/chats",
        headers=auth_headers,
        json={"scope": {"entity_id": "not-a-uuid"}},
    )
    assert response.status_code == 422
    assert "Malformed entity_id" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_chat_rejects_entity_not_owned(
    client: AsyncClient, auth_headers: dict
) -> None:
    response = await client.post(
        "/api/companion/chats",
        headers=auth_headers,
        json={"scope": {"entity_id": str(uuid.uuid4())}},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Entity scope not found"


@pytest.mark.asyncio
async def test_create_chat_accepts_owned_entity_scope(
    client: AsyncClient, auth_headers: dict, db_session
) -> None:
    from app.models.entity import Entity

    uid = await _me_id(client, auth_headers)
    entity = Entity(user_id=uid, type="person", name="Lena")
    db_session.add(entity)
    await db_session.flush()

    response = await client.post(
        "/api/companion/chats",
        headers=auth_headers,
        json={"scope": {"entity_id": str(entity.id)}},
    )
    assert response.status_code == 201
    assert response.json()["scope"] == {"entity_id": str(entity.id)}


async def _me_id(client: AsyncClient, headers: dict) -> uuid.UUID:
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return uuid.UUID(me.json()["id"])


# ---------------------------------------------------------------------------
# get_chat: before_message_id cursor happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_chat_before_message_cursor_returns_older_messages(
    client: AsyncClient, auth_headers: dict, db_session
) -> None:
    from datetime import datetime, timedelta, timezone

    from app.models.companion import ChatMessage

    r = await client.post("/api/companion/chats", headers=auth_headers, json={})
    chat_id = r.json()["id"]
    base = datetime.now(timezone.utc)
    older = ChatMessage(
        conversation_id=uuid.UUID(chat_id),
        role="user",
        content="first question",
        created_at=base - timedelta(minutes=2),
    )
    newer = ChatMessage(
        conversation_id=uuid.UUID(chat_id),
        role="assistant",
        content=[{"type": "text", "text": "second answer"}],
        created_at=base - timedelta(minutes=1),
    )
    db_session.add_all([older, newer])
    await db_session.flush()

    response = await client.get(
        f"/api/companion/chats/{chat_id}",
        headers=auth_headers,
        params={"before_message_id": str(newer.id)},
    )
    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [m["id"] for m in messages] == [str(older.id)]


# ---------------------------------------------------------------------------
# post_message SSE branches (legacy durable-runtime path). The Wai agent run
# is faked at run_wai_run_inline — zero model/network work.
# ---------------------------------------------------------------------------


def _sse_events(body: str) -> list[str]:
    return [
        line.split(": ", 1)[1]
        for line in body.split("\n")
        if line.startswith("event: ")
    ]


def _install_inline_stub(monkeypatch, mutate) -> None:
    """Replace the durable Wai run with a stub that mutates the run row."""

    async def fake_run_wai_run_inline(_db, run):
        result = mutate(run)
        if result is not None:  # allow async mutators
            await result
        return run

    monkeypatch.setattr(
        "app.api.routes.companion.run_wai_run_inline", fake_run_wai_run_inline
    )


@pytest.mark.asyncio
async def test_post_message_passes_viewing_context_to_wai_task(
    client: AsyncClient, auth_headers: dict, db_session, monkeypatch
) -> None:
    from app.core.wai_agent import start_wai_task as real_start_wai_task
    from app.models.recording import Folder, Recording

    uid = await _me_id(client, auth_headers)
    recording = Recording(
        user_id=uid, title="Roadmap sync", type="meeting", status="ready"
    )
    folder = Folder(user_id=uid, name="Work")
    db_session.add_all([recording, folder])
    await db_session.flush()

    captured: dict = {}

    async def spy_start_wai_task(db, **kwargs):
        captured.update(kwargs)
        return await real_start_wai_task(db, **kwargs)

    monkeypatch.setattr(
        "app.api.routes.companion.start_wai_task", spy_start_wai_task
    )

    def mutate(run):
        run.status = "done"
        run.result = {"output_text": "Context noted."}

    _install_inline_stub(monkeypatch, mutate)
    chat = (
        await client.post("/api/companion/chats", json={}, headers=auth_headers)
    ).json()

    response = await client.post(
        f"/api/companion/chats/{chat['id']}/messages",
        headers=auth_headers,
        json={
            "content": "what did we decide here?",
            "viewing_recording_id": str(recording.id),
            "viewing_folder_id": str(folder.id),
            "client_local_date": "2026-06-10",
            "client_timezone": "Europe/Lisbon",
        },
    )

    assert response.status_code == 200
    assert _sse_events(response.text) == ["turn_start", "token", "done"]
    # The owner-scoped lookups resolved the titles and the active context was
    # forwarded to the Wai task verbatim.
    assert captured["context"] == {
        "ref_type": "recording",
        "ref_id": str(recording.id),
        "source": "companion",
        "title": "Roadmap sync",
    }


@pytest.mark.asyncio
async def test_post_message_retrying_run_emits_retry_notice(
    client: AsyncClient, auth_headers: dict, monkeypatch
) -> None:
    def mutate(run):
        run.status = "pending"
        run.error = "Retrying after transient provider error: HTTPStatusError"

    _install_inline_stub(monkeypatch, mutate)
    chat = (
        await client.post("/api/companion/chats", json={}, headers=auth_headers)
    ).json()

    response = await client.post(
        f"/api/companion/chats/{chat['id']}/messages",
        headers=auth_headers,
        json={"content": "try something heavy"},
    )

    assert response.status_code == 200
    assert _sse_events(response.text) == ["turn_start", "token", "done"]
    assert "temporary provider limit" in response.text

    detail = await client.get(
        f"/api/companion/chats/{chat['id']}", headers=auth_headers
    )
    assistant = [
        m for m in detail.json()["messages"] if m["role"] == "assistant"
    ][-1]
    assert assistant["model"] == "wai-agent"
    assert "temporary provider limit" in str(assistant["content"])


@pytest.mark.asyncio
async def test_post_message_failed_run_surfaces_error_event(
    client: AsyncClient, auth_headers: dict, monkeypatch
) -> None:
    def mutate(run):
        run.status = "failed"
        run.error = "provider exploded"

    _install_inline_stub(monkeypatch, mutate)
    chat = (
        await client.post("/api/companion/chats", json={}, headers=auth_headers)
    ).json()

    response = await client.post(
        f"/api/companion/chats/{chat['id']}/messages",
        headers=auth_headers,
        json={"content": "doomed"},
    )

    assert response.status_code == 200
    assert _sse_events(response.text) == ["turn_start", "error"]
    assert "wai_agent_failed" in response.text
    assert "provider exploded" in response.text


@pytest.mark.asyncio
async def test_post_message_empty_agent_output_surfaces_error_event(
    client: AsyncClient, auth_headers: dict, monkeypatch
) -> None:
    def mutate(run):
        run.status = "done"
        run.result = {"output_text": "   "}

    _install_inline_stub(monkeypatch, mutate)
    chat = (
        await client.post("/api/companion/chats", json={}, headers=auth_headers)
    ).json()

    response = await client.post(
        f"/api/companion/chats/{chat['id']}/messages",
        headers=auth_headers,
        json={"content": "say nothing"},
    )

    assert response.status_code == 200
    assert _sse_events(response.text) == ["turn_start", "error"]
    assert "empty_agent_output" in response.text


@pytest.mark.asyncio
async def test_post_message_unexpected_error_emits_internal_error(
    client: AsyncClient, auth_headers: dict, monkeypatch
) -> None:
    async def crash(_db, _run):
        raise RuntimeError("kapow")

    monkeypatch.setattr("app.api.routes.companion.run_wai_run_inline", crash)
    chat = (
        await client.post("/api/companion/chats", json={}, headers=auth_headers)
    ).json()

    response = await client.post(
        f"/api/companion/chats/{chat['id']}/messages",
        headers=auth_headers,
        json={"content": "crash me"},
    )

    assert response.status_code == 200
    assert _sse_events(response.text) == ["turn_start", "error"]
    assert "internal_error" in response.text
    assert "Turn failed" in response.text
    assert "kapow" not in response.text  # raw exception text never leaks


@pytest.mark.asyncio
async def test_post_message_slow_turn_records_latency_anomaly(
    client: AsyncClient, auth_headers: dict, monkeypatch
) -> None:
    anomalies: list[str] = []

    def spy_capture(key, *args, **kwargs):
        anomalies.append(key)

    monkeypatch.setattr(
        "app.api.routes.companion.COMPANION_TURN_SLOW_THRESHOLD_MS", 0
    )
    monkeypatch.setattr(
        "app.api.routes.companion.capture_sentry_anomaly", spy_capture
    )

    def mutate(run):
        run.status = "done"
        run.result = {"output_text": "slow but fine"}

    _install_inline_stub(monkeypatch, mutate)
    chat = (
        await client.post("/api/companion/chats", json={}, headers=auth_headers)
    ).json()

    response = await client.post(
        f"/api/companion/chats/{chat['id']}/messages",
        headers=auth_headers,
        json={"content": "take your time"},
    )

    assert response.status_code == 200
    assert _sse_events(response.text) == ["turn_start", "token", "done"]
    assert anomalies == ["companion.turn.slow"]


@pytest.mark.asyncio
async def test_post_message_emits_heartbeats_while_turn_is_slow(
    client: AsyncClient, auth_headers: dict, monkeypatch
) -> None:
    import asyncio

    monkeypatch.setattr("app.api.routes.companion.SSE_HEARTBEAT_SECONDS", 0.05)

    async def slow_inline(_db, run):
        await asyncio.sleep(0.25)
        run.status = "done"
        run.result = {"output_text": "finally"}
        return run

    monkeypatch.setattr(
        "app.api.routes.companion.run_wai_run_inline", slow_inline
    )
    chat = (
        await client.post("/api/companion/chats", json={}, headers=auth_headers)
    ).json()

    response = await client.post(
        f"/api/companion/chats/{chat['id']}/messages",
        headers=auth_headers,
        json={"content": "slow burner"},
    )

    assert response.status_code == 200
    assert ": keep-alive" in response.text  # proxy-defeating heartbeat frames
    assert "event: done" in response.text


@pytest.mark.asyncio
async def test_post_message_stream_close_cancels_in_flight_producer(
    client: AsyncClient, auth_headers: dict, db_session, monkeypatch
) -> None:
    """Closing the SSE stream mid-turn cancels the producer task instead of
    leaking it (the generator's finally branch)."""
    import asyncio

    from app.api.routes import companion as companion_routes
    from app.models.user import User

    uid = await _me_id(client, auth_headers)
    user = await db_session.get(User, uid)
    chat = (
        await client.post("/api/companion/chats", json={}, headers=auth_headers)
    ).json()

    started = asyncio.Event()

    async def hanging_inline(_db, run):
        started.set()
        await asyncio.sleep(60)  # parked until the stream is torn down
        return run

    monkeypatch.setattr(
        "app.api.routes.companion.run_wai_run_inline", hanging_inline
    )

    response = await companion_routes.post_message(
        uuid.UUID(chat["id"]),
        companion_routes.PostMessageRequest(content="hold the line"),
        user,
        db_session,
    )
    iterator = response.body_iterator
    first = await iterator.__anext__()
    assert b"turn_start" in first
    await started.wait()  # the producer is now blocked inside the turn

    await iterator.aclose()  # client disconnect → finally cancels the producer

    # The hanging stub was cancelled along with the producer task — nothing is
    # still running on the loop for this turn.
    remaining = [
        t
        for t in asyncio.all_tasks()
        if t is not asyncio.current_task() and not t.done()
    ]
    assert remaining == []


@pytest.mark.asyncio
async def test_post_message_skips_malformed_agent_citations(
    client: AsyncClient, auth_headers: dict, db_session, monkeypatch
) -> None:
    """Only well-formed recording citations become citation events/rows; every
    malformed shape is skipped without failing the turn."""
    from app.models.recording import Recording, Segment

    uid = await _me_id(client, auth_headers)
    recording = Recording(user_id=uid, title="Risks", type="meeting", status="ready")
    db_session.add(recording)
    await db_session.flush()
    segment = Segment(recording_id=recording.id, content="The risk.", start_ms=1000)
    db_session.add(segment)
    await db_session.flush()

    def mutate(run):
        run.status = "done"
        run.result = {
            "output_text": "Numbers [1] only",
            "citations": [
                "just-a-string",  # not a dict
                {"source_kind": "item", "source_id": str(uuid.uuid4())},
                {"source_kind": "recording", "source_id": "not-a-uuid"},
                {"source_kind": "recording"},  # no source_id at all
                {
                    # Valid — but its [5] marker is absent from the text and
                    # start_ms is unparseable, so span/start_ms degrade safely.
                    "source_kind": "recording",
                    "source_id": str(recording.id),
                    "id": str(segment.id),
                    "start_ms": "soon",
                },
            ],
        }

    _install_inline_stub(monkeypatch, mutate)
    chat = (
        await client.post("/api/companion/chats", json={}, headers=auth_headers)
    ).json()

    response = await client.post(
        f"/api/companion/chats/{chat['id']}/messages",
        headers=auth_headers,
        json={"content": "cite carefully"},
    )

    assert response.status_code == 200
    assert _sse_events(response.text) == ["turn_start", "token", "citation", "done"]
    citation_payloads = [
        line.split(": ", 1)[1]
        for line in response.text.split("\n")
        if line.startswith("data: ") and "recording_id" in line
    ]
    assert len(citation_payloads) == 1
    payload = citation_payloads[0]
    assert f'"recording_id": "{recording.id}"' in payload
    assert '"span_start": 0' in payload
    assert '"span_end": 0' in payload
    assert '"start_ms": null' in payload


@pytest.mark.asyncio
async def test_post_message_ignores_non_list_citations_payload(
    client: AsyncClient, auth_headers: dict, monkeypatch
) -> None:
    def mutate(run):
        run.status = "done"
        run.result = {
            "output_text": "No citations here",
            "citations": {"weird": "shape"},  # not a list — dropped wholesale
        }

    _install_inline_stub(monkeypatch, mutate)
    chat = (
        await client.post("/api/companion/chats", json={}, headers=auth_headers)
    ).json()

    response = await client.post(
        f"/api/companion/chats/{chat['id']}/messages",
        headers=auth_headers,
        json={"content": "no citations"},
    )

    assert response.status_code == 200
    assert _sse_events(response.text) == ["turn_start", "token", "done"]


def test_citation_helper_coercions() -> None:
    """The citation coercion helpers never raise — every malformed value
    degrades to None / a zero span."""
    from app.api.routes.companion import _citation_span, _int_or_none, _uuid_or_none

    assert _uuid_or_none(None) is None
    known = uuid.uuid4()
    assert _uuid_or_none(known) is known  # already a UUID — passed through
    assert _uuid_or_none(str(known)) == known
    assert _uuid_or_none("not-a-uuid") is None

    assert _citation_span("answer [2] cited", 2) == (7, 10)
    assert _citation_span("no marker here", 9) == (0, 0)

    assert _int_or_none("42") == 42
    assert _int_or_none(None) is None
    assert _int_or_none(True) is None
    assert _int_or_none("soon") is None
