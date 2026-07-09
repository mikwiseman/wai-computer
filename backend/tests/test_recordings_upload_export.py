"""Tests targeting upload and export paths for recordings.py coverage."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import UsageWeek
from app.models.recording import Recording
from app.models.user import User
from tests.conftest import LEGAL_ACCEPTANCE


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


async def _register_user(client: AsyncClient, email: str) -> dict:
    """Register a new user and return auth headers."""
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "testpassword123", **LEGAL_ACCEPTANCE},
    )
    data = response.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


async def _save_transcript(
    client: AsyncClient,
    headers: dict,
    recording_id: str,
    segments: list[dict],
    duration_seconds: int | None = None,
) -> int:
    """Save transcript segments to a recording, return the status code."""
    body: dict = {"segments": segments}
    if duration_seconds is not None:
        body["duration_seconds"] = duration_seconds
    response = await client.post(
        f"/api/recordings/{recording_id}/transcript",
        headers=headers,
        json=body,
    )
    return response.status_code


# ---------------------------------------------------------------------------
# 1. Upload audio with wav extension and correct mime type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_wav_file_with_correct_mime(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Uploading a .wav file with audio/wav content type should enqueue processing."""
    recording = await _create_recording(client, auth_headers)
    recording_id = recording["id"]

    enqueue_processing = AsyncMock()
    monkeypatch.setattr(
        "app.api.routes.recordings.enqueue_recording_audio_processing",
        enqueue_processing,
    )

    wav_content = b"RIFF" + b"\x00" * 40  # minimal bytes, will pass ext check
    response = await client.post(
        f"/api/recordings/{recording_id}/upload",
        headers=auth_headers,
        files={"file": ("recording.wav", wav_content, "audio/wav")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processing"
    assert data["segments"] == []
    enqueue_processing.assert_awaited_once()
    _, enqueue_kwargs = enqueue_processing.await_args
    assert enqueue_kwargs["content_type"] == "audio/wav"


# ---------------------------------------------------------------------------
# 2. Upload with unsupported extension returns error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_unsupported_extension_returns_415(
    client: AsyncClient,
    auth_headers: dict,
):
    """Uploading a file with an unsupported extension should return 415."""
    recording = await _create_recording(client, auth_headers)
    recording_id = recording["id"]

    # Video containers are importable now (audio gets extracted); a text file
    # is still not transcribable media.
    response = await client.post(
        f"/api/recordings/{recording_id}/upload",
        headers=auth_headers,
        files={"file": ("notes.txt", b"fake data", "text/plain")},
    )
    assert response.status_code == 415
    assert "Unsupported file type" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 3. Export as txt format
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_txt_format(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Exporting a recording as txt should return plain text with speaker labels."""
    recording = await _create_recording(client, auth_headers, title="My Note")
    recording_id = recording["id"]

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embeddings",
        AsyncMock(side_effect=lambda texts, **_: [[0.1] * 1536 for _ in texts]),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="My Note"),
    )

    segments = [
        {"text": "Hello from speaker A", "speaker": "Alice", "start_ms": 0, "end_ms": 2000},
        {"text": "Hello from speaker B", "speaker": "Bob", "start_ms": 2000, "end_ms": 4000},
    ]
    status_code = await _save_transcript(client, auth_headers, recording_id, segments)
    assert status_code == 200

    response = await client.get(
        f"/api/recordings/{recording_id}/export",
        headers=auth_headers,
        params={"format": "txt"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "Alice" in body
    assert "Bob" in body
    assert "Hello from speaker A" in body
    assert "Hello from speaker B" in body


# ---------------------------------------------------------------------------
# 4. Export as srt format includes timestamps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_srt_format_includes_timestamps(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Exporting a recording as srt should include SRT-formatted timestamps."""
    recording = await _create_recording(client, auth_headers, title="SRT Test")
    recording_id = recording["id"]

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embeddings",
        AsyncMock(side_effect=lambda texts, **_: [[0.1] * 1536 for _ in texts]),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="SRT Test"),
    )

    segments = [
        {"text": "First line", "speaker": "Alice", "start_ms": 1000, "end_ms": 3500},
        {"text": "Second line", "speaker": "Bob", "start_ms": 4000, "end_ms": 7200},
    ]
    status_code = await _save_transcript(client, auth_headers, recording_id, segments)
    assert status_code == 200

    response = await client.get(
        f"/api/recordings/{recording_id}/export",
        headers=auth_headers,
        params={"format": "srt"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/srt")
    body = response.text
    # SRT timestamps look like 00:00:01,000 --> 00:00:03,500
    assert "-->" in body
    assert "00:00:01,000" in body
    assert "00:00:03,500" in body
    # Verify entry numbering
    assert body.strip().startswith("1")


# ---------------------------------------------------------------------------
# 5. Export as json (markdown) format returns valid structured content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_markdown_format_returns_structured_content(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Exporting a recording as markdown should return structured markdown content."""
    recording = await _create_recording(client, auth_headers, title="Markdown Test")
    recording_id = recording["id"]

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embeddings",
        AsyncMock(side_effect=lambda texts, **_: [[0.1] * 1536 for _ in texts]),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Markdown Test"),
    )

    segments = [
        {"text": "Discussion about Q4 goals", "speaker": "Alice", "start_ms": 0, "end_ms": 5000},
    ]
    status_code = await _save_transcript(client, auth_headers, recording_id, segments)
    assert status_code == 200

    response = await client.get(
        f"/api/recordings/{recording_id}/export",
        headers=auth_headers,
        params={"format": "markdown"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    body = response.text
    # Markdown should have a title header
    assert "# Markdown Test" in body
    # Should have Transcript section
    assert "## Transcript" in body
    # Should contain speaker and content
    assert "Alice" in body
    assert "Discussion about Q4 goals" in body
    # Should have date and duration metadata
    assert "Date:" in body
    assert "Duration:" in body


# ---------------------------------------------------------------------------
# 6. Export nonexistent recording returns 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_nonexistent_recording_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Exporting a recording that does not exist should return 404."""
    fake_id = str(uuid4())
    response = await client.get(
        f"/api/recordings/{fake_id}/export",
        headers=auth_headers,
        params={"format": "txt"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Recording not found"


# ---------------------------------------------------------------------------
# 7. Export other user's recording returns 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_other_users_recording_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Exporting a recording owned by another user should return 404."""
    # Create recording as user A
    recording = await _create_recording(client, auth_headers, title="Private")
    recording_id = recording["id"]

    # Register a different user
    other_headers = await _register_user(client, f"other-{uuid4().hex}@example.com")

    response = await client.get(
        f"/api/recordings/{recording_id}/export",
        headers=other_headers,
        params={"format": "txt"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Recording not found"


# ---------------------------------------------------------------------------
# 8. Upload queues single-channel processing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_queues_single_channel_processing(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Upload should stage an MP3 and enqueue canonical processing."""
    recording = await _create_recording(client, auth_headers, title=None)
    recording_id = recording["id"]

    enqueue_processing = AsyncMock()
    monkeypatch.setattr(
        "app.api.routes.recordings.enqueue_recording_audio_processing",
        enqueue_processing,
    )

    response = await client.post(
        f"/api/recordings/{recording_id}/upload",
        headers=auth_headers,
        files={"file": ("test.mp3", b"\x00" * 100, "audio/mpeg")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processing"
    assert data["segments"] == []
    enqueue_processing.assert_awaited_once()
    _, enqueue_kwargs = enqueue_processing.await_args
    assert enqueue_kwargs["content_type"] == "audio/mpeg"


# ---------------------------------------------------------------------------
# 9. Upload queues multichannel-capable files
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_queues_wav_processing(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Upload should stage a WAV and enqueue canonical processing."""
    recording = await _create_recording(client, auth_headers, title=None)
    recording_id = recording["id"]

    enqueue_processing = AsyncMock()
    monkeypatch.setattr(
        "app.api.routes.recordings.enqueue_recording_audio_processing",
        enqueue_processing,
    )

    wav_content = b"RIFF" + b"\x00" * 40
    response = await client.post(
        f"/api/recordings/{recording_id}/upload",
        headers=auth_headers,
        files={"file": ("stereo.wav", wav_content, "audio/wav")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processing"
    assert data["segments"] == []
    enqueue_processing.assert_awaited_once()
    _, enqueue_kwargs = enqueue_processing.await_args
    assert enqueue_kwargs["content_type"] == "audio/wav"


# ---------------------------------------------------------------------------
# 10. Save transcript with empty segments array
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_transcript_records_weekly_usage_without_double_counting(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    recording = await _create_recording(client, auth_headers)
    recording_id = recording["id"]
    segments = [
        {"speaker": "A", "text": "one two", "start_ms": 0, "end_ms": 1000, "confidence": 0.9},
        {"speaker": "B", "text": "three four", "start_ms": 1000, "end_ms": 2000, "confidence": 0.9},
    ]

    first_status = await _save_transcript(client, auth_headers, recording_id, segments)
    second_status = await _save_transcript(client, auth_headers, recording_id, segments)

    assert first_status == 200
    assert second_status == 200
    user = (await db_session.execute(select(User))).scalars().first()
    assert user is not None
    usage = (
        await db_session.execute(select(UsageWeek).where(UsageWeek.user_id == user.id))
    ).scalar_one()
    assert usage.words_used == 4
    stored = await db_session.get(Recording, recording_id)
    assert stored is not None
    assert stored.billed_word_count == 4


@pytest.mark.asyncio
async def test_save_transcript_empty_segments_marks_recording_failed(
    client: AsyncClient,
    auth_headers: dict,
):
    """Saving a transcript with no speech must not create a ready empty recording."""
    recording = await _create_recording(client, auth_headers)
    recording_id = recording["id"]

    response = await client.post(
        f"/api/recordings/{recording_id}/transcript",
        headers=auth_headers,
        json={"segments": []},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["segments"] == []
    assert data["failure_code"] == "transcript_empty"
    assert data["failure_message"] == "We could not detect clear speech in this recording."


# ---------------------------------------------------------------------------
# 11. Save transcript with very long text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_transcript_with_very_long_text(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Saving a transcript with very long segment text should succeed."""
    recording = await _create_recording(client, auth_headers, title=None)
    recording_id = recording["id"]

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embeddings",
        AsyncMock(side_effect=lambda texts, **_: [[0.1] * 1536 for _ in texts]),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Long Text Recording"),
    )

    long_text = "word " * 10000  # ~50000 chars
    segments = [
        {
            "text": long_text.strip(),
            "speaker": "Speaker 0",
            "start_ms": 0,
            "end_ms": 600000,
        },
    ]
    response = await client.post(
        f"/api/recordings/{recording_id}/transcript",
        headers=auth_headers,
        json={"segments": segments},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert len(data["segments"]) == 1
    assert len(data["segments"][0]["content"]) > 40000


# ---------------------------------------------------------------------------
# 12. Generate summary when no segments exist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_summary_no_segments_returns_400(
    client: AsyncClient,
    auth_headers: dict,
):
    """Generating a summary for a recording with no transcript should return 400."""
    recording = await _create_recording(client, auth_headers, title="Empty")
    recording_id = recording["id"]

    response = await client.post(
        f"/api/recordings/{recording_id}/generate-summary",
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "No transcript segments" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 13. Save transcript with only whitespace segments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_transcript_whitespace_only_segments_return_ready_recording(
    client: AsyncClient,
    auth_headers: dict,
):
    """Whitespace-only segments should surface the no-speech state."""
    recording = await _create_recording(client, auth_headers)
    recording_id = recording["id"]

    segments = [
        {"text": "   ", "speaker": "Alice", "start_ms": 0, "end_ms": 1000},
        {"text": "\n\t", "speaker": "Bob", "start_ms": 1000, "end_ms": 2000},
    ]
    response = await client.post(
        f"/api/recordings/{recording_id}/transcript",
        headers=auth_headers,
        json={"segments": segments},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["failure_code"] == "transcript_empty"
    assert data["segments"] == []


# ---------------------------------------------------------------------------
# 14. Upload to nonexistent recording returns 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_to_nonexistent_recording_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Uploading audio to a non-existent recording should return 404."""
    fake_id = str(uuid4())
    response = await client.post(
        f"/api/recordings/{fake_id}/upload",
        headers=auth_headers,
        files={"file": ("test.mp3", b"\x00" * 10, "audio/mpeg")},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Recording not found"


# ---------------------------------------------------------------------------
# 15. Export srt with no segments returns empty body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_srt_no_segments_returns_empty(
    client: AsyncClient,
    auth_headers: dict,
):
    """Exporting srt for a recording with no segments should return an empty body."""
    recording = await _create_recording(client, auth_headers, title="No Segments")
    recording_id = recording["id"]

    response = await client.get(
        f"/api/recordings/{recording_id}/export",
        headers=auth_headers,
        params={"format": "srt"},
    )
    assert response.status_code == 200
    assert response.text.strip() == ""


# ---------------------------------------------------------------------------
# 16. Save transcript sets duration from end times
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_transcript_sets_duration_from_end_times(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """After saving a transcript, recording duration should be derived from segment end_ms."""
    recording = await _create_recording(client, auth_headers, title="Duration Test")
    recording_id = recording["id"]

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embeddings",
        AsyncMock(side_effect=lambda texts, **_: [[0.1] * 1536 for _ in texts]),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Duration Test"),
    )

    segments = [
        {"text": "First", "speaker": "A", "start_ms": 0, "end_ms": 10000},
        {"text": "Second", "speaker": "B", "start_ms": 10000, "end_ms": 25000},
        {"text": "Third", "speaker": "A", "start_ms": 25000, "end_ms": 42000},
    ]
    response = await client.post(
        f"/api/recordings/{recording_id}/transcript",
        headers=auth_headers,
        json={"segments": segments},
    )
    assert response.status_code == 200
    data = response.json()
    # 42000ms // 1000 = 42s
    assert data["duration_seconds"] == 42


# ---------------------------------------------------------------------------
# 17. Upload processing failure marks recording as failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_processing_failure_marks_recording_failed(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """If queueing fails during upload, recording should be marked as failed."""
    recording = await _create_recording(client, auth_headers, title="Fail Test")
    recording_id = recording["id"]

    monkeypatch.setattr(
        "app.api.routes.recordings.enqueue_recording_audio_processing",
        AsyncMock(side_effect=RuntimeError("queue connection timeout")),
    )

    response = await client.post(
        f"/api/recordings/{recording_id}/upload",
        headers=auth_headers,
        files={"file": ("test.mp3", b"\x00" * 100, "audio/mpeg")},
    )
    assert response.status_code == 503
    stored = await db_session.get(Recording, recording_id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.failure_code == "processing_enqueue_failed"
    assert stored.failure_message == "Failed to start recording processing"


# ---------------------------------------------------------------------------
# 18. Export txt content-disposition header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_content_disposition_header(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Export should set a Content-Disposition header with a sanitized filename."""
    recording = await _create_recording(client, auth_headers, title="My/Special:File")
    recording_id = recording["id"]

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embeddings",
        AsyncMock(side_effect=lambda texts, **_: [[0.1] * 1536 for _ in texts]),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="My/Special:File"),
    )

    segments = [
        {"text": "Hello", "speaker": "A", "start_ms": 0, "end_ms": 1000},
    ]
    await _save_transcript(client, auth_headers, recording_id, segments)

    response = await client.get(
        f"/api/recordings/{recording_id}/export",
        headers=auth_headers,
        params={"format": "txt"},
    )
    assert response.status_code == 200
    disposition = response.headers.get("content-disposition", "")
    assert "attachment" in disposition
    assert ".txt" in disposition
    # Unsafe characters should be stripped
    assert "/" not in disposition.split("filename=")[1]
    assert ":" not in disposition.split("filename=")[1]
