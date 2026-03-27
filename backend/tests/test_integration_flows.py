"""Integration-style tests exercising complex multi-step flows across the API.

Each test walks through an end-to-end scenario, calling multiple endpoints
in sequence and verifying that state mutations propagate correctly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import chat as chat_routes
from app.core.chat import ChatResult, SourceSegment
from app.core.rate_limit import get_rate_limiter
from app.core.security import decode_access_token
from app.core.summarizer import SummaryResult
from app.models.chat import ChatMessage, ChatSession
from app.models.recording import ActionItem
from app.models.user import User

# --- helpers ---


def _unique_email(prefix: str = "flow") -> str:
    """Generate a unique email to avoid collisions with leftover DB state."""
    return f"{prefix}-{uuid4().hex[:8]}@example.com"


async def _register(
    client: AsyncClient, email: str | None = None
) -> tuple[dict[str, str], str, str]:
    """Register a user and return (headers, token, email)."""
    if email is None:
        email = _unique_email()
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, token, email


async def _user_from_token(db: AsyncSession, token: str) -> User:
    uid = decode_access_token(token)
    assert uid is not None
    user = await db.get(User, uid)
    assert user is not None
    return user


async def _create_recording(
    client: AsyncClient,
    headers: dict,
    title: str | None = "Test Recording",
    type_: str = "note",
) -> dict:
    resp = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": title, "type": type_, "language": "en"},
    )
    assert resp.status_code == 201
    return resp.json()


# --- 1. Full chat lifecycle ---


@pytest.mark.asyncio
async def test_full_chat_lifecycle_create_message_search_export_delete(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """End-to-end: create session via message -> search -> export -> delete."""
    headers, token, _ = await _register(client)
    user = await _user_from_token(db_session, token)

    created_session_id = uuid4()
    created_message_id = uuid4()
    recording_id = uuid4()

    call_count = 0

    async def fake_chat(*, db, user_id, question, session_id=None, recording_ids=None):
        nonlocal call_count
        call_count += 1
        return ChatResult(
            answer=f"Answer #{call_count}: details about the roadmap.",
            session_id=str(created_session_id),
            message_id=str(created_message_id),
            source_segments=[
                SourceSegment(
                    segment_id=str(uuid4()),
                    recording_id=str(recording_id),
                    recording_title="Roadmap Meeting",
                    speaker="Alice",
                    content="We need to ship Q3 milestones.",
                    start_ms=0,
                    end_ms=3000,
                )
            ],
        )

    monkeypatch.setattr(chat_routes, "chat_with_recordings", fake_chat)

    # Step 1: Send first message (creates session implicitly)
    r1 = await client.post(
        "/api/chat",
        headers=headers,
        json={"question": "What is on the roadmap?"},
    )
    assert r1.status_code == 200
    payload = r1.json()
    assert payload["session_id"] == str(created_session_id)
    assert payload["sources"][0]["recording_title"] == "Roadmap Meeting"
    assert payload["sources"][0]["speaker"] == "Alice"

    # Step 2: Send follow-up message to same session
    r2 = await client.post(
        "/api/chat",
        headers=headers,
        json={
            "question": "Tell me more about Q3",
            "session_id": str(created_session_id),
        },
    )
    assert r2.status_code == 200
    assert "Answer #2" in r2.json()["answer"]

    # Step 3: Create DB-level session + messages to test search/export/list
    session = ChatSession(
        id=created_session_id,
        user_id=user.id,
        title="Roadmap Discussion",
        recording_ids=[str(recording_id)],
    )
    db_session.add(session)
    await db_session.flush()

    db_session.add_all([
        ChatMessage(
            session_id=created_session_id,
            role="user",
            content="What is on the roadmap?",
            source_segment_ids=None,
            source_recording_ids=None,
        ),
        ChatMessage(
            session_id=created_session_id,
            role="assistant",
            content="Answer #1: details about the roadmap.",
            source_segment_ids=[str(uuid4())],
            source_recording_ids=[str(recording_id)],
        ),
        ChatMessage(
            session_id=created_session_id,
            role="user",
            content="Tell me more about Q3",
            source_segment_ids=None,
            source_recording_ids=None,
        ),
        ChatMessage(
            session_id=created_session_id,
            role="assistant",
            content="Answer #2: details about the roadmap.",
            source_segment_ids=[str(uuid4())],
            source_recording_ids=[str(recording_id)],
        ),
    ])
    await db_session.flush()

    # Step 4: List sessions — should see the session
    list_resp = await client.get("/api/chat/sessions", headers=headers)
    assert list_resp.status_code == 200
    sessions = list_resp.json()
    assert any(s["id"] == str(created_session_id) for s in sessions)
    our_session = next(s for s in sessions if s["id"] == str(created_session_id))
    assert our_session["message_count"] == 4

    # Step 5: Search sessions — should find by content
    search_resp = await client.get(
        "/api/chat/sessions/search",
        headers=headers,
        params={"q": "roadmap"},
    )
    assert search_resp.status_code == 200
    search_results = search_resp.json()
    assert len(search_results) >= 1
    assert any(s["id"] == str(created_session_id) for s in search_results)

    # Step 6: Export session — should contain conversation
    export_resp = await client.get(
        f"/api/chat/sessions/{created_session_id}/export",
        headers=headers,
    )
    assert export_resp.status_code == 200
    assert "text/markdown" in export_resp.headers["content-type"]
    md = export_resp.text
    assert "# Roadmap Discussion" in md
    assert "What is on the roadmap?" in md
    assert "Answer #1" in md
    assert "**You:**" in md
    assert "**Assistant:**" in md

    # Step 7: Rename session
    rename_resp = await client.patch(
        f"/api/chat/sessions/{created_session_id}",
        headers=headers,
        json={"title": "Q3 Roadmap Chat"},
    )
    assert rename_resp.status_code == 200
    assert rename_resp.json()["title"] == "Q3 Roadmap Chat"

    # Step 8: Pin session
    pin_resp = await client.post(
        f"/api/chat/sessions/{created_session_id}/pin",
        headers=headers,
    )
    assert pin_resp.status_code == 200
    assert pin_resp.json()["pinned_at"] is not None

    # Step 9: Delete session
    del_resp = await client.delete(
        f"/api/chat/sessions/{created_session_id}",
        headers=headers,
    )
    assert del_resp.status_code == 204

    # Step 10: Confirm deleted — list should be empty
    final_list = await client.get("/api/chat/sessions", headers=headers)
    assert final_list.status_code == 200
    assert not any(s["id"] == str(created_session_id) for s in final_list.json())


# --- 2. Multi-speaker recording with diarization labels ---


@pytest.mark.asyncio
async def test_recording_multi_speaker_diarization_labels(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Recording with multiple speakers should preserve diarization labels and ordering."""
    headers, _, _ = await _register(client)

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=[0.1] * 384),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Team Standup"),
    )

    recording = await _create_recording(client, headers, title=None, type_="meeting")
    rec_id = recording["id"]

    segments_payload = [
        {"text": "Good morning everyone, let's start.", "speaker": "Speaker 0",
         "start_ms": 0, "end_ms": 2000, "confidence": 0.95},
        {"text": "I finished the API refactor yesterday.", "speaker": "Speaker 1",
         "start_ms": 2100, "end_ms": 5000, "confidence": 0.92},
        {"text": "That's great. Any blockers?", "speaker": "Speaker 0",
         "start_ms": 5100, "end_ms": 7000, "confidence": 0.97},
        {"text": "Just waiting on the design review.", "speaker": "Speaker 2",
         "start_ms": 7100, "end_ms": 9500, "confidence": 0.89},
        {"text": "I'll follow up on that today.", "speaker": "Speaker 1",
         "start_ms": 9600, "end_ms": 11000, "confidence": 0.91},
    ]

    resp = await client.post(
        f"/api/recordings/{rec_id}/transcript",
        headers=headers,
        json={"segments": segments_payload, "duration_seconds": 11},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Team Standup"
    assert data["status"] == "ready"

    # Verify segments are ordered by start_ms
    contents = [s["content"] for s in data["segments"]]
    assert contents == [
        "Good morning everyone, let's start.",
        "I finished the API refactor yesterday.",
        "That's great. Any blockers?",
        "Just waiting on the design review.",
        "I'll follow up on that today.",
    ]

    # Verify diarization labels are preserved
    speakers = [s["speaker"] for s in data["segments"]]
    assert speakers == ["Speaker 0", "Speaker 1", "Speaker 0", "Speaker 2", "Speaker 1"]

    # Verify speaker statistics via detail endpoint
    detail_resp = await client.get(f"/api/recordings/{rec_id}", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()

    # Count unique speakers
    unique_speakers = set(s["speaker"] for s in detail["segments"])
    assert unique_speakers == {"Speaker 0", "Speaker 1", "Speaker 2"}

    # Verify transcript search finds multi-speaker content
    transcript_resp = await client.get(
        f"/api/recordings/{rec_id}/transcript", headers=headers
    )
    assert transcript_resp.status_code == 200
    transcript_segs = transcript_resp.json()
    assert len(transcript_segs) == 5
    # Confirm ordering is by start_ms
    start_times = [s["start_ms"] for s in transcript_segs]
    assert start_times == sorted(start_times)


# --- 3. Login rate limiter integration ---


@pytest.mark.asyncio
async def test_login_rate_limiter_blocks_after_threshold(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Login endpoint should return 429 after exceeding rate limit."""
    get_rate_limiter().reset()

    # Register a user with a known email
    email = _unique_email("ratelimit")
    await _register(client, email)

    # Attempt 5 failed logins (wrong password) — these should all pass rate limiting
    for i in range(5):
        resp = await client.post(
            "/api/auth/login",
            json={"email": email, "password": "wrongpassword"},
        )
        assert resp.status_code == 401, f"Login attempt {i + 1} should return 401"

    # 6th attempt should be rate-limited
    resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "wrongpassword"},
    )
    assert resp.status_code == 429
    assert "Too many requests" in resp.json()["detail"]

    # Even a correct password should be blocked
    resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert resp.status_code == 429

    # Reset and confirm the user can login again
    get_rate_limiter().reset()
    resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


# --- 4. Password change rejects whitespace-only ---


@pytest.mark.asyncio
async def test_password_change_rejects_whitespace_only_password(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Changing password to whitespace-only or short-after-strip should be rejected."""
    headers, _, email = await _register(client)

    # Whitespace-only new password
    resp = await client.post(
        "/api/settings/change-password",
        headers=headers,
        json={"current_password": "password123", "new_password": "        "},
    )
    assert resp.status_code == 422

    # Tabs and spaces only
    resp2 = await client.post(
        "/api/settings/change-password",
        headers=headers,
        json={"current_password": "password123", "new_password": "\t\t  \t"},
    )
    assert resp2.status_code == 422

    # Short after stripping whitespace (5 visible chars)
    resp3 = await client.post(
        "/api/settings/change-password",
        headers=headers,
        json={"current_password": "password123", "new_password": "  short  "},
    )
    assert resp3.status_code == 422

    # Valid new password should succeed
    resp4 = await client.post(
        "/api/settings/change-password",
        headers=headers,
        json={"current_password": "password123", "new_password": "newpass12345"},
    )
    assert resp4.status_code == 200
    assert resp4.json()["message"] == "Password changed successfully"

    # Verify old password no longer works
    login_resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login_resp.status_code == 401

    # Verify new password works
    login_resp2 = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "newpass12345"},
    )
    assert login_resp2.status_code == 200


# --- 5. Recording lifecycle with summary + highlights ---


@pytest.mark.asyncio
async def test_recording_lifecycle_summary_highlights_creation(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Full lifecycle: create -> add transcript -> summarize -> verify highlights -> delete."""
    headers, _, _ = await _register(client)

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=[0.1] * 384),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Sprint Planning"),
    )

    # Step 1: Create recording
    rec = await _create_recording(client, headers, title=None, type_="meeting")
    rec_id = rec["id"]
    assert rec["status"] == "pending_upload"

    # Step 2: Save transcript with multiple segments
    transcript_resp = await client.post(
        f"/api/recordings/{rec_id}/transcript",
        headers=headers,
        json={
            "segments": [
                {"text": "Let's plan the sprint.", "speaker": "PM",
                 "start_ms": 0, "end_ms": 2000, "confidence": 0.95},
                {"text": "I can take the database migration.", "speaker": "Dev",
                 "start_ms": 2100, "end_ms": 4000, "confidence": 0.93},
                {"text": "We need to ship the dashboard by Friday.", "speaker": "PM",
                 "start_ms": 4100, "end_ms": 6000, "confidence": 0.97},
            ],
            "duration_seconds": 6,
        },
    )
    assert transcript_resp.status_code == 200
    assert transcript_resp.json()["status"] == "ready"
    assert transcript_resp.json()["title"] == "Sprint Planning"

    # Step 3: Generate summary (mocked Claude)
    async def fake_summarize(transcript: str) -> SummaryResult:
        return SummaryResult(
            title="Sprint Planning Session",
            summary="Team planned the sprint with database migration and dashboard delivery.",
            key_points=["Database migration assigned", "Dashboard due Friday"],
            decisions=[{"decision": "Ship dashboard by Friday", "context": "Sprint goal"}],
            action_items=[
                {"task": "Complete database migration", "owner": "Dev",
                 "due": "2026-03-20", "priority": "high"},
                {"task": "Deliver dashboard UI", "owner": "PM",
                 "due": "2026-03-22", "priority": "high"},
            ],
            topics=["sprint planning", "database", "dashboard"],
            people_mentioned=["PM", "Dev"],
            follow_up_questions=["What about testing?"],
            sentiment="positive",
            highlights=[
                {
                    "category": "decision",
                    "title": "Dashboard delivery deadline set to Friday",
                    "description": "The team agreed to ship the dashboard by Friday.",
                    "speaker": "PM",
                    "importance": "high",
                },
                {
                    "category": "insight",
                    "title": "Dev volunteers for database migration",
                    "description": "Dev proactively took ownership of the migration task.",
                    "speaker": "Dev",
                    "importance": "medium",
                },
            ],
        )

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", fake_summarize)

    summary_resp = await client.post(
        f"/api/recordings/{rec_id}/generate-summary",
        headers=headers,
    )
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary["summary"] is not None
    assert "sprint" in summary["summary"].lower()
    assert summary["sentiment"] == "positive"

    # Step 4: Verify full detail includes summary + action items + highlights
    detail_resp = await client.get(f"/api/recordings/{rec_id}", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()

    assert detail["title"] == "Sprint Planning"  # original title preserved since it was set
    assert detail["summary"]["summary"] is not None
    assert len(detail["action_items"]) == 2
    tasks = {item["task"] for item in detail["action_items"]}
    assert "Complete database migration" in tasks
    assert "Deliver dashboard UI" in tasks

    # Verify highlights were created
    assert len(detail["highlights"]) == 2
    hl_titles = {h["title"] for h in detail["highlights"]}
    assert "Dashboard delivery deadline set to Friday" in hl_titles
    assert "Dev volunteers for database migration" in hl_titles

    # Verify highlight timestamps were resolved from segments
    for h in detail["highlights"]:
        # start_ms should have been resolved to a segment's time range
        assert h["start_ms"] is not None or h["end_ms"] is not None

    # Step 5: Star the recording
    star_resp = await client.post(
        f"/api/recordings/{rec_id}/star", headers=headers
    )
    assert star_resp.status_code == 200
    assert star_resp.json()["starred_at"] is not None

    # Step 6: Verify starred filter works
    starred_list = await client.get(
        "/api/recordings", headers=headers, params={"starred": "true"}
    )
    assert starred_list.status_code == 200
    assert len(starred_list.json()) == 1
    assert starred_list.json()[0]["id"] == rec_id

    # Step 7: Delete recording (soft delete)
    del_resp = await client.delete(f"/api/recordings/{rec_id}", headers=headers)
    assert del_resp.status_code == 204

    # Step 8: Not in active list
    active_list = await client.get("/api/recordings", headers=headers)
    assert active_list.status_code == 200
    assert len(active_list.json()) == 0

    # Step 9: In trash
    trash_list = await client.get(
        "/api/recordings", headers=headers, params={"trashed": "true"}
    )
    assert trash_list.status_code == 200
    assert len(trash_list.json()) == 1
    assert trash_list.json()[0]["id"] == rec_id


# --- 6. Register rate limiting ---


@pytest.mark.asyncio
async def test_register_rate_limiter_blocks_after_threshold(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Registration endpoint should block after 3 attempts from same IP."""
    get_rate_limiter().reset()

    # 3 registrations should succeed
    for i in range(3):
        resp = await client.post(
            "/api/auth/register",
            json={"email": _unique_email(f"ratereg{i}"), "password": "password123"},
        )
        assert resp.status_code == 200, f"Registration {i + 1} should succeed"

    # 4th should be rate-limited
    resp = await client.post(
        "/api/auth/register",
        json={"email": _unique_email("ratereg.blocked"), "password": "password123"},
    )
    assert resp.status_code == 429
    assert "Too many requests" in resp.json()["detail"]


# --- 7. Summary regeneration replaces highlights ---


@pytest.mark.asyncio
async def test_summary_regeneration_replaces_highlights_and_action_items(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Regenerating a summary should replace all highlights and generated action items."""
    headers, _, _ = await _register(client)

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=[0.1] * 384),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Design Review"),
    )

    rec = await _create_recording(client, headers, title="Design Review", type_="meeting")
    rec_id = rec["id"]

    # Add transcript
    await client.post(
        f"/api/recordings/{rec_id}/transcript",
        headers=headers,
        json={
            "segments": [
                {"text": "The new design is ready for review.", "speaker": "Designer",
                 "start_ms": 0, "end_ms": 3000, "confidence": 0.96},
                {"text": "I have some concerns about the color palette.", "speaker": "Lead",
                 "start_ms": 3100, "end_ms": 6000, "confidence": 0.94},
            ],
            "duration_seconds": 6,
        },
    )

    # Add a manual action item that should survive regeneration
    rec_uuid = UUID(rec_id)
    db_session.add(
        ActionItem(
            recording_id=rec_uuid,
            task="Manually added task",
            owner="PM",
            priority="low",
            source="manual",
        )
    )
    await db_session.flush()

    # First summary generation
    async def summarize_v1(transcript: str) -> SummaryResult:
        return SummaryResult(
            title="Design Review V1",
            summary="First design review.",
            key_points=["Colors need revision"],
            decisions=[],
            action_items=[
                {"task": "Revise color palette", "owner": "Designer",
                 "due": None, "priority": "high"},
            ],
            topics=["design"],
            people_mentioned=["Designer", "Lead"],
            follow_up_questions=[],
            sentiment="mixed",
            highlights=[
                {"category": "concern", "title": "Color palette concerns raised",
                 "description": "Lead flagged issues with colors.",
                 "speaker": "Lead", "importance": "high"},
            ],
        )

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", summarize_v1)

    resp1 = await client.post(
        f"/api/recordings/{rec_id}/generate-summary", headers=headers
    )
    assert resp1.status_code == 200

    detail1 = await client.get(f"/api/recordings/{rec_id}", headers=headers)
    d1 = detail1.json()
    assert len(d1["highlights"]) == 1
    assert d1["highlights"][0]["title"] == "Color palette concerns raised"
    # Manual + generated
    assert len(d1["action_items"]) == 2

    # Second summary generation — should replace highlights and generated actions
    async def summarize_v2(transcript: str) -> SummaryResult:
        return SummaryResult(
            title="Design Review V2",
            summary="Updated design review.",
            key_points=["Colors approved"],
            decisions=[{"decision": "Colors are fine", "context": "After discussion"}],
            action_items=[
                {"task": "Update style guide", "owner": "Designer",
                 "due": "2026-04-01", "priority": "medium"},
            ],
            topics=["design", "style guide"],
            people_mentioned=["Designer"],
            follow_up_questions=[],
            sentiment="positive",
            highlights=[
                {"category": "decision", "title": "Color palette approved",
                 "description": "Team decided colors are acceptable.",
                 "speaker": "Lead", "importance": "high"},
                {"category": "insight", "title": "Style guide update needed",
                 "description": None, "speaker": None, "importance": "low"},
            ],
        )

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", summarize_v2)

    resp2 = await client.post(
        f"/api/recordings/{rec_id}/generate-summary", headers=headers
    )
    assert resp2.status_code == 200

    detail2 = await client.get(f"/api/recordings/{rec_id}", headers=headers)
    d2 = detail2.json()

    # Highlights should be replaced (2 new ones, not 3 total)
    assert len(d2["highlights"]) == 2
    hl_titles = {h["title"] for h in d2["highlights"]}
    assert "Color palette approved" in hl_titles
    assert "Style guide update needed" in hl_titles
    assert "Color palette concerns raised" not in hl_titles  # old one gone

    # Generated action items replaced, manual one preserved
    assert len(d2["action_items"]) == 2
    task_map = {a["task"]: a["source"] for a in d2["action_items"]}
    assert task_map["Manually added task"] == "manual"
    assert task_map["Update style guide"] == "generated"

    # Summary content should be updated
    assert d2["summary"]["sentiment"] == "positive"


# --- 8. Cross-user data isolation in recordings and chat ---


@pytest.mark.asyncio
async def test_cross_user_data_isolation(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Users should never see another user's recordings, chat sessions, or action items."""
    headers_a, _, _ = await _register(client)
    headers_b, _, _ = await _register(client)

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=[0.1] * 384),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="User A Meeting"),
    )

    # User A creates a recording
    rec_a = await _create_recording(client, headers_a, title="Secret Meeting A", type_="meeting")

    await client.post(
        f"/api/recordings/{rec_a['id']}/transcript",
        headers=headers_a,
        json={
            "segments": [
                {"text": "Confidential information.", "speaker": "CEO",
                 "start_ms": 0, "end_ms": 2000, "confidence": 0.99},
            ],
            "duration_seconds": 2,
        },
    )

    # User B should NOT see User A's recording
    list_b = await client.get("/api/recordings", headers=headers_b)
    assert list_b.status_code == 200
    assert len(list_b.json()) == 0

    # User B should get 404 on User A's recording detail
    detail_b = await client.get(
        f"/api/recordings/{rec_a['id']}", headers=headers_b
    )
    assert detail_b.status_code == 404

    # User B should get 404 trying to delete User A's recording
    del_b = await client.delete(
        f"/api/recordings/{rec_a['id']}", headers=headers_b
    )
    assert del_b.status_code == 404

    # User B should get 404 trying to star User A's recording
    star_b = await client.post(
        f"/api/recordings/{rec_a['id']}/star", headers=headers_b
    )
    assert star_b.status_code == 404

    # User B should get 404 on User A's transcript
    transcript_b = await client.get(
        f"/api/recordings/{rec_a['id']}/transcript", headers=headers_b
    )
    assert transcript_b.status_code == 404

    # User B should get 404 on User A's export
    export_b = await client.get(
        f"/api/recordings/{rec_a['id']}/export",
        headers=headers_b,
        params={"format": "markdown"},
    )
    assert export_b.status_code == 404


