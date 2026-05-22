"""Tests for transcript search within a recording (TDD RED phase).

Endpoint: GET /api/recordings/{recording_id}/transcript/search?q=keyword&limit=20
"""

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


async def _create_recording(client: AsyncClient, headers: dict, title: str) -> UUID:
    response = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": title, "type": "note", "language": "en"},
    )
    assert response.status_code == 201
    return UUID(response.json()["id"])


@pytest.mark.asyncio
async def test_transcript_search_returns_matching_segments(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Search should return only segments containing the query with correct match_count."""
    headers = await _register(client, "tsearch.match@example.com")
    recording_id = await _create_recording(client, headers, "Transcript Search Test")

    db_session.add_all(
        [
            Segment(
                recording_id=recording_id,
                speaker="Speaker 1",
                content="We discussed the roadmap for Q2 and the roadmap for Q3",
                start_ms=0,
                end_ms=5000,
                confidence=0.95,
            ),
            Segment(
                recording_id=recording_id,
                speaker="Speaker 2",
                content="Budget review was completed successfully",
                start_ms=5000,
                end_ms=10000,
                confidence=0.90,
            ),
            Segment(
                recording_id=recording_id,
                speaker="Speaker 1",
                content="The roadmap needs final approval",
                start_ms=10000,
                end_ms=15000,
                confidence=0.92,
            ),
        ]
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/transcript/search",
        headers=headers,
        params={"q": "roadmap"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["recording_id"] == str(recording_id)
    assert payload["query"] == "roadmap"
    assert payload["total_matches"] == 2
    assert len(payload["segments"]) == 2

    # First segment has "roadmap" twice
    assert payload["segments"][0]["match_count"] == 2
    assert payload["segments"][0]["start_ms"] == 0

    # Third segment has "roadmap" once
    assert payload["segments"][1]["match_count"] == 1
    assert payload["segments"][1]["start_ms"] == 10000


@pytest.mark.asyncio
async def test_transcript_search_case_insensitive(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Search should be case-insensitive."""
    headers = await _register(client, "tsearch.case@example.com")
    recording_id = await _create_recording(client, headers, "Case Test")

    db_session.add_all(
        [
            Segment(
                recording_id=recording_id,
                speaker="Speaker 1",
                content="The ROADMAP was discussed in detail",
                start_ms=0,
                end_ms=3000,
                confidence=0.95,
            ),
            Segment(
                recording_id=recording_id,
                speaker="Speaker 2",
                content="We updated the Roadmap timeline",
                start_ms=3000,
                end_ms=6000,
                confidence=0.90,
            ),
        ]
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/transcript/search",
        headers=headers,
        params={"q": "roadmap"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_matches"] == 2
    assert len(payload["segments"]) == 2


@pytest.mark.asyncio
async def test_transcript_search_empty_query_rejected(
    client: AsyncClient,
    auth_headers: dict,
):
    """Empty query string should return 422."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(
        f"/api/recordings/{fake_id}/transcript/search",
        headers=auth_headers,
        params={"q": ""},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_transcript_search_recording_not_found(
    client: AsyncClient,
    auth_headers: dict,
):
    """Non-existent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(
        f"/api/recordings/{fake_id}/transcript/search",
        headers=auth_headers,
        params={"q": "anything"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_transcript_search_other_user_recording_denied(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Searching in another user's recording should return 404."""
    owner_headers = await _register(client, "tsearch.owner@example.com")
    other_headers = await _register(client, "tsearch.other@example.com")

    recording_id = await _create_recording(client, owner_headers, "Owner Only Recording")

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Secret roadmap information",
            start_ms=0,
            end_ms=2000,
            confidence=0.95,
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/transcript/search",
        headers=other_headers,
        params={"q": "roadmap"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_transcript_search_no_matches_returns_empty(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Query with no matches should return empty list and total_matches=0."""
    headers = await _register(client, "tsearch.empty@example.com")
    recording_id = await _create_recording(client, headers, "No Match Recording")

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Budget review was completed",
            start_ms=0,
            end_ms=3000,
            confidence=0.90,
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/transcript/search",
        headers=headers,
        params={"q": "nonexistent"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_matches"] == 0
    assert payload["segments"] == []


@pytest.mark.asyncio
async def test_transcript_search_requires_auth(client: AsyncClient):
    """Unauthenticated request should return 401."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(
        f"/api/recordings/{fake_id}/transcript/search",
        params={"q": "anything"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_transcript_search_respects_limit(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Limit parameter should cap the number of returned segments."""
    headers = await _register(client, "tsearch.limit@example.com")
    recording_id = await _create_recording(client, headers, "Limit Test Recording")

    # Create 5 segments all containing the keyword
    segments = [
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content=f"Roadmap discussion point {i}",
            start_ms=i * 2000,
            end_ms=(i + 1) * 2000,
            confidence=0.90,
        )
        for i in range(5)
    ]
    db_session.add_all(segments)
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/transcript/search",
        headers=headers,
        params={"q": "roadmap", "limit": 2},
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["segments"]) == 2
    # total_matches should reflect ALL matching segments, not just the limited ones
    assert payload["total_matches"] == 5
    # First two by start_ms order
    assert payload["segments"][0]["start_ms"] == 0
    assert payload["segments"][1]["start_ms"] == 2000
