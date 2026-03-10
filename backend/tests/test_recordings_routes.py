"""Tests for recording endpoints and summary generation flows."""

import json
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deepgram import TranscriptResult
from app.core.summarizer import SummaryResult
from app.models.recording import ActionItem, Segment, Summary


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
async def test_delete_recording_moves_to_trash_and_can_be_restored(
    client: AsyncClient,
    auth_headers: dict,
):
    """Delete should soft-delete into trash until explicitly restored or removed."""
    recording = await _create_recording(client, auth_headers, title="Trash Me")

    delete_response = await client.delete(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
    )
    assert delete_response.status_code == 204

    active_response = await client.get("/api/recordings", headers=auth_headers)
    assert active_response.status_code == 200
    assert active_response.json() == []

    trashed_response = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"trashed": "true"},
    )
    assert trashed_response.status_code == 200
    assert [item["id"] for item in trashed_response.json()] == [recording["id"]]
    assert trashed_response.json()[0]["deleted_at"] is not None

    restore_response = await client.post(
        f"/api/recordings/{recording['id']}/restore",
        headers=auth_headers,
    )
    assert restore_response.status_code == 200
    assert restore_response.json()["deleted_at"] is None

    restored_response = await client.get("/api/recordings", headers=auth_headers)
    assert restored_response.status_code == 200
    assert [item["id"] for item in restored_response.json()] == [recording["id"]]


@pytest.mark.asyncio
async def test_delete_recording_can_permanently_delete_from_trash(
    client: AsyncClient,
    auth_headers: dict,
):
    """A trashed recording should be removable permanently."""
    recording = await _create_recording(client, auth_headers, title="Permanent Delete")

    first_delete = await client.delete(f"/api/recordings/{recording['id']}", headers=auth_headers)
    assert first_delete.status_code == 204

    second_delete = await client.delete(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
        params={"permanent": "true"},
    )
    assert second_delete.status_code == 204

    detail_response = await client.get(f"/api/recordings/{recording['id']}", headers=auth_headers)
    assert detail_response.status_code == 404


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


# ---- Upload endpoint tests ----


@pytest.mark.asyncio
async def test_upload_nonexistent_recording_returns_404(client: AsyncClient, auth_headers: dict):
    """Upload to a nonexistent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.post(
        f"/api/recordings/{fake_id}/upload",
        headers=auth_headers,
        files={"file": ("test.mp3", b"fake-audio", "audio/mpeg")},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_upload_unsupported_file_type_returns_415(client: AsyncClient, auth_headers: dict):
    """Upload with unsupported file extension should return 415."""
    recording = await _create_recording(client, auth_headers)
    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("test.txt", b"not-audio", "text/plain")},
    )
    assert response.status_code == 415
    assert "Unsupported file type" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_success_with_mocked_services(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Successful upload should transcribe and return recording detail."""
    recording = await _create_recording(client, auth_headers, title=None)

    fake_transcripts = [
        TranscriptResult(
            text="Hello world",
            speaker="Speaker 0",
            is_final=True,
            start_ms=0,
            end_ms=1500,
            confidence=0.98,
        ),
    ]

    mock_storage = AsyncMock()
    mock_storage.upload_audio_fileobj = AsyncMock(return_value="user/2026/01/01/rec.mp3")

    monkeypatch.setattr(
        "app.api.routes.recordings.transcribe_audio_file",
        AsyncMock(return_value=fake_transcripts),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.get_storage_client",
        lambda: mock_storage,
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=[0.1] * 384),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Hello World Meeting"),
    )

    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("meeting.mp3", b"fake-mp3-data", "audio/mpeg")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Hello World Meeting"
    assert data["audio_url"] == "user/2026/01/01/rec.mp3"
    assert data["status"] == "ready"
    assert data["duration_seconds"] == 1
    assert len(data["segments"]) == 1
    assert data["segments"][0]["content"] == "Hello world"


