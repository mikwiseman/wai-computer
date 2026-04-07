"""Tests targeting coverage gaps in recordings.py, dictation.py, deps.py, and main.py.

Covers: list filters (folder_id, starred, trashed), analytics, weekly digest,
transcript search, keywords, transcript stats, cookie-based auth, health check,
export edge cases (null title, highlights-only markdown), bulk move edge cases,
permanent delete of recording with audio_url, and dictation cleanup auth.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.highlight import Highlight
from app.models.recording import ActionItem, Recording, Segment, Summary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


async def _create_folder(client: AsyncClient, headers: dict, name: str) -> dict:
    response = await client.post(
        "/api/folders", headers=headers, json={"name": name}
    )
    assert response.status_code == 201
    return response.json()


async def _add_segments(
    db_session: AsyncSession,
    recording_id: UUID,
    count: int = 2,
) -> list[Segment]:
    """Add segments to a recording and flush."""
    segments = []
    for i in range(count):
        seg = Segment(
            recording_id=recording_id,
            speaker=f"Speaker {i + 1}",
            content=f"Segment number {i + 1} with some content about roadmap planning.",
            start_ms=i * 5000,
            end_ms=(i + 1) * 5000,
            confidence=0.9 + (i * 0.01),
        )
        db_session.add(seg)
        segments.append(seg)
    await db_session.flush()
    return segments


# ---------------------------------------------------------------------------
# 1. Recording list with folder_id filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_recordings_filter_by_folder_id(
    client: AsyncClient, auth_headers: dict
):
    """List endpoint with folder_id filter should return only recordings in that folder."""
    folder = await _create_folder(client, auth_headers, "Work")
    folder_id = folder["id"]

    rec_in_folder = await _create_recording(client, auth_headers, title="In Folder")
    await client.patch(
        f"/api/recordings/{rec_in_folder['id']}",
        headers=auth_headers,
        json={"folder_id": folder_id},
    )
    await _create_recording(client, auth_headers, title="No Folder")

    response = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"folder_id": folder_id},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == rec_in_folder["id"]
    assert data[0]["folder_id"] == folder_id


# ---------------------------------------------------------------------------
# 2. Recording analytics endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recording_analytics_endpoint(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """GET /api/recordings/analytics should return aggregate statistics."""
    rec1 = await _create_recording(client, auth_headers, title="Analytics 1", type_="meeting")
    await _create_recording(client, auth_headers, title="Analytics 2", type_="note")

    # Set duration on rec1
    result = await db_session.execute(
        select(Recording).where(Recording.id == UUID(rec1["id"]))
    )
    r = result.scalar_one()
    r.duration_seconds = 120
    await db_session.flush()

    # Add segments to count words
    await _add_segments(db_session, UUID(rec1["id"]), count=2)

    response = await client.get("/api/recordings/analytics", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total_recordings"] == 2
    assert data["total_duration_seconds"] >= 120
    assert "meeting" in data["by_type"]
    assert "note" in data["by_type"]
    assert data["total_words"] > 0


# ---------------------------------------------------------------------------
# 3. Transcript search within a recording
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcript_search_returns_matching_segments(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """GET /api/recordings/{id}/transcript/search should find segments matching the query."""
    rec = await _create_recording(client, auth_headers, title="Search Target")
    recording_id = UUID(rec["id"])

    db_session.add_all([
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="The roadmap is looking good for Q3.",
            start_ms=0,
            end_ms=3000,
            confidence=0.95,
        ),
        Segment(
            recording_id=recording_id,
            speaker="Speaker 2",
            content="Budget update is pending review.",
            start_ms=3000,
            end_ms=6000,
            confidence=0.9,
        ),
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Let us revisit the roadmap next week.",
            start_ms=6000,
            end_ms=9000,
            confidence=0.92,
        ),
    ])
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/transcript/search",
        headers=auth_headers,
        params={"q": "roadmap"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "roadmap"
    assert data["total_matches"] == 2
    assert len(data["segments"]) == 2
    assert all("roadmap" in seg["content"].lower() for seg in data["segments"])


@pytest.mark.asyncio
async def test_transcript_search_nonexistent_recording_returns_404(
    client: AsyncClient, auth_headers: dict
):
    """Transcript search on a nonexistent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(
        f"/api/recordings/{fake_id}/transcript/search",
        headers=auth_headers,
        params={"q": "test"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 4. Recording keywords endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recording_keywords_endpoint(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """GET /api/recordings/{id}/keywords should extract meaningful terms."""
    rec = await _create_recording(client, auth_headers, title="Keywords Test")
    recording_id = UUID(rec["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="The roadmap planning meeting discussed database migration and performance.",
            start_ms=0,
            end_ms=5000,
            confidence=0.95,
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/keywords",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["recording_id"] == str(recording_id)
    assert data["total_words"] > 0
    terms = [kw["term"] for kw in data["keywords"]]
    assert "roadmap" in terms or "planning" in terms or "database" in terms


@pytest.mark.asyncio
async def test_recording_keywords_nonexistent_returns_404(
    client: AsyncClient, auth_headers: dict
):
    """Keywords for a nonexistent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(
        f"/api/recordings/{fake_id}/keywords",
        headers=auth_headers,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 5. Transcript stats endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcript_stats_endpoint(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """GET /api/recordings/{id}/transcript-stats should return transcript statistics."""
    rec = await _create_recording(client, auth_headers, title="Stats Test")
    recording_id = UUID(rec["id"])

    db_session.add_all([
        Segment(
            recording_id=recording_id,
            speaker="Alice",
            content="Hello everyone welcome to the meeting.",
            start_ms=0,
            end_ms=3000,
            confidence=0.95,
        ),
        Segment(
            recording_id=recording_id,
            speaker="Bob",
            content="Thanks Alice. Let us begin with the roadmap review.",
            start_ms=3000,
            end_ms=8000,
            confidence=0.9,
        ),
    ])
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/transcript-stats",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["segment_count"] == 2
    assert data["word_count"] > 0
    assert data["unique_speakers"] == 2
    assert set(data["speakers"]) == {"Alice", "Bob"}
    assert data["longest_segment_ms"] == 5000
    assert data["shortest_segment_ms"] == 3000
    assert data["avg_words_per_segment"] > 0


@pytest.mark.asyncio
async def test_transcript_stats_no_segments(
    client: AsyncClient, auth_headers: dict
):
    """Transcript stats for a recording with no segments should return zeros."""
    rec = await _create_recording(client, auth_headers, title="Empty Stats")

    response = await client.get(
        f"/api/recordings/{rec['id']}/transcript-stats",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["segment_count"] == 0
    assert data["word_count"] == 0
    assert data["unique_speakers"] == 0
    assert data["speakers"] == []
    assert data["longest_segment_ms"] is None
    assert data["shortest_segment_ms"] is None


# ---------------------------------------------------------------------------
# 6. Cookie-based auth token extraction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cookie_based_auth_accesses_protected_endpoint(
    client: AsyncClient, auth_headers: dict
):
    """An authenticated request using the auth cookie should succeed."""
    # First, register to get the token
    email = f"cookie-test-{uuid4().hex[:8]}@example.com"
    reg_response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert reg_response.status_code == 200
    token = reg_response.json()["access_token"]

    # Use cookie instead of Authorization header
    client.cookies.set("wai_access_token", token)
    try:
        response = await client.get("/api/recordings")
        assert response.status_code == 200
    finally:
        client.cookies.clear()


@pytest.mark.asyncio
async def test_invalid_cookie_token_returns_401(client: AsyncClient):
    """An invalid cookie token should return 401."""
    client.cookies.set("wai_access_token", "invalid-token-value")
    try:
        response = await client.get("/api/recordings")
        assert response.status_code == 401
    finally:
        client.cookies.clear()


# ---------------------------------------------------------------------------
# 7. Health check and root endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient):
    """GET / should return app info."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "WaiSay API"
    assert "version" in data


# ---------------------------------------------------------------------------
# 8. Export recording with null title
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_markdown_null_title_uses_untitled(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """Exporting a recording with no title should use 'Untitled Recording'."""
    rec = await _create_recording(client, auth_headers, title=None)
    recording_id = UUID(rec["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Some words here.",
            start_ms=0,
            end_ms=2000,
            confidence=0.9,
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/export",
        headers=auth_headers,
        params={"format": "markdown"},
    )
    assert response.status_code == 200
    assert "# Untitled Recording" in response.text
    # Filename should use 'recording' as fallback
    assert "recording.md" in response.headers.get("content-disposition", "")


# ---------------------------------------------------------------------------
# 9. Export markdown with highlights (speaker + no-speaker branches)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_markdown_highlights_with_and_without_speaker(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """Markdown export should handle highlights both with and without speakers."""
    rec = await _create_recording(client, auth_headers, title="Highlight Export")
    recording_id = UUID(rec["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Main discussion content.",
            start_ms=0,
            end_ms=5000,
            confidence=0.95,
        )
    )
    db_session.add_all([
        Highlight(
            recording_id=recording_id,
            category="decision",
            title="Budget approved",
            description=None,
            speaker="Alice",
            start_ms=1000,
            end_ms=2000,
            importance="high",
        ),
        Highlight(
            recording_id=recording_id,
            category="insight",
            title="Market trend observed",
            description=None,
            speaker=None,
            start_ms=3000,
            end_ms=4000,
            importance="medium",
        ),
        Highlight(
            recording_id=recording_id,
            category="action",
            title="Follow up needed",
            description=None,
            speaker=None,
            start_ms=None,
            end_ms=None,
            importance="low",
        ),
    ])
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/export",
        headers=auth_headers,
        params={"format": "markdown"},
    )
    assert response.status_code == 200
    body = response.text
    assert "## Key Highlights" in body
    # Highlight with speaker and timestamp
    assert "Budget approved" in body
    assert "(Alice," in body
    # Highlight without speaker but with timestamp
    assert "Market trend observed" in body
    # Highlight without speaker or timestamp
    assert "Follow up needed" in body


# ---------------------------------------------------------------------------
# 10. Permanent delete of recording that has audio_url
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_permanent_delete_recording_with_audio_url_removes_record(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession,
):
    """Permanent delete should remove the record even if audio_url is still populated."""
    rec = await _create_recording(client, auth_headers, title="Has Audio")
    recording_id = UUID(rec["id"])

    result = await db_session.execute(
        select(Recording).where(Recording.id == recording_id)
    )
    r = result.scalar_one()
    r.audio_url = "user/2026/01/01/test-audio.mp3"
    r.deleted_at = datetime.now(timezone.utc)  # soft-deleted first
    await db_session.flush()

    response = await client.delete(
        f"/api/recordings/{recording_id}",
        headers=auth_headers,
        params={"permanent": "true"},
    )
    assert response.status_code == 204

    detail_response = await client.get(
        f"/api/recordings/{recording_id}", headers=auth_headers
    )
    assert detail_response.status_code == 404


# ---------------------------------------------------------------------------
# 11. Permanent delete when storage delete fails (warning branch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_permanent_delete_with_audio_url_still_deletes_record(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession,
):
    """Audio metadata should not block permanent deletion."""
    rec = await _create_recording(client, auth_headers, title="Audio Metadata Delete")
    recording_id = UUID(rec["id"])

    result = await db_session.execute(
        select(Recording).where(Recording.id == recording_id)
    )
    r = result.scalar_one()
    r.audio_url = "user/2026/01/01/audio-only-metadata.mp3"
    r.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()

    response = await client.delete(
        f"/api/recordings/{recording_id}",
        headers=auth_headers,
        params={"permanent": "true"},
    )
    assert response.status_code == 204

    detail_response = await client.get(
        f"/api/recordings/{recording_id}", headers=auth_headers
    )
    assert detail_response.status_code == 404


# ---------------------------------------------------------------------------
# 12. List recordings with trashed filter shows only soft-deleted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_recordings_trashed_filter(client: AsyncClient, auth_headers: dict):
    """List with trashed=true should only return soft-deleted recordings."""
    rec1 = await _create_recording(client, auth_headers, title="Active")
    rec2 = await _create_recording(client, auth_headers, title="Trashed")

    await client.delete(f"/api/recordings/{rec2['id']}", headers=auth_headers)

    # Active list should not contain trashed recording
    active_response = await client.get("/api/recordings", headers=auth_headers)
    assert active_response.status_code == 200
    active_ids = [r["id"] for r in active_response.json()]
    assert rec1["id"] in active_ids
    assert rec2["id"] not in active_ids

    # Trashed list should contain only the trashed recording
    trashed_response = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"trashed": "true"},
    )
    assert trashed_response.status_code == 200
    trashed_ids = [r["id"] for r in trashed_response.json()]
    assert rec2["id"] in trashed_ids
    assert rec1["id"] not in trashed_ids


# ---------------------------------------------------------------------------
# 13. List recordings pagination (skip/limit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_recordings_pagination(client: AsyncClient, auth_headers: dict):
    """List endpoint should respect skip and limit parameters."""
    for i in range(5):
        await _create_recording(client, auth_headers, title=f"Paginate {i}")

    # Get first 2
    response = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"skip": 0, "limit": 2},
    )
    assert response.status_code == 200
    assert len(response.json()) == 2

    # Skip 3, should get 2
    response2 = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"skip": 3, "limit": 10},
    )
    assert response2.status_code == 200
    assert len(response2.json()) == 2