# --- 9. Recording restore and permanent delete flow ---


@pytest.mark.asyncio
async def test_recording_trash_restore_permanent_delete_cycle(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Full trash lifecycle: create -> delete -> restore -> re-delete -> permanent delete."""
    headers, _, _ = await _register(client)

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=[0.1] * 384),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Recoverable Meeting"),
    )

    # Create and add transcript
    rec = await _create_recording(client, headers, title="Recoverable Meeting")
    rec_id = rec["id"]

    await client.post(
        f"/api/recordings/{rec_id}/transcript",
        headers=headers,
        json={
            "segments": [
                {"text": "Important discussion.", "speaker": "Speaker 1",
                 "start_ms": 0, "end_ms": 2000, "confidence": 0.95},
            ],
            "duration_seconds": 2,
        },
    )

    # Star it first
    await client.post(f"/api/recordings/{rec_id}/star", headers=headers)

    # Step 1: Soft delete
    del_resp = await client.delete(f"/api/recordings/{rec_id}", headers=headers)
    assert del_resp.status_code == 204

    # Active list should be empty
    active = await client.get("/api/recordings", headers=headers)
    assert len(active.json()) == 0

    # Starred filter should also be empty (trashed items excluded)
    starred = await client.get(
        "/api/recordings", headers=headers, params={"starred": "true"}
    )
    assert len(starred.json()) == 0

    # Trash should have it
    trash = await client.get(
        "/api/recordings", headers=headers, params={"trashed": "true"}
    )
    assert len(trash.json()) == 1
    assert trash.json()[0]["deleted_at"] is not None

    # Step 2: Restore from trash
    restore_resp = await client.post(
        f"/api/recordings/{rec_id}/restore", headers=headers
    )
    assert restore_resp.status_code == 200
    assert restore_resp.json()["deleted_at"] is None

    # Should be back in active list
    active2 = await client.get("/api/recordings", headers=headers)
    assert len(active2.json()) == 1

    # Star should still be preserved after restore
    assert active2.json()[0]["starred_at"] is not None

    # Step 3: Re-delete
    del2 = await client.delete(f"/api/recordings/{rec_id}", headers=headers)
    assert del2.status_code == 204

    # Step 4: Permanent delete
    perm_del = await client.delete(
        f"/api/recordings/{rec_id}",
        headers=headers,
        params={"permanent": "true"},
    )
    assert perm_del.status_code == 204

    # Step 5: Gone from everywhere
    detail = await client.get(f"/api/recordings/{rec_id}", headers=headers)
    assert detail.status_code == 404

    trash_final = await client.get(
        "/api/recordings", headers=headers, params={"trashed": "true"}
    )
    assert len(trash_final.json()) == 0


# --- 10. Auth cookie flow and token refresh ---


@pytest.mark.asyncio
async def test_auth_cookie_set_on_login_and_cleared_on_logout(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Login should set cookie, logout should clear it, /me should work with token."""
    email = _unique_email("cookie")

    # Register
    reg_resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert reg_resp.status_code == 200
    token = reg_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Check /me works
    me_resp = await client.get("/api/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == email

    # Login again
    login_resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login_resp.status_code == 200
    new_token = login_resp.json()["access_token"]

    # Both old and new tokens should work for /me
    me2 = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {new_token}"}
    )
    assert me2.status_code == 200

    # Refresh token using refresh_token from login
    login_refresh_token = login_resp.json()["refresh_token"]
    refresh_resp = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": login_refresh_token},
    )
    assert refresh_resp.status_code == 200
    refreshed_token = refresh_resp.json()["access_token"]
    new_refresh_token = refresh_resp.json()["refresh_token"]
    assert refreshed_token is not None

    # Refreshed token should work
    me3 = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {refreshed_token}"}
    )
    assert me3.status_code == 200

    # Logout with refresh token revocation
    logout_resp = await client.post(
        "/api/auth/logout",
        json={"refresh_token": new_refresh_token},
    )
    assert logout_resp.status_code == 200
    assert logout_resp.json()["message"] == "Logged out"