@pytest.mark.asyncio
async def test_upload_too_large_marks_recording_failed_and_keeps_it_visible(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Oversized upload should fail explicitly without hiding the recording."""
    recording = await _create_recording(client, auth_headers)
    monkeypatch.setattr("app.api.routes.recordings.MAX_UPLOAD_SIZE", 4)

    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("large.mp3", b"12345", "audio/mpeg")},
    )
    assert response.status_code == 413
    assert "Maximum size" in response.json()["detail"]

    detail_response = await client.get(f"/api/recordings/{recording['id']}", headers=auth_headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["status"] == "failed"
    assert detail["failure_code"] == "file_too_large"
    assert detail["audio_url"] is None

    list_response = await client.get("/api/recordings", headers=auth_headers)
    assert list_response.status_code == 200
    items = {item["id"]: item for item in list_response.json()}
    assert items[recording["id"]]["status"] == "failed"


@pytest.mark.asyncio
async def test_save_transcript_persists_segments_before_audio_upload(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Live transcript segments should be savable before durable audio completes."""
    recording = await _create_recording(client, auth_headers, title=None)

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=[0.1] * 384),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Transcript First"),
    )

    response = await client.post(
        f"/api/recordings/{recording['id']}/transcript",
        headers=auth_headers,
        json={
            "duration_seconds": 3,
            "segments": [
                {
                    "text": "Transcript saved first",
                    "speaker": "Speaker 1",
                    "start_ms": 0,
                    "end_ms": 2400,
                    "confidence": 0.93,
                }
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["title"] == "Transcript First"
    assert data["duration_seconds"] == 2
    assert [segment["content"] for segment in data["segments"]] == ["Transcript saved first"]


@pytest.mark.asyncio
async def test_upload_processing_failure_returns_failed_recording_with_audio_preserved(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Audio should remain linked when post-upload processing fails."""
    recording = await _create_recording(client, auth_headers, title=None)

    mock_storage = AsyncMock()
    mock_storage.upload_audio_fileobj = AsyncMock(return_value="user/2026/01/01/rec.mp3")

    monkeypatch.setattr(
        "app.api.routes.recordings.get_storage_client",
        lambda: mock_storage,
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.transcribe_audio_file",
        AsyncMock(side_effect=RuntimeError("Deepgram unavailable")),
    )

    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("meeting.mp3", b"fake-mp3-data", "audio/mpeg")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["failure_code"] == "processing_failed"
    assert data["audio_url"] == "user/2026/01/01/rec.mp3"
    assert data["segments"] == []


@pytest.mark.asyncio
async def test_upload_storage_failure_marks_recording_failed_and_keeps_record_visible(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """If durable storage fails, the recording should remain visible with a failed state."""
    recording = await _create_recording(client, auth_headers, title=None)

    mock_storage = AsyncMock()
    mock_storage.upload_audio_fileobj = AsyncMock(side_effect=RuntimeError("S3 unavailable"))

    monkeypatch.setattr(
        "app.api.routes.recordings.get_storage_client",
        lambda: mock_storage,
    )

    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("meeting.mp3", b"fake-mp3-data", "audio/mpeg")},
    )
    assert response.status_code == 503
    assert "failed to store imported audio" in response.json()["detail"].lower()

    detail_response = await client.get(f"/api/recordings/{recording['id']}", headers=auth_headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["status"] == "failed"
    assert detail["failure_code"] == "storage_upload_failed"
    assert detail["audio_url"] is None


@pytest.mark.asyncio
async def test_reupload_replaces_segments_summary_and_generated_action_items(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Retrying an upload should replace derived content instead of appending to it."""
    recording = await _create_recording(client, auth_headers, title=None)
    recording_id = UUID(recording["id"])

    mock_storage = AsyncMock()
    mock_storage.upload_audio_fileobj = AsyncMock(return_value="user/2026/01/01/rec.mp3")

    monkeypatch.setattr(
        "app.api.routes.recordings.get_storage_client",
        lambda: mock_storage,
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=[0.1] * 384),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Recovered Recording"),
    )

    first_upload = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        data={
            "segments_json": json.dumps(
                [
                    {
                        "text": "First upload",
                        "speaker": "Speaker 1",
                        "start_ms": 0,
                        "end_ms": 1000,
                        "confidence": 0.9,
                    }
                ]
            )
        },
        files={"file": ("meeting.mp3", b"fake-mp3-data", "audio/mpeg")},
    )
    assert first_upload.status_code == 200

    db_session.add(
        Summary(
            recording_id=recording_id,
            summary="Old summary",
        )
    )
    db_session.add(
        ActionItem(
            recording_id=recording_id,
            task="Generated action",
            priority="medium",
            source="generated",
        )
    )
    db_session.add(
        ActionItem(
            recording_id=recording_id,
            task="Manual action",
            priority="low",
            source="manual",
        )
    )
    await db_session.flush()

    second_upload = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        data={
            "segments_json": json.dumps(
                [
                    {
                        "text": "Second upload",
                        "speaker": "Speaker 2",
                        "start_ms": 0,
                        "end_ms": 1500,
                        "confidence": 0.95,
                    }
                ]
            )
        },
        files={"file": ("meeting.mp3", b"new-fake-mp3-data", "audio/mpeg")},
    )
    assert second_upload.status_code == 200
    data = second_upload.json()
    assert [segment["content"] for segment in data["segments"]] == ["Second upload"]
    assert data["summary"] is None
    assert [item["task"] for item in data["action_items"]] == ["Manual action"]