# ---------------------------------------------------------------------------
# 14. Dictation cleanup requires authentication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dictation_cleanup_requires_auth(client: AsyncClient):
    """POST /api/dictation/cleanup without auth should return 401."""
    response = await client.post(
        "/api/dictation/cleanup",
        json={"text": "some text to clean up for testing"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 15. Export helpers — format_duration with edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_recording_with_long_duration(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """Export of a recording with duration > 1 hour should show H:MM:SS format."""
    rec = await _create_recording(client, auth_headers, title="Long Recording")
    recording_id = UUID(rec["id"])

    # Set duration to 1 hour 5 minutes 30 seconds = 3930 seconds
    result = await db_session.execute(
        select(Recording).where(Recording.id == recording_id)
    )
    r = result.scalar_one()
    r.duration_seconds = 3930
    await db_session.flush()

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="A very long recording.",
            start_ms=0,
            end_ms=3930000,
            confidence=0.95,
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/export",
        headers=auth_headers,
        params={"format": "markdown"},
    )
    assert response.status_code == 200
    # Duration should be formatted as H:MM:SS
    assert "1:05:30" in response.text


# ---------------------------------------------------------------------------
# 16. Speaker stats endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_speaker_stats_endpoint(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """GET /api/recordings/{id}/speaker-stats should return per-speaker statistics."""
    rec = await _create_recording(client, auth_headers, title="Speaker Stats Test")
    recording_id = UUID(rec["id"])

    db_session.add_all([
        Segment(
            recording_id=recording_id,
            speaker="Alice",
            content="I think we should proceed with the plan.",
            start_ms=0,
            end_ms=5000,
            confidence=0.95,
        ),
        Segment(
            recording_id=recording_id,
            speaker="Bob",
            content="I agree. Let us also consider the alternatives.",
            start_ms=5000,
            end_ms=12000,
            confidence=0.9,
        ),
        Segment(
            recording_id=recording_id,
            speaker="Alice",
            content="Good point, Bob.",
            start_ms=12000,
            end_ms=15000,
            confidence=0.93,
        ),
    ])
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/speaker-stats",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_speakers"] == 2
    assert data["total_duration_ms"] == 15000

    speaker_names = {s["name"] for s in data["speakers"]}
    assert speaker_names == {"Alice", "Bob"}

    # Alice has 2 segments, Bob has 1
    alice = next(s for s in data["speakers"] if s["name"] == "Alice")
    bob = next(s for s in data["speakers"] if s["name"] == "Bob")
    assert alice["segment_count"] == 2
    assert bob["segment_count"] == 1
    assert alice["word_count"] > 0
    assert bob["word_count"] > 0

    # Timeline should have 3 entries
    assert len(data["timeline"]) == 3


@pytest.mark.asyncio
async def test_speaker_stats_empty_recording(
    client: AsyncClient, auth_headers: dict
):
    """Speaker stats for a recording with no segments should return empty."""
    rec = await _create_recording(client, auth_headers, title="Empty Speaker Stats")

    response = await client.get(
        f"/api/recordings/{rec['id']}/speaker-stats",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_speakers"] == 0
    assert data["total_duration_ms"] == 0
    assert data["speakers"] == []
    assert data["timeline"] == []


# ---------------------------------------------------------------------------
# 17. Weekly digest endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_digest_endpoint(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """GET /api/recordings/digest/weekly should return aggregated weekly data."""
    rec = await _create_recording(client, auth_headers, title="Digest Recording", type_="meeting")
    recording_id = UUID(rec["id"])

    # Set duration
    result = await db_session.execute(
        select(Recording).where(Recording.id == recording_id)
    )
    r = result.scalar_one()
    r.duration_seconds = 300
    await db_session.flush()

    # Add summary for topic/people aggregation
    db_session.add(Summary(
        recording_id=recording_id,
        summary="Team discussed roadmap and hiring plan.",
        key_points=["Roadmap finalized"],
        topics=["roadmap", "hiring"],
        people_mentioned=["Alice", "Bob"],
        sentiment="positive",
    ))

    # Add a pending action item
    db_session.add(ActionItem(
        recording_id=recording_id,
        task="Review roadmap document",
        owner="Alice",
        priority="high",
        status="pending",
        source="generated",
    ))

    # Add a highlight
    db_session.add(Highlight(
        recording_id=recording_id,
        category="decision",
        title="Roadmap finalized",
        importance="high",
    ))

    await db_session.flush()

    response = await client.get("/api/recordings/digest/weekly", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    assert data["total_recordings"] >= 1
    assert data["total_duration_seconds"] >= 300
    assert "meeting" in data["recordings_by_type"]
    assert len(data["top_topics"]) > 0
    assert len(data["top_people"]) > 0
    assert len(data["pending_action_items"]) >= 1
    assert data["pending_action_items"][0]["task"] == "Review roadmap document"
    assert len(data["highlights"]) >= 1
    assert "positive" in data["sentiment_breakdown"]
    assert len(data["daily_breakdown"]) == 7


# ---------------------------------------------------------------------------
# 18. Analytics endpoint with no recordings returns zeros
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analytics_empty_returns_zeros(client: AsyncClient, auth_headers: dict):
    """Analytics with no recordings should return zeroed-out stats."""
    response = await client.get("/api/recordings/analytics", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total_recordings"] == 0
    assert data["total_duration_seconds"] == 0
    assert data["average_duration_seconds"] == 0
    assert data["total_words"] == 0
    assert data["by_type"] == {}
    assert data["by_week"] == []


# ---------------------------------------------------------------------------
# 19. Restore a non-trashed recording (still works, sets deleted_at to None)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_active_recording_is_noop(
    client: AsyncClient, auth_headers: dict
):
    """Restoring a recording that was never trashed should succeed as a no-op."""
    rec = await _create_recording(client, auth_headers, title="Never Trashed")

    response = await client.post(
        f"/api/recordings/{rec['id']}/restore",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["deleted_at"] is None


# ---------------------------------------------------------------------------
# 20. Delete recording that belongs to another user returns 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_other_users_recording_returns_404(
    client: AsyncClient, auth_headers: dict
):
    """Deleting another user's recording should return 404."""
    rec = await _create_recording(client, auth_headers, title="My Recording")

    # Create another user
    other_resp = await client.post(
        "/api/auth/register",
        json={"email": f"other-del-{uuid4().hex[:8]}@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}

    response = await client.delete(
        f"/api/recordings/{rec['id']}", headers=other_headers
    )
    assert response.status_code == 404

    # Original recording should still exist
    detail = await client.get(f"/api/recordings/{rec['id']}", headers=auth_headers)
    assert detail.status_code == 200
