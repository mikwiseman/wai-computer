"""Tests for recording analytics/statistics endpoint."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recording import Recording, Segment


async def _create_recording(
    client: AsyncClient,
    headers: dict,
    title: str = "Test Recording",
    type_: str = "note",
) -> dict:
    response = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": title, "type": type_, "language": "en"},
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
async def test_analytics_empty_returns_zeros(client: AsyncClient, auth_headers: dict):
    """Analytics with no recordings should return all-zero stats."""
    response = await client.get("/api/recordings/analytics", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    assert data["total_recordings"] == 0
    assert data["total_duration_seconds"] == 0
    assert data["total_words"] == 0
    assert data["average_duration_seconds"] == 0
    assert data["by_type"] == {}
    assert data["by_week"] == []


@pytest.mark.asyncio
async def test_analytics_basic_counts(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """Analytics should count recordings and aggregate durations."""
    rec1 = await _create_recording(client, auth_headers, title="Meeting 1", type_="meeting")
    rec2 = await _create_recording(client, auth_headers, title="Note 1", type_="note")
    rec3 = await _create_recording(client, auth_headers, title="Meeting 2", type_="meeting")

    # Set durations on recordings
    for rec_id, duration in [(rec1["id"], 120), (rec2["id"], 60), (rec3["id"], 180)]:
        result = await db_session.get(Recording, UUID(rec_id))
        result.duration_seconds = duration
    await db_session.commit()

    # Add segments for word counting
    await _add_segments(
        db_session,
        rec1["id"],
        [{"content": "Hello world from meeting one", "start_ms": 0, "end_ms": 5000}],
    )
    await _add_segments(
        db_session,
        rec2["id"],
        [{"content": "Short note", "start_ms": 0, "end_ms": 2000}],
    )

    response = await client.get("/api/recordings/analytics", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    assert data["total_recordings"] == 3
    assert data["total_duration_seconds"] == 360
    assert data["average_duration_seconds"] == 120
    assert data["total_words"] == 7  # 5 + 2
    assert data["by_type"]["meeting"] == 2
    assert data["by_type"]["note"] == 1


@pytest.mark.asyncio
async def test_analytics_excludes_trashed_recordings(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """Trashed recordings should not be counted in analytics."""
    await _create_recording(client, auth_headers, title="Active")
    rec2 = await _create_recording(client, auth_headers, title="Trashed")

    # Trash one recording
    await client.delete(f"/api/recordings/{rec2['id']}", headers=auth_headers)

    response = await client.get("/api/recordings/analytics", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total_recordings"] == 1


@pytest.mark.asyncio
async def test_analytics_auth_required(client: AsyncClient):
    """Analytics endpoint requires authentication."""
    response = await client.get("/api/recordings/analytics")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_analytics_by_week_sorted_chronologically(
    client: AsyncClient, auth_headers: dict
):
    """By-week breakdown should be sorted oldest to newest."""
    await _create_recording(client, auth_headers, title="Rec 1")
    await _create_recording(client, auth_headers, title="Rec 2")

    response = await client.get("/api/recordings/analytics", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    # Both recordings created in the same week
    assert len(data["by_week"]) >= 1
    assert data["by_week"][-1]["count"] >= 2
