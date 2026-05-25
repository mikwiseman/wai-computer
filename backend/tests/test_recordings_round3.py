"""Round 3 coverage tests for recordings.py — targeting uncovered route handler bodies.

Covers: list_recordings body (folder_id, starred, trashed filters), weekly_digest body,
analytics body, bulk operations body, export format selection/Response, delete/restore bodies,
star/unstar bodies, update with folder, transcript search body, keywords body,
transcript-stats body, speaker-stats body, related-recordings body, save_transcript body,
get_summary edge, generate_summary highlights/edge, upload body.

These tests use db_session.flush() (not commit()) to keep data visible to the
route handlers via the shared test session, matching the pattern from
test_recordings_routes.py that achieves actual line coverage.
"""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.summarizer import SummaryResult
from app.models.highlight import Highlight
from app.models.recording import ActionItem, Recording, Segment, Summary
from tests.conftest import LEGAL_ACCEPTANCE

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


async def _register_user(client: AsyncClient, email: str) -> dict:
    """Register a new user and return auth headers."""
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "testpassword123", **LEGAL_ACCEPTANCE},
    )
    data = response.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


# ---------------------------------------------------------------------------
# 1. PATCH update recording title
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_recording_title_round3(client: AsyncClient, auth_headers: dict):
    """PATCH title should update and be reflected in detail response."""
    rec = await _create_recording(client, auth_headers, title="Before Update")
    response = await client.patch(
        f"/api/recordings/{rec['id']}",
        headers=auth_headers,
        json={"title": "After Update"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "After Update"
    assert data["id"] == rec["id"]
    assert data["type"] == "note"


# ---------------------------------------------------------------------------
# 2. PATCH update recording type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_recording_type_to_reflection(
    client: AsyncClient, auth_headers: dict
):
    """PATCH should allow changing type to reflection."""
    rec = await _create_recording(client, auth_headers, type_="note")
    response = await client.patch(
        f"/api/recordings/{rec['id']}",
        headers=auth_headers,
        json={"type": "reflection"},
    )
    assert response.status_code == 200
    assert response.json()["type"] == "reflection"


# ---------------------------------------------------------------------------
# 3. Soft-delete (trash) and list trashed recordings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_soft_delete_and_list_trashed(client: AsyncClient, auth_headers: dict):
    """Soft-deleted recording should appear in trashed list but not active list."""
    rec = await _create_recording(client, auth_headers, title="Trash Me Round3")
    await client.delete(f"/api/recordings/{rec['id']}", headers=auth_headers)

    # Active list should be empty
    active = await client.get("/api/recordings", headers=auth_headers)
    assert active.status_code == 200
    assert len(active.json()) == 0

    # Trashed list should contain the recording
    trashed = await client.get(
        "/api/recordings", headers=auth_headers, params={"trashed": "true"}
    )
    assert trashed.status_code == 200
    trashed_items = trashed.json()
    assert len(trashed_items) == 1
    assert trashed_items[0]["id"] == rec["id"]
    assert trashed_items[0]["deleted_at"] is not None


# ---------------------------------------------------------------------------
# 4. Restore recording from trash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_recording_clears_deleted_at(
    client: AsyncClient, auth_headers: dict
):
    """Restoring should clear deleted_at and make recording appear in active list."""
    rec = await _create_recording(client, auth_headers, title="Restore Target")
    await client.delete(f"/api/recordings/{rec['id']}", headers=auth_headers)

    restore = await client.post(
        f"/api/recordings/{rec['id']}/restore", headers=auth_headers
    )
    assert restore.status_code == 200
    assert restore.json()["deleted_at"] is None
    assert restore.json()["id"] == rec["id"]

    # Should be back in active list
    active = await client.get("/api/recordings", headers=auth_headers)
    assert any(r["id"] == rec["id"] for r in active.json())