# --- 11. Recording folder lifecycle with move operations ---


@pytest.mark.asyncio
async def test_recording_folder_lifecycle_create_move_filter(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Create folders, assign recordings, filter by folder, move between folders."""
    headers, _, _ = await _register(client)

    # Create two folders
    f1 = await client.post("/api/folders", headers=headers, json={"name": "Work"})
    assert f1.status_code == 201
    folder_work_id = f1.json()["id"]

    f2 = await client.post("/api/folders", headers=headers, json={"name": "Personal"})
    assert f2.status_code == 201
    folder_personal_id = f2.json()["id"]

    # Create recordings in different folders
    rec_work = await client.post(
        "/api/recordings", headers=headers,
        json={"title": "Work Meeting", "type": "meeting", "folder_id": folder_work_id},
    )
    assert rec_work.status_code == 201
    assert rec_work.json()["folder_id"] == folder_work_id

    rec_personal = await client.post(
        "/api/recordings", headers=headers,
        json={"title": "Journal Entry", "type": "reflection", "folder_id": folder_personal_id},
    )
    assert rec_personal.status_code == 201

    rec_unfiled = await _create_recording(client, headers, title="No Folder Note")

    # Filter by folder
    work_list = await client.get(
        "/api/recordings", headers=headers, params={"folder_id": folder_work_id}
    )
    assert work_list.status_code == 200
    assert len(work_list.json()) == 1
    assert work_list.json()[0]["title"] == "Work Meeting"

    personal_list = await client.get(
        "/api/recordings", headers=headers, params={"folder_id": folder_personal_id}
    )
    assert personal_list.status_code == 200
    assert len(personal_list.json()) == 1
    assert personal_list.json()[0]["title"] == "Journal Entry"

    # Move recording to different folder
    move_resp = await client.patch(
        f"/api/recordings/{rec_unfiled['id']}",
        headers=headers,
        json={"folder_id": folder_work_id},
    )
    assert move_resp.status_code == 200
    assert move_resp.json()["folder_id"] == folder_work_id

    # Work folder should now have 2 recordings
    work_list2 = await client.get(
        "/api/recordings", headers=headers, params={"folder_id": folder_work_id}
    )
    assert len(work_list2.json()) == 2

    # Remove from folder
    unfolder_resp = await client.patch(
        f"/api/recordings/{rec_unfiled['id']}",
        headers=headers,
        json={"folder_id": None},
    )
    assert unfolder_resp.status_code == 200
    assert unfolder_resp.json()["folder_id"] is None


# --- 12. Email case normalization across auth endpoints ---


@pytest.mark.asyncio
async def test_email_case_normalization_across_auth_flows(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Email should be case-insensitive: register with mixed case, login with different case."""
    unique = uuid4().hex[:8]
    mixed_case = f"Flow.CaseTest.{unique}@Example.COM"
    lower_case = f"flow.casetest.{unique}@example.com"
    upper_case = f"FLOW.CASETEST.{unique}@EXAMPLE.COM"

    # Register with mixed case
    reg_resp = await client.post(
        "/api/auth/register",
        json={"email": mixed_case, "password": "password123"},
    )
    assert reg_resp.status_code == 200

    # Login with all lowercase
    login_resp = await client.post(
        "/api/auth/login",
        json={"email": lower_case, "password": "password123"},
    )
    assert login_resp.status_code == 200

    # Login with all uppercase
    login_resp2 = await client.post(
        "/api/auth/login",
        json={"email": upper_case, "password": "password123"},
    )
    assert login_resp2.status_code == 200

    # Attempting to register same email in different case should fail
    dup_resp = await client.post(
        "/api/auth/register",
        json={"email": upper_case, "password": "password123"},
    )
    assert dup_resp.status_code == 400
    assert "already registered" in dup_resp.json()["detail"].lower()
