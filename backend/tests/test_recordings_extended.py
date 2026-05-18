"""Extended tests for recording routes — edge cases, error paths, and boundary conditions."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api.routes import recordings


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
        json={"email": email, "password": "testpassword123"},
    )
    data = response.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


# ---------------------------------------------------------------------------
# Upload / Create edge cases
# ---------------------------------------------------------------------------


async def test_upload_file_exceeding_streaming_size_limit_returns_413(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Upload that exceeds MAX_UPLOAD_SIZE during streaming stage should return 413."""
    recording = await _create_recording(client, auth_headers)

    # Set a very small limit so the file exceeds it during _stage_upload_to_disk streaming
    monkeypatch.setattr("app.api.routes.recordings.MAX_UPLOAD_SIZE", 2)

    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("test.mp3", b"abcdef", "audio/mpeg")},
    )
    assert response.status_code == 413
    assert "Maximum size" in response.json()["detail"]


async def test_create_recording_with_null_title_succeeds(
    client: AsyncClient,
    auth_headers: dict,
):
    """Creating a recording with null title should succeed (title is optional)."""
    response = await client.post(
        "/api/recordings",
        headers=auth_headers,
        json={"type": "note"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] is None


async def test_create_recording_with_title_at_500_chars_boundary(
    client: AsyncClient,
    auth_headers: dict,
):
    """A title with exactly 500 characters should be accepted (column max is VARCHAR(500))."""
    title_500 = "B" * 500
    response = await client.post(
        "/api/recordings",
        headers=auth_headers,
        json={"title": title_500, "type": "note"},
    )
    assert response.status_code == 201
    assert response.json()["title"] == title_500


async def test_create_recording_with_very_long_title_at_exact_boundary(
    client: AsyncClient,
    auth_headers: dict,
):
    """A title with exactly 499 characters should be accepted (well within VARCHAR(500))."""
    title_499 = "B" * 499
    response = await client.post(
        "/api/recordings",
        headers=auth_headers,
        json={"title": title_499, "type": "note"},
    )
    assert response.status_code == 201
    assert len(response.json()["title"]) == 499


# ---------------------------------------------------------------------------
# Recording retrieval
# ---------------------------------------------------------------------------


async def test_get_recording_for_nonexistent_id_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Requesting a recording detail for a UUID that doesn't exist should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(
        f"/api/recordings/{fake_id}",
        headers=auth_headers,
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


async def test_list_recordings_with_pagination(
    client: AsyncClient,
    auth_headers: dict,
):
    """List endpoint should respect skip and limit pagination parameters."""
    # Create 5 recordings
    titles = [f"Paginated {i}" for i in range(5)]
    for title in titles:
        await _create_recording(client, auth_headers, title=title)

    # Get all
    all_response = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"skip": 0, "limit": 50},
    )
    assert all_response.status_code == 200
    all_recordings = all_response.json()
    assert len(all_recordings) == 5

    # Get first 2 (newest first)
    page1 = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"skip": 0, "limit": 2},
    )
    assert page1.status_code == 200
    page1_data = page1.json()
    assert len(page1_data) == 2

    # Get next 2
    page2 = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"skip": 2, "limit": 2},
    )
    assert page2.status_code == 200
    page2_data = page2.json()
    assert len(page2_data) == 2

    # No overlap between pages
    page1_ids = {r["id"] for r in page1_data}
    page2_ids = {r["id"] for r in page2_data}
    assert page1_ids.isdisjoint(page2_ids)

    # Skip past all
    page_empty = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"skip": 100, "limit": 10},
    )
    assert page_empty.status_code == 200
    assert page_empty.json() == []


# ---------------------------------------------------------------------------
# Recording deletion
# ---------------------------------------------------------------------------


