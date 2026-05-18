"""Tests for the related recordings endpoint."""

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recording import Segment, Summary


def _vector_near(base_index: int, noise_offset: float = 0.0) -> list[float]:
    """Create a 1536-d unit vector pointing mostly at base_index with optional noise."""
    values = [0.0] * 1536
    values[base_index] = 1.0
    if noise_offset and base_index + 1 < 1536:
        values[base_index + 1] = noise_offset
    # Normalize
    magnitude = sum(v * v for v in values) ** 0.5
    return [v / magnitude for v in values]


async def _register(client: AsyncClient, email: str) -> dict:
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_recording(
    client: AsyncClient,
    headers: dict,
    title: str,
    type_: str = "note",
) -> str:
    response = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": title, "type": type_, "language": "en"},
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_related_recordings_basic(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Related recordings should return semantically similar recordings ordered by score."""
    headers = await _register(client, f"related-basic-{uuid4().hex[:8]}@example.com")

    # Create 3 recordings: rec_a and rec_b are similar, rec_c is different
    rec_a_id = await _create_recording(client, headers, "Budget Meeting Q2")
    rec_b_id = await _create_recording(client, headers, "Budget Review Q3")
    rec_c_id = await _create_recording(client, headers, "Vacation Planning")

    # rec_a segments: pointing at dimension 0
    db_session.add(Segment(
        recording_id=UUID(rec_a_id),
        content="We discussed the Q2 budget allocation",
        start_ms=0, end_ms=1000, embedding=_vector_near(0),
    ))
    db_session.add(Segment(
        recording_id=UUID(rec_a_id),
        content="Revenue targets were reviewed",
        start_ms=1000, end_ms=2000, embedding=_vector_near(0, 0.1),
    ))

    # rec_b segments: similar to rec_a (also dimension 0 area)
    db_session.add(Segment(
        recording_id=UUID(rec_b_id),
        content="Budget review for next quarter",
        start_ms=0, end_ms=1000, embedding=_vector_near(0, 0.05),
    ))

    # rec_c segments: very different (dimension 100)
    db_session.add(Segment(
        recording_id=UUID(rec_c_id),
        content="Planning our summer vacation",
        start_ms=0, end_ms=1000, embedding=_vector_near(100),
    ))
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{rec_a_id}/related",
        headers=headers,
        params={"limit": 5},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["recording_id"] == rec_a_id
    assert len(data["related"]) >= 1
    # rec_b should be the most similar
    assert data["related"][0]["id"] == rec_b_id
    assert data["related"][0]["similarity_score"] > 0
    # All results should have required fields
    for related in data["related"]:
        assert "id" in related
        assert "title" in related
        assert "created_at" in related
        assert "recording_type" in related
        assert "similarity_score" in related
        assert "matching_topic" in related


@pytest.mark.asyncio
async def test_related_recordings_excludes_self(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """The source recording should NOT appear in its own related results."""
    headers = await _register(client, f"related-self-{uuid4().hex[:8]}@example.com")

    rec_a_id = await _create_recording(client, headers, "Self Test Recording")
    rec_b_id = await _create_recording(client, headers, "Another Recording")

    db_session.add(Segment(
        recording_id=UUID(rec_a_id),
        content="Content A", start_ms=0, end_ms=1000, embedding=_vector_near(0),
    ))
    db_session.add(Segment(
        recording_id=UUID(rec_b_id),
        content="Content B similar", start_ms=0, end_ms=1000, embedding=_vector_near(0, 0.1),
    ))
    await db_session.flush()

    response = await client.get(f"/api/recordings/{rec_a_id}/related", headers=headers)
    assert response.status_code == 200
    data = response.json()
    result_ids = [r["id"] for r in data["related"]]
    assert rec_a_id not in result_ids


@pytest.mark.asyncio
async def test_related_recordings_empty_no_segments(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """A recording with no segments should return an empty related list."""
    headers = await _register(client, f"related-empty-{uuid4().hex[:8]}@example.com")

    rec_id = await _create_recording(client, headers, "Empty Recording")

    response = await client.get(f"/api/recordings/{rec_id}/related", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["recording_id"] == rec_id
    assert data["related"] == []


@pytest.mark.asyncio
async def test_related_recordings_limit(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Limit parameter should constrain the number of results."""
    headers = await _register(client, f"related-limit-{uuid4().hex[:8]}@example.com")

    source_id = await _create_recording(client, headers, "Source")
    db_session.add(Segment(
        recording_id=UUID(source_id),
        content="Source content", start_ms=0, end_ms=1000, embedding=_vector_near(0),
    ))

    # Create 3 related recordings
    for i in range(3):
        rid = await _create_recording(client, headers, f"Related {i}")
        db_session.add(Segment(
            recording_id=UUID(rid),
            content=f"Related content {i}",
            start_ms=0, end_ms=1000,
            embedding=_vector_near(0, 0.01 * (i + 1)),
        ))
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{source_id}/related",
        headers=headers,
        params={"limit": 2},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["related"]) == 2


