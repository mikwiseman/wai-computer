"""Tests for speaker statistics endpoint."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recording import Segment


async def _create_recording(
    client: AsyncClient,
    headers: dict,
    title: str = "Test Recording",
) -> dict:
    response = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": title, "type": "meeting", "language": "en"},
    )
    assert response.status_code == 201
    return response.json()


async def _add_segments(
    db_session: AsyncSession,
    recording_id: str,
    segments: list[dict],
) -> None:
    for seg in segments:
        db_session.add(
            Segment(
                recording_id=UUID(recording_id),
                speaker=seg.get("speaker"),
                content=seg["content"],
                start_ms=seg.get("start_ms", 0),
                end_ms=seg.get("end_ms", 0),
                confidence=seg.get("confidence"),
            )
        )
    await db_session.commit()


@pytest.mark.asyncio
async def test_speaker_stats_basic(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """Recording with 3 speakers should compute correct per-speaker stats."""
    recording = await _create_recording(client, auth_headers, title="Team Meeting")

    await _add_segments(
        db_session,
        recording["id"],
        [
            # Speaker 1: 2 segments, 20s total, 8 words
            {
                "speaker": "Alice",
                "content": "Hello everyone welcome to meeting",
                "start_ms": 0,
                "end_ms": 10000,
            },
            {
                "speaker": "Alice",
                "content": "Let us begin",
                "start_ms": 30000,
                "end_ms": 40000,
            },
            # Speaker 2: 1 segment, 20s, 5 words
            {
                "speaker": "Bob",
                "content": "Thanks Alice sounds good today",
                "start_ms": 10000,
                "end_ms": 30000,
            },
            # Speaker 3: 1 segment, 10s, 3 words
            {
                "speaker": "Carol",
                "content": "I agree completely",
                "start_ms": 40000,
                "end_ms": 50000,
            },
        ],
    )

    response = await client.get(
        f"/api/recordings/{recording['id']}/speaker-stats",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["recording_id"] == recording["id"]
    assert data["total_duration_ms"] == 50000
    assert data["total_speakers"] == 3

    speakers_by_name = {s["name"]: s for s in data["speakers"]}

    alice = speakers_by_name["Alice"]
    assert alice["total_duration_ms"] == 20000
    assert alice["percentage"] == pytest.approx(40.0)
    assert alice["segment_count"] == 2
    assert alice["avg_segment_duration_ms"] == 10000
    assert alice["word_count"] == 8
    assert alice["first_spoke_ms"] == 0
    assert alice["last_spoke_ms"] == 40000

    bob = speakers_by_name["Bob"]
    assert bob["total_duration_ms"] == 20000
    assert bob["percentage"] == pytest.approx(40.0)
    assert bob["segment_count"] == 1
    assert bob["word_count"] == 5

    carol = speakers_by_name["Carol"]
    assert carol["total_duration_ms"] == 10000
    assert carol["percentage"] == pytest.approx(20.0)
    assert carol["segment_count"] == 1
    assert carol["word_count"] == 3

    # Speakers sorted by total_duration_ms descending, then name ascending
    names = [s["name"] for s in data["speakers"]]
    assert names == ["Alice", "Bob", "Carol"]

    # Timeline should be chronological
    assert len(data["timeline"]) == 4
    assert data["timeline"][0]["speaker"] == "Alice"
    assert data["timeline"][0]["start_ms"] == 0
    assert data["timeline"][0]["end_ms"] == 10000


@pytest.mark.asyncio
async def test_speaker_stats_single_speaker(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """Single speaker should have 100% speaking time."""
    recording = await _create_recording(client, auth_headers, title="Solo Note")

    await _add_segments(
        db_session,
        recording["id"],
        [
            {"speaker": "Me", "content": "Just me talking here", "start_ms": 0, "end_ms": 30000},
            {"speaker": "Me", "content": "Still talking", "start_ms": 30000, "end_ms": 60000},
        ],
    )

    response = await client.get(
        f"/api/recordings/{recording['id']}/speaker-stats",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["total_speakers"] == 1
    assert data["total_duration_ms"] == 60000
    assert len(data["speakers"]) == 1

    speaker = data["speakers"][0]
    assert speaker["name"] == "Me"
    assert speaker["total_duration_ms"] == 60000
    assert speaker["percentage"] == pytest.approx(100.0)
    assert speaker["segment_count"] == 2
    assert speaker["avg_segment_duration_ms"] == 30000
    assert speaker["word_count"] == 6


@pytest.mark.asyncio
async def test_speaker_stats_no_segments(
    client: AsyncClient, auth_headers: dict
):
    """Recording with no segments should return empty stats."""
    recording = await _create_recording(client, auth_headers, title="Empty Recording")

    response = await client.get(
        f"/api/recordings/{recording['id']}/speaker-stats",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["recording_id"] == recording["id"]
    assert data["total_duration_ms"] == 0
    assert data["total_speakers"] == 0
    assert data["speakers"] == []
    assert data["timeline"] == []


@pytest.mark.asyncio
async def test_speaker_stats_no_speakers(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """Segments without speaker field should be grouped as 'Unknown'."""
    recording = await _create_recording(client, auth_headers, title="No Speaker Tags")

    await _add_segments(
        db_session,
        recording["id"],
        [
            {"speaker": None, "content": "Some speech here", "start_ms": 0, "end_ms": 10000},
            {"speaker": None, "content": "More speech", "start_ms": 10000, "end_ms": 20000},
        ],
    )

    response = await client.get(
        f"/api/recordings/{recording['id']}/speaker-stats",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["total_speakers"] == 1
    assert data["speakers"][0]["name"] == "Unknown"
    assert data["speakers"][0]["total_duration_ms"] == 20000
    assert data["speakers"][0]["percentage"] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_speaker_stats_nonexistent_recording(
    client: AsyncClient, auth_headers: dict
):
    """Nonexistent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(
        f"/api/recordings/{fake_id}/speaker-stats",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_speaker_stats_auth_required(client: AsyncClient):
    """Request without auth token should return 401."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/api/recordings/{fake_id}/speaker-stats")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_speaker_stats_timeline_chronological(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """Timeline entries should be in chronological order by start_ms."""
    recording = await _create_recording(client, auth_headers, title="Timeline Check")

    await _add_segments(
        db_session,
        recording["id"],
        [
            {"speaker": "B", "content": "Second part", "start_ms": 5000, "end_ms": 10000},
            {"speaker": "A", "content": "First part", "start_ms": 0, "end_ms": 5000},
            {"speaker": "A", "content": "Third part", "start_ms": 10000, "end_ms": 15000},
        ],
    )

    response = await client.get(
        f"/api/recordings/{recording['id']}/speaker-stats",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()

    timeline = data["timeline"]
    assert len(timeline) == 3
    # Verify chronological order
    for i in range(len(timeline) - 1):
        assert timeline[i]["start_ms"] <= timeline[i + 1]["start_ms"]

    assert timeline[0]["speaker"] == "A"
    assert timeline[0]["start_ms"] == 0
    assert timeline[1]["speaker"] == "B"
    assert timeline[1]["start_ms"] == 5000
    assert timeline[2]["speaker"] == "A"
    assert timeline[2]["start_ms"] == 10000


@pytest.mark.asyncio
async def test_speaker_stats_null_timestamps(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """Segments with null timestamps should be handled gracefully."""
    recording = await _create_recording(client, auth_headers, title="Null Timestamps")

    await _add_segments(
        db_session,
        recording["id"],
        [
            {"speaker": "Alice", "content": "Some words here", "start_ms": 0, "end_ms": 10000},
            {"speaker": "Bob", "content": "No timestamps", "start_ms": None, "end_ms": None},
        ],
    )

    response = await client.get(
        f"/api/recordings/{recording['id']}/speaker-stats",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()

    # Should still include both speakers; Bob has 0 duration from null timestamps
    assert data["total_speakers"] == 2
    speakers_by_name = {s["name"]: s for s in data["speakers"]}
    assert speakers_by_name["Alice"]["total_duration_ms"] == 10000
    assert speakers_by_name["Bob"]["total_duration_ms"] == 0
    assert speakers_by_name["Bob"]["word_count"] == 2


@pytest.mark.asyncio
async def test_speaker_stats_words_per_minute(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """Words per minute should be computed correctly."""
    recording = await _create_recording(client, auth_headers, title="WPM Test")

    # 120 words in 60 seconds = 120 WPM
    words = " ".join(["word"] * 120)
    await _add_segments(
        db_session,
        recording["id"],
        [
            {"speaker": "Fast", "content": words, "start_ms": 0, "end_ms": 60000},
        ],
    )

    response = await client.get(
        f"/api/recordings/{recording['id']}/speaker-stats",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()

    speaker = data["speakers"][0]
    assert speaker["words_per_minute"] == pytest.approx(120.0)