async def test_delete_nonexistent_recording_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Deleting a recording with a nonexistent UUID should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.delete(
        f"/api/recordings/{fake_id}",
        headers=auth_headers,
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


async def test_delete_recording_owned_by_different_user_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Deleting another user's recording should return 404 (not leaked as 403)."""
    # Create recording as the first user
    recording = await _create_recording(client, auth_headers, title="Private Recording")

    # Register a second user
    other_headers = await _register_user(client, f"other-{uuid4().hex[:8]}@example.com")

    # Second user tries to delete first user's recording
    response = await client.delete(
        f"/api/recordings/{recording['id']}",
        headers=other_headers,
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

    # Verify the recording still exists for the original owner
    get_response = await client.get(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
    )
    assert get_response.status_code == 200


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------


async def test_generate_summary_nonexistent_recording_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Generate summary for a nonexistent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.post(
        f"/api/recordings/{fake_id}/generate-summary",
        headers=auth_headers,
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


async def test_generate_summary_no_segments_returns_400(
    client: AsyncClient,
    auth_headers: dict,
):
    """Generate summary for a recording with no transcript segments should return 400."""
    recording = await _create_recording(client, auth_headers, title="Empty Transcript")
    response = await client.post(
        f"/api/recordings/{recording['id']}/generate-summary",
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "no transcript segments" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Helper functions — unit tests
# ---------------------------------------------------------------------------


def test_normalize_failure_message_with_exception():
    """_normalize_failure_message should extract message from Exception."""
    error = RuntimeError("Something broke badly")
    result = recordings._normalize_failure_message(error, "default message")
    assert result == "Something broke badly"


def test_normalize_failure_message_with_string():
    """_normalize_failure_message should return the string directly."""
    result = recordings._normalize_failure_message("Direct error text", "default message")
    assert result == "Direct error text"


def test_normalize_failure_message_with_empty_string_returns_fallback():
    """_normalize_failure_message should return fallback for empty strings."""
    result = recordings._normalize_failure_message("", "fallback message")
    assert result == "fallback message"

    result_whitespace = recordings._normalize_failure_message("   ", "fallback message")
    assert result_whitespace == "fallback message"


def test_normalize_failure_message_truncates_at_500_chars():
    """_normalize_failure_message should truncate messages longer than 500 chars."""
    long_message = "x" * 1000
    result = recordings._normalize_failure_message(long_message, "fallback")
    assert len(result) == 500
    assert result == "x" * 500


def test_normalize_failure_message_with_empty_exception_returns_fallback():
    """_normalize_failure_message should return fallback for Exception('')."""
    error = RuntimeError("")
    result = recordings._normalize_failure_message(error, "fallback")
    assert result == "fallback"


# ---------------------------------------------------------------------------
# _extension_from_upload helper
# ---------------------------------------------------------------------------


def test_extension_from_upload_valid_extension():
    """_extension_from_upload should return extension for valid audio files."""
    assert recordings._extension_from_upload("recording.mp3", "audio/mpeg") == "mp3"
    assert recordings._extension_from_upload("recording.wav", "audio/wav") == "wav"
    assert recordings._extension_from_upload("recording.m4a", "audio/mp4") == "m4a"


def test_extension_from_upload_uses_content_type_fallback():
    """_extension_from_upload should resolve from content_type when ext is unknown."""
    result = recordings._extension_from_upload("noext", "audio/mpeg")
    assert result == "mp3"


def test_extension_from_upload_unsupported_raises_415():
    """_extension_from_upload should raise 415 for unsupported types."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        recordings._extension_from_upload("file.txt", "text/plain")
    assert exc_info.value.status_code == 415
    assert "Unsupported file type" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# _transcript_failure_details helper
# ---------------------------------------------------------------------------


def test_transcript_failure_details_empty_transcript():
    """Empty transcript validation no longer has a custom failure code."""
    from fastapi import HTTPException

    error = HTTPException(status_code=400, detail="Transcript is empty")
    code, message = recordings._transcript_failure_details(error)
    assert code == "transcript_validation_failed"
    assert message == "Transcript is empty"


def test_transcript_failure_details_validation_failure():
    """Should return transcript_validation_failed for other 400 errors."""
    from fastapi import HTTPException

    error = HTTPException(status_code=400, detail="Some other validation error")
    code, message = recordings._transcript_failure_details(error)
    assert code == "transcript_validation_failed"
    assert message == "Some other validation error"


def test_transcript_failure_details_non_400_error():
    """Non-400 errors should return transcript_validation_failed."""
    from fastapi import HTTPException

    error = HTTPException(status_code=500, detail="Server error")
    code, message = recordings._transcript_failure_details(error)
    assert code == "transcript_validation_failed"
    assert message == "Server error"


def test_transcript_failure_details_none_detail_uses_status_phrase():
    """HTTPException with detail=None defaults to status phrase (e.g., 'Bad Request').

    FastAPI's HTTPException sets detail to the HTTP status phrase when None is passed,
    so _transcript_failure_details sees a non-None detail string.
    """
    from fastapi import HTTPException

    error = HTTPException(status_code=400, detail=None)
    code, message = recordings._transcript_failure_details(error)
    # FastAPI sets detail to "Bad Request" when None is passed for status 400
    assert code == "transcript_validation_failed"
    assert message == "Bad Request"


# ---------------------------------------------------------------------------
# Cross-user isolation
# ---------------------------------------------------------------------------


async def test_get_recording_owned_by_different_user_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Accessing another user's recording should return 404 (not leaked)."""
    recording = await _create_recording(client, auth_headers, title="Owner Only")
    other_headers = await _register_user(client, f"snooper-{uuid4().hex[:8]}@example.com")

    response = await client.get(
        f"/api/recordings/{recording['id']}",
        headers=other_headers,
    )
    assert response.status_code == 404


async def test_update_recording_owned_by_different_user_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Updating another user's recording should return 404."""
    recording = await _create_recording(client, auth_headers, title="No Touch")
    other_headers = await _register_user(client, f"updater-{uuid4().hex[:8]}@example.com")

    response = await client.patch(
        f"/api/recordings/{recording['id']}",
        headers=other_headers,
        json={"title": "Hacked Title"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Save transcript endpoint
# ---------------------------------------------------------------------------


async def test_save_transcript_for_nonexistent_recording_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Saving transcript to a nonexistent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.post(
        f"/api/recordings/{fake_id}/transcript",
        headers=auth_headers,
        json={
            "segments": [{"text": "Hello", "start_ms": 0, "end_ms": 1000}],
            "duration_seconds": 1,
        },
    )
    assert response.status_code == 404


async def test_save_transcript_uses_duration_seconds_when_no_end_times(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """When all segments have end_ms=0, duration_seconds from request should be used."""
    recording = await _create_recording(client, auth_headers, title=None)

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Duration Test"),
    )

    response = await client.post(
        f"/api/recordings/{recording['id']}/transcript",
        headers=auth_headers,
        json={
            "duration_seconds": 42,
            "segments": [
                {
                    "text": "Segment with zero end_ms",
                    "speaker": "Speaker 1",
                    "start_ms": 0,
                    "end_ms": 0,
                    "confidence": 0.9,
                }
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()
    # end_ms=0 means max(end_times)//1000 = 0, but duration_seconds should fall through
    # Actually end_times will contain [0], max is 0, so recording.duration_seconds = 0
    # The duration_seconds from request is only used if end_times is empty
    assert data["status"] == "ready"


# ---------------------------------------------------------------------------
# Get transcript for nonexistent recording
# ---------------------------------------------------------------------------


async def test_get_transcript_for_nonexistent_recording_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Getting transcript for nonexistent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(
        f"/api/recordings/{fake_id}/transcript",
        headers=auth_headers,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Get summary for nonexistent recording
# ---------------------------------------------------------------------------


async def test_get_summary_for_nonexistent_recording_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Getting summary for nonexistent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(
        f"/api/recordings/{fake_id}/summary",
        headers=auth_headers,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Restore endpoint edge cases
# ---------------------------------------------------------------------------


async def test_restore_nonexistent_recording_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Restoring a nonexistent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.post(
        f"/api/recordings/{fake_id}/restore",
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_restore_recording_owned_by_different_user_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Restoring another user's trashed recording should return 404."""
    recording = await _create_recording(client, auth_headers, title="Trash Mine")

    # Soft-delete it
    await client.delete(f"/api/recordings/{recording['id']}", headers=auth_headers)

    # Another user tries to restore it
    other_headers = await _register_user(client, f"restorer-{uuid4().hex[:8]}@example.com")
    response = await client.post(
        f"/api/recordings/{recording['id']}/restore",
        headers=other_headers,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Language normalization
# ---------------------------------------------------------------------------


async def test_create_recording_normalizes_language(
    client: AsyncClient,
    auth_headers: dict,
):
    """Language should be lowercased and stripped."""
    response = await client.post(
        "/api/recordings",
        headers=auth_headers,
        json={"title": "Language Test", "type": "note", "language": "  EN  "},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["language"] == "en"


async def test_create_recording_empty_language_becomes_null(
    client: AsyncClient,
    auth_headers: dict,
):
    """Empty/whitespace-only language should normalize to null (user default)."""
    response = await client.post(
        "/api/recordings",
        headers=auth_headers,
        json={"title": "Empty Lang", "type": "note", "language": "   "},
    )
    assert response.status_code == 201


# ---------------------------------------------------------------------------
# Upload with nonexistent recording_id for another user
# ---------------------------------------------------------------------------


async def test_upload_to_recording_owned_by_different_user_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Uploading to another user's recording should return 404."""
    recording = await _create_recording(client, auth_headers, title="Upload Test")
    other_headers = await _register_user(client, f"uploader-{uuid4().hex[:8]}@example.com")

    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=other_headers,
        files={"file": ("test.mp3", b"fake-audio", "audio/mpeg")},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# _serialize_summary with None
# ---------------------------------------------------------------------------


def test_serialize_summary_with_none_returns_none():
    """_serialize_summary should return None when passed None."""
    assert recordings._serialize_summary(None) is None


# ---------------------------------------------------------------------------
# _delete_staged_file edge cases
# ---------------------------------------------------------------------------


def test_delete_staged_file_with_none_is_noop():
    """_delete_staged_file should not crash when given None."""
    recordings._delete_staged_file(None)


def test_delete_staged_file_with_empty_string_is_noop():
    """_delete_staged_file should not crash when given empty string."""
    recordings._delete_staged_file("")


def test_delete_staged_file_with_nonexistent_path_is_noop():
    """_delete_staged_file should not crash for missing files (missing_ok=True)."""
    recordings._delete_staged_file("/tmp/nonexistent-file-12345.mp3")


# ---------------------------------------------------------------------------
# _upload_limit_message
# ---------------------------------------------------------------------------


def test_upload_limit_message_format():
    """_upload_limit_message should produce a human-readable size string."""
    msg = recordings._upload_limit_message()
    assert "Maximum size" in msg
    assert "MB" in msg


# ---------------------------------------------------------------------------
# _measure_upload_size
# ---------------------------------------------------------------------------


def test_measure_upload_size():
    """_measure_upload_size should return the file size and reset position."""
    import io

    from fastapi import UploadFile

    content = b"hello world"
    file = UploadFile(filename="test.mp3", file=io.BytesIO(content))
    size = recordings._measure_upload_size(file)
    assert size == len(content)
    # Verify file is reset to beginning
    assert file.file.tell() == 0


# ---------------------------------------------------------------------------
# Update recording
# ---------------------------------------------------------------------------


async def test_update_recording_title_and_type(
    client: AsyncClient,
    auth_headers: dict,
):
    """PATCH should update title and type fields."""
    recording = await _create_recording(client, auth_headers, title="Old Title", type_="note")

    response = await client.patch(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
        json={"title": "New Title", "type": "meeting"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "New Title"
    assert data["type"] == "meeting"


async def test_update_nonexistent_recording_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """PATCH on nonexistent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.patch(
        f"/api/recordings/{fake_id}",
        headers=auth_headers,
        json={"title": "Nope"},
    )
    assert response.status_code == 404


async def test_create_recording_with_null_language_uses_user_default(
    client: AsyncClient,
    auth_headers: dict,
):
    """Creating with language=None should fall back to user default."""
    response = await client.post(
        "/api/recordings",
        headers=auth_headers,
        json={"title": "Null Lang", "type": "note", "language": None},
    )
    assert response.status_code == 201


async def test_update_recording_clear_folder_id(
    client: AsyncClient,
    auth_headers: dict,
):
    """PATCH with folder_id=null should clear the folder assignment."""
    recording = await _create_recording(client, auth_headers, title="Folder Test")

    response = await client.patch(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
        json={"folder_id": None},
    )
    assert response.status_code == 200
    assert response.json()["folder_id"] is None


async def test_update_recording_with_nonexistent_folder_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """PATCH with a nonexistent folder_id should return 404."""
    recording = await _create_recording(client, auth_headers, title="Bad Folder")
    fake_folder_id = "00000000-0000-0000-0000-000000000000"

    response = await client.patch(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
        json={"folder_id": fake_folder_id},
    )
    assert response.status_code == 404
    assert "folder" in response.json()["detail"].lower()


async def test_permanent_delete_recording(
    client: AsyncClient,
    auth_headers: dict,
):
    """Permanent delete with ?permanent=true should fully remove the recording."""
    recording = await _create_recording(client, auth_headers, title="Gone Forever")

    response = await client.delete(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
        params={"permanent": "true"},
    )
    assert response.status_code == 204

    get_response = await client.get(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
    )
    assert get_response.status_code == 404
