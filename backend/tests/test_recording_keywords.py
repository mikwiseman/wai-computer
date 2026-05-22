"""Tests for recording key terms extraction endpoint."""

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
async def test_keywords_returns_top_terms(
    client: AsyncClient, db_session: AsyncSession
):
    """Keywords endpoint should return most frequent meaningful words."""
    headers = await _register(client, "keywords.basic@example.com")
    recording_id = await _create_recording(client, headers, "Keywords Test")

    db_session.add_all(
        [
            Segment(
                recording_id=recording_id,
                speaker="Alice",
                content=(
                    "The roadmap for the product launch is critical."
                    " We need the roadmap finalized."
                ),
                start_ms=0,
                end_ms=5000,
            ),
            Segment(
                recording_id=recording_id,
                speaker="Bob",
                content=(
                    "I agree the product roadmap should include"
                    " timeline and milestones for the launch."
                ),
                start_ms=5000,
                end_ms=10000,
            ),
        ]
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/keywords",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["recording_id"] == str(recording_id)
    assert len(payload["keywords"]) > 0

    # "roadmap" appears 3 times, should be at or near the top
    terms = {k["term"]: k["count"] for k in payload["keywords"]}
    assert "roadmap" in terms
    assert terms["roadmap"] >= 3

    # Common stop words should be excluded
    for stop in ["the", "is", "for", "we", "i", "and", "to", "a"]:
        assert stop not in terms


@pytest.mark.asyncio
async def test_keywords_respects_limit(
    client: AsyncClient, db_session: AsyncSession
):
    """Limit parameter should cap the number of returned keywords."""
    headers = await _register(client, "keywords.limit@example.com")
    recording_id = await _create_recording(client, headers, "Limit Test")

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker",
            content="alpha bravo charlie delta echo foxtrot golf hotel india juliet",
            start_ms=0,
            end_ms=5000,
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/keywords",
        headers=headers,
        params={"limit": 3},
    )
    assert response.status_code == 200
    assert len(response.json()["keywords"]) == 3


@pytest.mark.asyncio
async def test_keywords_recording_not_found(
    client: AsyncClient, auth_headers: dict
):
    """Non-existent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(
        f"/api/recordings/{fake_id}/keywords",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_keywords_other_user_denied(
    client: AsyncClient, db_session: AsyncSession
):
    """Accessing another user's recording keywords should return 404."""
    owner_headers = await _register(client, "keywords.owner@example.com")
    other_headers = await _register(client, "keywords.other@example.com")
    recording_id = await _create_recording(client, owner_headers, "Owner Only")

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker",
            content="secret roadmap details",
            start_ms=0,
            end_ms=2000,
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/keywords",
        headers=other_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_keywords_empty_transcript(
    client: AsyncClient, auth_headers: dict
):
    """Recording with no segments should return empty keywords list."""
    response = await client.post(
        "/api/recordings",
        headers=auth_headers,
        json={"title": "Empty", "type": "note"},
    )
    recording_id = response.json()["id"]

    response = await client.get(
        f"/api/recordings/{recording_id}/keywords",
        headers=auth_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["keywords"] == []
    assert payload["total_words"] == 0


@pytest.mark.asyncio
async def test_keywords_requires_auth(client: AsyncClient):
    """Unauthenticated request should return 401."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/api/recordings/{fake_id}/keywords")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_keywords_sorted_by_count_descending(
    client: AsyncClient, db_session: AsyncSession
):
    """Keywords should be sorted by count in descending order."""
    headers = await _register(client, "keywords.sort@example.com")
    recording_id = await _create_recording(client, headers, "Sort Test")

    # "apple" 3 times, "banana" 2 times, "cherry" 1 time
    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker",
            content="apple banana cherry apple banana apple",
            start_ms=0,
            end_ms=3000,
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/keywords",
        headers=headers,
    )
    assert response.status_code == 200
    keywords = response.json()["keywords"]
    counts = [k["count"] for k in keywords]
    assert counts == sorted(counts, reverse=True)
    assert keywords[0]["term"] == "apple"
    assert keywords[0]["count"] == 3


@pytest.mark.asyncio
async def test_keywords_with_only_stop_words(
    client: AsyncClient, db_session: AsyncSession
):
    """Transcript with only stop words should return empty keywords."""
    headers = await _register(client, "keywords.stoponly@example.com")
    recording_id = await _create_recording(client, headers, "Stop Words")

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker",
            content="the is a an and or but for to of in on at by",
            start_ms=0,
            end_ms=3000,
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/keywords",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["keywords"] == []


@pytest.mark.asyncio
async def test_keywords_case_insensitive(
    client: AsyncClient, db_session: AsyncSession
):
    """Keywords should be case-insensitive (lowercased)."""
    headers = await _register(client, "keywords.case@example.com")
    recording_id = await _create_recording(client, headers, "Case Test")

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker",
            content="Roadmap roadmap ROADMAP",
            start_ms=0,
            end_ms=2000,
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/keywords",
        headers=headers,
    )
    assert response.status_code == 200
    terms = {k["term"]: k["count"] for k in response.json()["keywords"]}
    assert terms["roadmap"] == 3
