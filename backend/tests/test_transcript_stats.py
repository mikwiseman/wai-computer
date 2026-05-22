"""Tests for recording transcript stats endpoint."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recording import Segment
from tests.conftest import LEGAL_ACCEPTANCE


async def _register(client: AsyncClient, email: str) -> dict:
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", **LEGAL_ACCEPTANCE},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_recording(
    client: AsyncClient, headers: dict, title: str
) -> UUID:
    response = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": title, "type": "note", "language": "en"},
    )
    assert response.status_code == 201
    return UUID(response.json()["id"])


@pytest.mark.asyncio
async def test_transcript_stats_basic(
    client: AsyncClient, db_session: AsyncSession
):
    """Stats endpoint returns correct word and speaker counts."""
    headers = await _register(client, "stats.basic@example.com")
    recording_id = await _create_recording(client, headers, "Stats Test")

    db_session.add_all([
        Segment(
            recording_id=recording_id,
            speaker="Alice",
            content="The roadmap is ready for review.",
            start_ms=0,
            end_ms=5000,
        ),
        Segment(
            recording_id=recording_id,
            speaker="Bob",
            content="I agree with the plan.",
            start_ms=5000,
            end_ms=8000,
        ),
        Segment(
            recording_id=recording_id,
            speaker="Alice",
            content="Great, let us proceed.",
            start_ms=8000,
            end_ms=11000,
        ),
    ])
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/transcript-stats",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["recording_id"] == str(recording_id)
    assert payload["segment_count"] == 3
    assert payload["word_count"] == 15
    assert payload["unique_speakers"] == 2
    assert payload["speakers"] == ["Alice", "Bob"]
    assert payload["avg_words_per_segment"] == 5.0
    assert payload["longest_segment_ms"] == 5000
    assert payload["shortest_segment_ms"] == 3000


@pytest.mark.asyncio
async def test_transcript_stats_empty(
    client: AsyncClient, db_session: AsyncSession
):
    """Recording with no segments should return zeros."""
    headers = await _register(client, "stats.empty@example.com")
    recording_id = await _create_recording(client, headers, "Empty")

    response = await client.get(
        f"/api/recordings/{recording_id}/transcript-stats",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["segment_count"] == 0
    assert payload["word_count"] == 0
    assert payload["unique_speakers"] == 0
    assert payload["speakers"] == []
    assert payload["avg_words_per_segment"] == 0.0
    assert payload["longest_segment_ms"] is None
    assert payload["shortest_segment_ms"] is None


@pytest.mark.asyncio
async def test_transcript_stats_not_found(
    client: AsyncClient, auth_headers: dict
):
    """Non-existent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(
        f"/api/recordings/{fake_id}/transcript-stats",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_transcript_stats_other_user_denied(
    client: AsyncClient, db_session: AsyncSession
):
    """Accessing another user's recording stats should return 404."""
    owner_headers = await _register(client, "stats.owner@example.com")
    other_headers = await _register(client, "stats.other@example.com")
    recording_id = await _create_recording(
        client, owner_headers, "Owner Only"
    )

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker",
            content="secret content",
            start_ms=0,
            end_ms=2000,
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/transcript-stats",
        headers=other_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_transcript_stats_requires_auth(client: AsyncClient):
    """Unauthenticated request should return 401."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(
        f"/api/recordings/{fake_id}/transcript-stats"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_transcript_stats_null_timestamps(
    client: AsyncClient, db_session: AsyncSession
):
    """Segments with null timestamps should report null for duration stats."""
    headers = await _register(client, "stats.nullts@example.com")
    recording_id = await _create_recording(client, headers, "Null TS")

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker",
            content="Hello world",
            start_ms=None,
            end_ms=None,
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/transcript-stats",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["word_count"] == 2
    assert payload["segment_count"] == 1
    assert payload["longest_segment_ms"] is None
    assert payload["shortest_segment_ms"] is None
