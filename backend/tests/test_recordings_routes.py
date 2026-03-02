"""Tests for recording endpoints and summary generation flows."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.summarizer import SummaryResult
from app.models.recording import ActionItem, Segment


async def _create_recording(
    client: AsyncClient,
    headers: dict,
    title: str | None = "Test Recording",
    type_: str = "note",
) -> dict:
    response = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": title, "type": type_, "language": "en"},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_create_recording_invalid_type_returns_422(client: AsyncClient, auth_headers: dict):
    """Recording type should be constrained to supported values."""
    response = await client.post(
        "/api/recordings",
        headers=auth_headers,
        json={"title": "Bad", "type": "invalid_type"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_recordings_can_filter_by_type(client: AsyncClient, auth_headers: dict):
    """List endpoint should filter recordings by type."""
    await _create_recording(client, auth_headers, title="Meeting A", type_="meeting")
    await _create_recording(client, auth_headers, title="Note A", type_="note")

    meeting_response = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"type": "meeting"},
    )
    assert meeting_response.status_code == 200
    meetings = meeting_response.json()
    assert len(meetings) == 1
    assert meetings[0]["type"] == "meeting"


@pytest.mark.asyncio
async def test_list_recordings_rejects_negative_skip(client: AsyncClient, auth_headers: dict):
    """Skip should not allow negative values."""
    response = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"skip": -1},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_recording_transcript_is_sorted_by_start_ms(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Transcript endpoint should return segments ordered by start timestamp."""
    recording = await _create_recording(client, auth_headers)
    recording_id = UUID(recording["id"])

    db_session.add_all(
        [
            Segment(
                recording_id=recording_id,
                speaker="Speaker 1",
                content="Second",
                start_ms=2000,
                end_ms=2500,
                confidence=0.9,
            ),
            Segment(
                recording_id=recording_id,
                speaker="Speaker 1",
                content="First",
                start_ms=500,
                end_ms=1000,
                confidence=0.95,
            ),
        ]
    )
    await db_session.flush()

    response = await client.get(f"/api/recordings/{recording_id}/transcript", headers=auth_headers)
    assert response.status_code == 200
    contents = [segment["content"] for segment in response.json()]
    assert contents == ["First", "Second"]


@pytest.mark.asyncio
async def test_get_summary_returns_404_when_not_generated(client: AsyncClient, auth_headers: dict):
    """Summary endpoint should return 404 until generated."""
    recording = await _create_recording(client, auth_headers)

    response = await client.get(f"/api/recordings/{recording['id']}/summary", headers=auth_headers)
    assert response.status_code == 404
    assert "not generated" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_generate_summary_requires_segments(client: AsyncClient, auth_headers: dict):
    """Generate summary should reject recordings without transcript segments."""
    recording = await _create_recording(client, auth_headers)
    response = await client.post(
        f"/api/recordings/{recording['id']}/generate-summary",
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "no transcript segments" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_generate_summary_creates_summary_and_action_items(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Generate summary should populate summary and action items with sanitized values."""
    recording = await _create_recording(client, auth_headers, title=None)
    recording_id = UUID(recording["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Ship the roadmap update by Friday.",
            start_ms=0,
            end_ms=1200,
            confidence=0.98,
        )
    )
    await db_session.flush()

    async def fake_summarize_transcript(_: str) -> SummaryResult:
        return SummaryResult(
            title="Roadmap Review",
            summary="Team reviewed roadmap and agreed next steps.",
            key_points=["Roadmap approved"],
            decisions=[{"decision": "Ship roadmap update", "context": "Sprint planning"}],
            action_items=[
                {
                    "task": "Prepare customer update",
                    "owner": "Alex",
                    "due": "2026-03-01",
                    "priority": "high",
                },
                {
                    "task": "Handle malformed due date",
                    "owner": "Sam",
                    "due": "not-a-date",
                    "priority": "unknown-priority",
                },
                {"task": "   ", "owner": "Nobody", "due": None, "priority": "low"},
            ],
            topics=["roadmap"],
            people_mentioned=["Alex", "Sam"],
            follow_up_questions=[],
            sentiment="positive",
        )

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", fake_summarize_transcript)

    response = await client.post(
        f"/api/recordings/{recording_id}/generate-summary",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["summary"]

    detail_response = await client.get(f"/api/recordings/{recording_id}", headers=auth_headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["title"] == "Roadmap Review"
    assert len(detail["action_items"]) == 2
    assert {item["priority"] for item in detail["action_items"]} == {"high", "medium"}


@pytest.mark.asyncio
async def test_generate_summary_regeneration_replaces_action_items(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Regeneration should replace old generated action items instead of duplicating them."""
    recording = await _create_recording(client, auth_headers, title="Retrospective")
    recording_id = UUID(recording["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Action items changed after discussion.",
            start_ms=0,
            end_ms=900,
            confidence=0.92,
        )
    )
    await db_session.flush()

    async def summarize_v1(_: str) -> SummaryResult:
        return SummaryResult(
            title="Retrospective V1",
            summary="First summary.",
            key_points=[],
            decisions=[],
            action_items=[{"task": "Old task", "owner": None, "due": None, "priority": "medium"}],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
        )

    async def summarize_v2(_: str) -> SummaryResult:
        return SummaryResult(
            title="Retrospective V2",
            summary="Second summary.",
            key_points=[],
            decisions=[],
            action_items=[{"task": "New task", "owner": None, "due": None, "priority": "high"}],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
        )

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", summarize_v1)
    first = await client.post(
        f"/api/recordings/{recording_id}/generate-summary",
        headers=auth_headers,
    )
    assert first.status_code == 200

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", summarize_v2)
    second = await client.post(
        f"/api/recordings/{recording_id}/generate-summary",
        headers=auth_headers,
    )
    assert second.status_code == 200

    detail_response = await client.get(f"/api/recordings/{recording_id}", headers=auth_headers)
    detail = detail_response.json()
    assert len(detail["action_items"]) == 1
    assert detail["action_items"][0]["task"] == "New task"


@pytest.mark.asyncio
async def test_generate_summary_preserves_manual_action_items(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Regeneration should only replace generated action items, preserving manual ones."""
    recording = await _create_recording(client, auth_headers, title="Manual Preservation")
    recording_id = UUID(recording["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Discuss tasks.",
            start_ms=0,
            end_ms=900,
            confidence=0.92,
        )
    )
    db_session.add(
        ActionItem(
            recording_id=recording_id,
            task="Manual task",
            owner="Taylor",
            priority="low",
            source="manual",
        )
    )
    await db_session.flush()

    async def summarize(_: str) -> SummaryResult:
        return SummaryResult(
            title="Manual Preservation",
            summary="Summary.",
            key_points=[],
            decisions=[],
            action_items=[{
                "task": "Generated task", "owner": None,
                "due": None, "priority": "medium",
            }],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
        )

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", summarize)
    response = await client.post(
        f"/api/recordings/{recording_id}/generate-summary",
        headers=auth_headers,
    )
    assert response.status_code == 200

    detail_response = await client.get(f"/api/recordings/{recording_id}", headers=auth_headers)
    detail = detail_response.json()
    tasks = sorted(item["task"] for item in detail["action_items"])
    assert tasks == ["Generated task", "Manual task"]