@pytest.mark.asyncio
async def test_related_recordings_nonexistent(
    client: AsyncClient,
    auth_headers: dict,
):
    """Requesting related recordings for a nonexistent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/api/recordings/{fake_id}/related", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_related_recordings_auth_required(
    client: AsyncClient,
):
    """Related recordings endpoint should require authentication."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/api/recordings/{fake_id}/related")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_related_recordings_does_not_leak_other_users(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Related results should only include recordings owned by the requesting user."""
    user_a_headers = await _register(client, f"related-usera-{uuid4().hex[:8]}@example.com")
    user_b_headers = await _register(client, f"related-userb-{uuid4().hex[:8]}@example.com")

    rec_a = await _create_recording(client, user_a_headers, "User A Recording")
    rec_b_own = await _create_recording(client, user_a_headers, "User A Other")
    rec_b_other = await _create_recording(client, user_b_headers, "User B Recording")

    # All have similar embeddings
    for rid in [rec_a, rec_b_own, rec_b_other]:
        db_session.add(Segment(
            recording_id=UUID(rid),
            content="Similar content",
            start_ms=0, end_ms=1000,
            embedding=_vector_near(0),
        ))
    await db_session.flush()

    response = await client.get(f"/api/recordings/{rec_a}/related", headers=user_a_headers)
    assert response.status_code == 200
    data = response.json()
    result_ids = [r["id"] for r in data["related"]]
    assert rec_b_own in result_ids
    assert rec_b_other not in result_ids


@pytest.mark.asyncio
async def test_related_recordings_includes_matching_topic(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """When the related recording has a summary with topics, matching_topic should be populated."""
    headers = await _register(client, f"related-topic-{uuid4().hex[:8]}@example.com")

    rec_a_id = await _create_recording(client, headers, "Source Recording")
    rec_b_id = await _create_recording(client, headers, "Target Recording")

    db_session.add(Segment(
        recording_id=UUID(rec_a_id),
        content="Discussing budgets", start_ms=0, end_ms=1000, embedding=_vector_near(0),
    ))
    db_session.add(Segment(
        recording_id=UUID(rec_b_id),
        content="Budget review", start_ms=0, end_ms=1000, embedding=_vector_near(0, 0.05),
    ))

    # Add summary with topics to the related recording
    db_session.add(Summary(
        recording_id=UUID(rec_b_id),
        summary="Budget discussion summary",
        topics=["budget discussion", "quarterly review"],
    ))
    await db_session.flush()

    response = await client.get(f"/api/recordings/{rec_a_id}/related", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["related"]) >= 1
    related_b = next(r for r in data["related"] if r["id"] == rec_b_id)
    # matching_topic should be the first topic from the summary
    assert related_b["matching_topic"] == "budget discussion"