# ---------------------------------------------------------------------------
# 5. Generate summary with highlights
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_summary_with_highlights(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Generate summary should persist highlights with resolved timestamps."""
    rec = await _create_recording(client, auth_headers, title=None)
    recording_id = UUID(rec["id"])

    db_session.add_all([
        Segment(
            recording_id=recording_id,
            speaker="Alice",
            content="We decided to approve the budget for Q3.",
            start_ms=0,
            end_ms=5000,
            confidence=0.95,
        ),
        Segment(
            recording_id=recording_id,
            speaker="Bob",
            content="I noticed a trend in the market data.",
            start_ms=5000,
            end_ms=10000,
            confidence=0.9,
        ),
    ])
    await db_session.flush()

    async def fake_summarize(_: str, **kwargs) -> SummaryResult:
        return SummaryResult(
            title="Budget and Market Review",
            summary="Team approved Q3 budget and discussed market trends.",
            key_points=["Budget approved", "Market trend noted"],
            decisions=[{"decision": "Approve Q3 budget", "context": "Team discussion"}],
            action_items=[],
            topics=["budget", "market"],
            people_mentioned=["Alice", "Bob"],
            follow_up_questions=[],
            sentiment="positive",
            highlights=[
                {
                    "category": "decision",
                    "title": "Budget approved for Q3",
                    "description": "Team agreed on budget allocation.",
                    "speaker": "Alice",
                    "importance": "high",
                    "quote": "approve the budget",
                },
                {
                    "category": "insight",
                    "title": "Market trend observed",
                    "description": None,
                    "speaker": None,
                    "importance": "medium",
                    "quote": "trend in the market",
                },
            ],
        )

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", fake_summarize)
    monkeypatch.setattr(
        "app.api.routes.recordings.resolve_highlight_timestamps",
        lambda highlights, segments: [
            {**h, "start_ms": 0, "end_ms": 5000} for h in highlights
        ],
    )

    response = await client.post(
        f"/api/recordings/{recording_id}/generate-summary",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["summary"] is not None
    assert "budget" in data["topics"]

    # Check recording detail for highlights
    detail = await client.get(
        f"/api/recordings/{recording_id}", headers=auth_headers
    )
    assert detail.status_code == 200
    detail_data = detail.json()
    assert detail_data["title"] == "Budget and Market Review"
    assert len(detail_data["highlights"]) == 2
    categories = {h["category"] for h in detail_data["highlights"]}
    assert "decision" in categories
    assert "insight" in categories


# ---------------------------------------------------------------------------
# 6. Upload audio file with mocked S3 (full upload pipeline)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_audio_with_m4a_extension(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Upload with .m4a should stage audio and enqueue processing."""
    rec = await _create_recording(client, auth_headers, title=None)

    enqueue_processing = AsyncMock()
    monkeypatch.setattr(
        "app.api.routes.recordings.enqueue_recording_audio_processing",
        enqueue_processing,
    )

    response = await client.post(
        f"/api/recordings/{rec['id']}/upload",
        headers=auth_headers,
        files={"file": ("voice-memo.m4a", b"fake-m4a-data", "audio/mp4")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processing"
    assert data["audio_url"] is None
    assert data["title"] is None
    assert data["segments"] == []
    assert data["duration_seconds"] is None
    enqueue_processing.assert_awaited_once()
    _, enqueue_kwargs = enqueue_processing.await_args
    assert enqueue_kwargs["content_type"] == "audio/mp4"


# ---------------------------------------------------------------------------
# 7. Export recording as markdown with summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_markdown_includes_summary_section(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Markdown export should include Summary section when summary exists."""
    rec = await _create_recording(client, auth_headers, title="Full Export")
    recording_id = UUID(rec["id"])

    db_session.add(Summary(
        recording_id=recording_id,
        summary="The team discussed project milestones.",
        key_points=["Milestone 1 done"],
        topics=["project"],
    ))
    db_session.add(Segment(
        recording_id=recording_id,
        speaker="Alice",
        content="We finished milestone one.",
        start_ms=0,
        end_ms=3000,
        confidence=0.9,
    ))
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/export",
        headers=auth_headers,
        params={"format": "markdown"},
    )
    assert response.status_code == 200
    body = response.text
    assert "# Full Export" in body
    assert "## Summary" in body
    assert "project milestones" in body
    assert "## Transcript" in body
    assert "milestone one" in body
    assert "text/markdown" in response.headers["content-type"]


# ---------------------------------------------------------------------------
# 8. Save transcript (live transcript from client)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_transcript_multiple_segments(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Save transcript with multiple segments should persist all and set duration."""
    rec = await _create_recording(client, auth_headers, title=None)

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Multi-Segment Call"),
    )

    response = await client.post(
        f"/api/recordings/{rec['id']}/transcript",
        headers=auth_headers,
        json={
            "duration_seconds": 10,
            "segments": [
                {
                    "text": "First segment here",
                    "speaker": "Speaker A",
                    "start_ms": 0,
                    "end_ms": 3000,
                    "confidence": 0.95,
                },
                {
                    "text": "Second segment here",
                    "speaker": "Speaker B",
                    "start_ms": 3000,
                    "end_ms": 7000,
                    "confidence": 0.9,
                },
                {
                    "text": "Third segment here",
                    "speaker": "Speaker A",
                    "start_ms": 7000,
                    "end_ms": 10000,
                    "confidence": 0.92,
                },
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["title"] == "Multi-Segment Call"
    assert len(data["segments"]) == 3
    assert data["duration_seconds"] == 10  # max(end_times) // 1000
    contents = [s["content"] for s in data["segments"]]
    assert "First segment here" in contents
    assert "Second segment here" in contents
    assert "Third segment here" in contents


# ---------------------------------------------------------------------------
# 9. Bulk move recordings to folder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_move_to_folder_round3(
    client: AsyncClient, auth_headers: dict
):
    """Bulk move should assign folder_id to all specified recordings."""
    folder = await _create_folder(client, auth_headers, "Bulk Folder R3")
    rec1 = await _create_recording(client, auth_headers, title="Move1")
    rec2 = await _create_recording(client, auth_headers, title="Move2")

    response = await client.post(
        "/api/recordings/bulk",
        headers=auth_headers,
        json={
            "recording_ids": [rec1["id"], rec2["id"]],
            "action": "move",
            "folder_id": folder["id"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["processed"] == 2
    assert data["failed"] == 0

    # Verify both recordings are in the folder
    list_resp = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"folder_id": folder["id"]},
    )
    assert list_resp.status_code == 200
    folder_ids = {r["id"] for r in list_resp.json()}
    assert rec1["id"] in folder_ids
    assert rec2["id"] in folder_ids


# ---------------------------------------------------------------------------
# 10. Bulk delete recordings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_delete_soft_deletes_round3(
    client: AsyncClient, auth_headers: dict
):
    """Bulk delete should soft-delete recordings (set deleted_at)."""
    rec1 = await _create_recording(client, auth_headers, title="BulkDel1")
    rec2 = await _create_recording(client, auth_headers, title="BulkDel2")
    rec3 = await _create_recording(client, auth_headers, title="BulkKeep")

    response = await client.post(
        "/api/recordings/bulk",
        headers=auth_headers,
        json={
            "recording_ids": [rec1["id"], rec2["id"]],
            "action": "delete",
        },
    )
    assert response.status_code == 200
    assert response.json()["processed"] == 2

    # Active list should only have rec3
    active = await client.get("/api/recordings", headers=auth_headers)
    active_ids = {r["id"] for r in active.json()}
    assert rec3["id"] in active_ids
    assert rec1["id"] not in active_ids
    assert rec2["id"] not in active_ids


# ---------------------------------------------------------------------------
# 11. Recording detail includes all expected fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recording_detail_includes_all_fields(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """GET detail should include segments, summary, action_items, and highlights."""
    rec = await _create_recording(client, auth_headers, title="Detail Test")
    recording_id = UUID(rec["id"])

    db_session.add(Segment(
        recording_id=recording_id,
        speaker="Alice",
        content="Testing detail fields.",
        start_ms=0,
        end_ms=2000,
        confidence=0.95,
    ))
    db_session.add(Summary(
        recording_id=recording_id,
        summary="A test summary.",
        key_points=["Key point"],
        topics=["testing"],
        people_mentioned=["Alice"],
        sentiment="neutral",
    ))
    db_session.add(ActionItem(
        recording_id=recording_id,
        task="Write more tests",
        owner="Alice",
        priority="high",
        source="generated",
    ))
    db_session.add(Highlight(
        recording_id=recording_id,
        category="insight",
        title="Important finding",
        importance="high",
        speaker="Alice",
        start_ms=0,
        end_ms=2000,
    ))
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()

    # Top-level fields
    assert data["id"] == str(recording_id)
    assert data["title"] == "Detail Test"
    assert data["type"] == "note"
    assert data["status"] == "pending_upload"
    assert "created_at" in data
    assert "audio_url" in data
    assert "duration_seconds" in data
    assert "language" in data
    assert "folder_id" in data
    assert "deleted_at" in data
    assert "starred_at" in data

    # Nested segments
    assert len(data["segments"]) == 1
    seg = data["segments"][0]
    assert seg["speaker"] == "Alice"
    assert seg["content"] == "Testing detail fields."
    assert "id" in seg
    assert "start_ms" in seg
    assert "end_ms" in seg
    assert "confidence" in seg

    # Summary
    assert data["summary"] is not None
    assert data["summary"]["summary"] == "A test summary."
    assert "testing" in data["summary"]["topics"]

    # Action items
    assert len(data["action_items"]) == 1
    ai = data["action_items"][0]
    assert ai["task"] == "Write more tests"
    assert ai["owner"] == "Alice"
    assert ai["priority"] == "high"
    assert ai["source"] == "generated"
    assert "id" in ai
    assert "recording_id" in ai
    assert "created_at" in ai

    # Highlights
    assert len(data["highlights"]) == 1
    hl = data["highlights"][0]
    assert hl["title"] == "Important finding"
    assert hl["category"] == "insight"
    assert hl["importance"] == "high"
    assert hl["speaker"] == "Alice"


# ---------------------------------------------------------------------------
# 12. Related recordings with no summary returns empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_related_recordings_empty_for_new_recording(
    client: AsyncClient, auth_headers: dict
):
    """Related recordings for a recording with no segments should return empty list."""
    rec = await _create_recording(client, auth_headers, title="Lonely Recording")

    response = await client.get(
        f"/api/recordings/{rec['id']}/related",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["recording_id"] == rec["id"]
    assert data["related"] == []


# ---------------------------------------------------------------------------
# 13. Transcript search with matching and non-matching queries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcript_search_no_matches(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Transcript search with non-matching query should return zero matches."""
    rec = await _create_recording(client, auth_headers, title="Search Miss")
    recording_id = UUID(rec["id"])

    db_session.add(Segment(
        recording_id=recording_id,
        speaker="Speaker 1",
        content="Discussion about project timelines.",
        start_ms=0,
        end_ms=3000,
        confidence=0.95,
    ))
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/transcript/search",
        headers=auth_headers,
        params={"q": "nonexistentword"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_matches"] == 0
    assert data["segments"] == []
    assert data["query"] == "nonexistentword"
    assert data["recording_id"] == str(recording_id)


# ---------------------------------------------------------------------------
# 14. Transcript search with case-insensitive matching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcript_search_case_insensitive(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Transcript search should be case-insensitive."""
    rec = await _create_recording(client, auth_headers, title="Case Search")
    recording_id = UUID(rec["id"])

    db_session.add(Segment(
        recording_id=recording_id,
        speaker="Speaker 1",
        content="The Budget was APPROVED by everyone.",
        start_ms=0,
        end_ms=3000,
        confidence=0.9,
    ))
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/transcript/search",
        headers=auth_headers,
        params={"q": "budget"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_matches"] == 1
    assert data["segments"][0]["match_count"] == 1


# ---------------------------------------------------------------------------
# 15. Keywords endpoint with segments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_keywords_extracts_meaningful_terms(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Keywords should extract non-stop-word terms from segments."""
    rec = await _create_recording(client, auth_headers, title="Keywords R3")
    recording_id = UUID(rec["id"])

    db_session.add_all([
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="The architecture decision was critical for performance.",
            start_ms=0,
            end_ms=3000,
            confidence=0.95,
        ),
        Segment(
            recording_id=recording_id,
            speaker="Speaker 2",
            content="Performance testing showed improvements in architecture.",
            start_ms=3000,
            end_ms=6000,
            confidence=0.9,
        ),
    ])
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/keywords",
        headers=auth_headers,
        params={"limit": 5},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["recording_id"] == str(recording_id)
    assert data["total_words"] > 0
    terms = [kw["term"] for kw in data["keywords"]]
    # "architecture" and "performance" appear twice each
    assert "architecture" in terms
    assert "performance" in terms
    # Check counts
    for kw in data["keywords"]:
        if kw["term"] == "architecture":
            assert kw["count"] == 2
            break


# ---------------------------------------------------------------------------
# 16. Transcript stats endpoint with segments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcript_stats_with_multiple_speakers(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Transcript stats should compute correct word counts and speaker info."""
    rec = await _create_recording(client, auth_headers, title="Stats R3")
    recording_id = UUID(rec["id"])

    db_session.add_all([
        Segment(
            recording_id=recording_id,
            speaker="Alice",
            content="Hello world from Alice.",
            start_ms=0,
            end_ms=3000,
            confidence=0.95,
        ),
        Segment(
            recording_id=recording_id,
            speaker="Bob",
            content="Hello from Bob here.",
            start_ms=3000,
            end_ms=5000,
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
    assert data["word_count"] == 8  # 4 + 4
    assert data["unique_speakers"] == 2
    assert set(data["speakers"]) == {"Alice", "Bob"}
    assert data["longest_segment_ms"] == 3000
    assert data["shortest_segment_ms"] == 2000
    assert data["avg_words_per_segment"] == 4.0


# ---------------------------------------------------------------------------
# 17. Speaker stats with segments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_speaker_stats_round3(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Speaker stats should compute per-speaker duration and word counts."""
    rec = await _create_recording(client, auth_headers, title="Speaker R3")
    recording_id = UUID(rec["id"])

    db_session.add_all([
        Segment(
            recording_id=recording_id,
            speaker="Alice",
            content="Alice speaking for ten seconds here.",
            start_ms=0,
            end_ms=10000,
            confidence=0.95,
        ),
        Segment(
            recording_id=recording_id,
            speaker="Bob",
            content="Bob responds briefly.",
            start_ms=10000,
            end_ms=15000,
            confidence=0.9,
        ),
        Segment(
            recording_id=recording_id,
            speaker="Alice",
            content="Alice again.",
            start_ms=15000,
            end_ms=20000,
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
    assert data["total_duration_ms"] == 20000

    speakers_by_name = {s["name"]: s for s in data["speakers"]}
    alice = speakers_by_name["Alice"]
    assert alice["segment_count"] == 2
    assert alice["total_duration_ms"] == 15000
    assert alice["word_count"] == 8

    bob = speakers_by_name["Bob"]
    assert bob["segment_count"] == 1
    assert bob["total_duration_ms"] == 5000

    # Timeline
    assert len(data["timeline"]) == 3
    assert data["timeline"][0]["speaker"] == "Alice"
    assert data["timeline"][1]["speaker"] == "Bob"
    assert data["timeline"][2]["speaker"] == "Alice"


# ---------------------------------------------------------------------------
# 18. Weekly digest with recording data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_digest_includes_recording_data(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Weekly digest should aggregate recordings from the past 7 days."""
    rec = await _create_recording(
        client, auth_headers, title="Digest Test R3", type_="meeting"
    )
    recording_id = UUID(rec["id"])

    # Set duration on the recording
    result = await db_session.execute(
        select(Recording).where(Recording.id == recording_id)
    )
    r = result.scalar_one()
    r.duration_seconds = 600
    await db_session.flush()

    # Add summary for topic aggregation
    db_session.add(Summary(
        recording_id=recording_id,
        summary="Quarterly planning discussion.",
        topics=["planning", "quarterly"],
        people_mentioned=["Alice"],
        sentiment="positive",
    ))
    db_session.add(ActionItem(
        recording_id=recording_id,
        task="Prepare quarterly report",
        owner="Alice",
        priority="high",
        status="pending",
        source="generated",
    ))
    db_session.add(Highlight(
        recording_id=recording_id,
        category="decision",
        title="Quarterly goals approved",
        importance="high",
    ))
    await db_session.flush()

    response = await client.get(
        "/api/recordings/digest/weekly", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_recordings"] >= 1
    assert data["total_duration_seconds"] >= 600
    assert "meeting" in data["recordings_by_type"]
    assert len(data["top_topics"]) > 0
    assert any(t["topic"] == "planning" for t in data["top_topics"])
    assert len(data["pending_action_items"]) >= 1
    assert data["pending_action_items"][0]["task"] == "Prepare quarterly report"
    assert len(data["highlights"]) >= 1
    assert len(data["daily_breakdown"]) == 7
    assert "positive" in data["sentiment_breakdown"]


# ---------------------------------------------------------------------------
# 19. Analytics endpoint with recordings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analytics_aggregates_stats(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Analytics should aggregate total recordings, duration, words, and type counts."""
    rec1 = await _create_recording(
        client, auth_headers, title="Analytics A", type_="meeting"
    )
    rec2 = await _create_recording(
        client, auth_headers, title="Analytics B", type_="note"
    )

    # Set durations
    for rec_data, dur in [(rec1, 120), (rec2, 60)]:
        result = await db_session.execute(
            select(Recording).where(Recording.id == UUID(rec_data["id"]))
        )
        r = result.scalar_one()
        r.duration_seconds = dur
    await db_session.flush()

    # Add segments for word counting
    db_session.add(Segment(
        recording_id=UUID(rec1["id"]),
        speaker="Alice",
        content="Five words in this segment.",
        start_ms=0,
        end_ms=3000,
        confidence=0.9,
    ))
    await db_session.flush()

    response = await client.get(
        "/api/recordings/analytics", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_recordings"] == 2
    assert data["total_duration_seconds"] == 180
    assert data["average_duration_seconds"] == 90
    assert data["total_words"] == 5
    assert data["by_type"]["meeting"] == 1
    assert data["by_type"]["note"] == 1
    assert len(data["by_week"]) >= 1


# ---------------------------------------------------------------------------
# 20. Export as SRT with timestamps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_srt_includes_timestamps(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """SRT export should include properly formatted timestamps and sequence numbers."""
    rec = await _create_recording(client, auth_headers, title="SRT Test R3")
    recording_id = UUID(rec["id"])

    db_session.add_all([
        Segment(
            recording_id=recording_id,
            speaker="Alice",
            content="First subtitle line.",
            start_ms=0,
            end_ms=3000,
            confidence=0.95,
        ),
        Segment(
            recording_id=recording_id,
            speaker="Bob",
            content="Second subtitle line.",
            start_ms=3000,
            end_ms=6500,
            confidence=0.9,
        ),
    ])
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/export",
        headers=auth_headers,
        params={"format": "srt"},
    )
    assert response.status_code == 200
    assert "text/srt" in response.headers["content-type"]

    body = response.text
    # SRT should have sequence numbers
    assert "1\n" in body
    assert "2\n" in body
    # SRT timestamps
    assert "00:00:00,000 --> 00:00:03,000" in body
    assert "00:00:03,000 --> 00:00:06,500" in body
    # Speaker labels in SRT
    assert "[Alice]" in body
    assert "[Bob]" in body
    # Content
    assert "First subtitle line." in body
    assert "Second subtitle line." in body


# ---------------------------------------------------------------------------
# 21. Export as TXT with timestamps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_txt_format(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """TXT export should include speaker labels and timestamps."""
    rec = await _create_recording(client, auth_headers, title="TXT Test R3")
    recording_id = UUID(rec["id"])

    db_session.add(Segment(
        recording_id=recording_id,
        speaker="Speaker A",
        content="Plain text line one.",
        start_ms=5000,
        end_ms=10000,
        confidence=0.9,
    ))
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/export",
        headers=auth_headers,
        params={"format": "txt"},
    )
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "TXT Test R3" in body
    assert "[Speaker A, 0:05]" in body
    assert "Plain text line one." in body


# ---------------------------------------------------------------------------
# 22. Bulk restore after soft-delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_restore_round3(client: AsyncClient, auth_headers: dict):
    """Bulk restore should clear deleted_at on multiple recordings."""
    rec1 = await _create_recording(client, auth_headers, title="BulkRestore1")
    rec2 = await _create_recording(client, auth_headers, title="BulkRestore2")

    # Soft-delete both
    await client.delete(f"/api/recordings/{rec1['id']}", headers=auth_headers)
    await client.delete(f"/api/recordings/{rec2['id']}", headers=auth_headers)

    # Bulk restore
    response = await client.post(
        "/api/recordings/bulk",
        headers=auth_headers,
        json={
            "recording_ids": [rec1["id"], rec2["id"]],
            "action": "restore",
        },
    )
    assert response.status_code == 200
    assert response.json()["processed"] == 2

    # Both should be in active list
    active = await client.get("/api/recordings", headers=auth_headers)
    active_ids = {r["id"] for r in active.json()}
    assert rec1["id"] in active_ids
    assert rec2["id"] in active_ids


# ---------------------------------------------------------------------------
# 23. Star and unstar recording
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_star_and_unstar_round3(client: AsyncClient, auth_headers: dict):
    """Star should set starred_at, unstar should clear it."""
    rec = await _create_recording(client, auth_headers, title="Star Me R3")

    # Star
    star_resp = await client.post(
        f"/api/recordings/{rec['id']}/star", headers=auth_headers
    )
    assert star_resp.status_code == 200
    assert star_resp.json()["starred_at"] is not None
    assert star_resp.json()["id"] == rec["id"]

    # Unstar
    unstar_resp = await client.delete(
        f"/api/recordings/{rec['id']}/star", headers=auth_headers
    )
    assert unstar_resp.status_code == 200
    assert unstar_resp.json()["starred_at"] is None


# ---------------------------------------------------------------------------
# 24. List recordings with starred filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_starred_recordings(client: AsyncClient, auth_headers: dict):
    """List with starred=true should return only starred recordings."""
    rec1 = await _create_recording(client, auth_headers, title="Starred One")
    await _create_recording(client, auth_headers, title="Not Starred")

    await client.post(f"/api/recordings/{rec1['id']}/star", headers=auth_headers)

    response = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"starred": "true"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == rec1["id"]


# ---------------------------------------------------------------------------
# 25. Update recording with folder_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_recording_move_to_folder_round3(
    client: AsyncClient, auth_headers: dict
):
    """PATCH with folder_id should move recording into folder."""
    folder = await _create_folder(client, auth_headers, "Move Folder R3")
    rec = await _create_recording(client, auth_headers, title="Move Me R3")

    response = await client.patch(
        f"/api/recordings/{rec['id']}",
        headers=auth_headers,
        json={"folder_id": folder["id"]},
    )
    assert response.status_code == 200
    assert response.json()["folder_id"] == folder["id"]

    # Clear folder
    clear_resp = await client.patch(
        f"/api/recordings/{rec['id']}",
        headers=auth_headers,
        json={"folder_id": None},
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["folder_id"] is None


# ---------------------------------------------------------------------------
# 26. Get transcript returns sorted segments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_transcript_sorted(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """GET transcript should return segments sorted by start_ms."""
    rec = await _create_recording(client, auth_headers, title="Transcript Sort R3")
    recording_id = UUID(rec["id"])

    db_session.add_all([
        Segment(
            recording_id=recording_id,
            speaker="B",
            content="Second part",
            start_ms=5000,
            end_ms=8000,
            confidence=0.9,
        ),
        Segment(
            recording_id=recording_id,
            speaker="A",
            content="First part",
            start_ms=0,
            end_ms=3000,
            confidence=0.95,
        ),
    ])
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/transcript",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["content"] == "First part"
    assert data[1]["content"] == "Second part"


# ---------------------------------------------------------------------------
# 27. Save transcript with embedding failure still succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_transcript_embedding_failure_still_saves(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Save transcript should succeed even if embedding generation fails."""
    rec = await _create_recording(client, auth_headers, title=None)

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(side_effect=RuntimeError("Embedding service down")),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Embedding Failure Test"),
    )

    response = await client.post(
        f"/api/recordings/{rec['id']}/transcript",
        headers=auth_headers,
        json={
            "segments": [
                {
                    "text": "Content despite embedding failure",
                    "speaker": "Speaker 1",
                    "start_ms": 0,
                    "end_ms": 2000,
                    "confidence": 0.9,
                }
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert len(data["segments"]) == 1
    assert data["segments"][0]["content"] == "Content despite embedding failure"


# ---------------------------------------------------------------------------
# 28. Get summary for recording with existing summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_summary_returns_existing_summary(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """GET summary should return the summary when it exists."""
    rec = await _create_recording(client, auth_headers, title="Summary Exists")
    recording_id = UUID(rec["id"])

    db_session.add(Summary(
        recording_id=recording_id,
        summary="This is the summary text.",
        key_points=["Point 1", "Point 2"],
        decisions=[{"decision": "Approved"}],
        topics=["testing"],
        people_mentioned=["Alice"],
        sentiment="positive",
    ))
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/summary",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == "This is the summary text."
    assert data["key_points"] == ["Point 1", "Point 2"]
    assert data["topics"] == ["testing"]
    assert data["people_mentioned"] == ["Alice"]
    assert data["sentiment"] == "positive"


# ---------------------------------------------------------------------------
# 29. Bulk operation with some nonexistent IDs skips them
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_with_nonexistent_ids_skips_missing(
    client: AsyncClient, auth_headers: dict
):
    """Bulk operation should skip nonexistent recording IDs and count as failed."""
    rec = await _create_recording(client, auth_headers, title="Real Recording")
    fake_id = "00000000-0000-0000-0000-000000000001"

    response = await client.post(
        "/api/recordings/bulk",
        headers=auth_headers,
        json={
            "recording_ids": [rec["id"], fake_id],
            "action": "delete",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["processed"] == 1
    assert data["failed"] == 1


# ---------------------------------------------------------------------------
# 30. List recordings filter by folder_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_recordings_filter_by_folder(
    client: AsyncClient, auth_headers: dict
):
    """List with folder_id filter should return only recordings in that folder."""
    folder = await _create_folder(client, auth_headers, "Filter Folder R3")
    rec_in = await _create_recording(client, auth_headers, title="In Folder R3")
    await _create_recording(client, auth_headers, title="No Folder R3")

    # Move rec_in into folder
    await client.patch(
        f"/api/recordings/{rec_in['id']}",
        headers=auth_headers,
        json={"folder_id": folder["id"]},
    )

    response = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"folder_id": folder["id"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == rec_in["id"]
