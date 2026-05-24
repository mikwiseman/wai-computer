"""Tests for search endpoints."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recording import Segment
from tests.conftest import LEGAL_ACCEPTANCE


def _vector_list(index: int) -> list[float]:
    values = [0.0] * 1536
    values[index] = 1.0
    return values


def _vector_literal(index: int) -> str:
    values = ["0"] * 1536
    values[index] = "1"
    return "[" + ",".join(values) + "]"


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
async def test_hybrid_search_returns_ranked_results_for_current_user(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Hybrid search should rank relevant owner segments and exclude other users."""
    owner_headers = await _register(client, "search.owner@example.com")
    other_headers = await _register(client, "search.other@example.com")

    owner_recording_id = await _create_recording(client, owner_headers, "Owner Search Recording")
    other_recording_id = await _create_recording(client, other_headers, "Other Search Recording")

    db_session.add_all(
        [
            Segment(
                recording_id=owner_recording_id,
                speaker="Speaker 1",
                content="Roadmap launch plan for Q2",
                start_ms=0,
                end_ms=1000,
                confidence=0.95,
                embedding=_vector_list(0),
            ),
            Segment(
                recording_id=owner_recording_id,
                speaker="Speaker 1",
                content="Budget review discussion",
                start_ms=1000,
                end_ms=2000,
                confidence=0.9,
                embedding=_vector_list(1),
            ),
            Segment(
                recording_id=other_recording_id,
                speaker="Speaker 2",
                content="Roadmap launch plan from another user",
                start_ms=0,
                end_ms=1000,
                confidence=0.9,
                embedding=_vector_list(0),
            ),
        ]
    )
    await db_session.flush()

    async def fake_generate_embedding(_: str) -> list[float]:
        return _vector_list(0)

    monkeypatch.setattr("app.api.routes.search.generate_embedding", fake_generate_embedding)

    response = await client.get(
        "/api/search",
        headers=owner_headers,
        params={"q": "roadmap", "limit": 20},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert payload["results"][0]["content"].lower().startswith("roadmap")
    assert all(result["recording_id"] != str(other_recording_id) for result in payload["results"])


@pytest.mark.asyncio
async def test_hybrid_search_excludes_low_similarity_results_from_rows_and_total(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Hybrid search should not return semantic-only noise below its threshold."""
    headers = await _register(client, "search.hybrid.threshold@example.com")
    recording_id = await _create_recording(client, headers, "Hybrid Threshold Recording")

    db_session.add_all(
        [
            Segment(
                recording_id=recording_id,
                content="Relevant vector only",
                start_ms=0,
                end_ms=500,
                embedding=_vector_list(0),
            ),
            Segment(
                recording_id=recording_id,
                content="Irrelevant vector only",
                start_ms=500,
                end_ms=1000,
                embedding=_vector_list(2),
            ),
        ]
    )
    await db_session.flush()

    async def fake_generate_embedding(_: str) -> list[float]:
        return _vector_list(0)

    monkeypatch.setattr("app.api.routes.search.generate_embedding", fake_generate_embedding)

    response = await client.get(
        "/api/search",
        headers=headers,
        params={"q": "nonmatching-query", "limit": 20},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["results"]) == 1
    assert payload["results"][0]["content"] == "Relevant vector only"


@pytest.mark.asyncio
async def test_hybrid_search_prefers_exact_text_matches_over_semantic_noise(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Exact obvious query terms should not show semantic-only unrelated rows."""
    headers = await _register(client, "search.exact-query@example.com")
    recording_id = await _create_recording(client, headers, "Exact Query Recording")

    db_session.add_all(
        [
            Segment(
                recording_id=recording_id,
                speaker="Speaker 1",
                content="Budget forecast for launch",
                start_ms=0,
                end_ms=500,
                embedding=_vector_list(0),
            ),
            Segment(
                recording_id=recording_id,
                speaker="Speaker 2",
                content="Unrelated lunch notes",
                start_ms=500,
                end_ms=1000,
                embedding=_vector_list(0),
            ),
        ]
    )
    await db_session.flush()

    async def fake_generate_embedding(_: str) -> list[float]:
        return _vector_list(0)

    monkeypatch.setattr("app.api.routes.search.generate_embedding", fake_generate_embedding)

    response = await client.get(
        "/api/search",
        headers=headers,
        params={"q": "budget", "limit": 20},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [result["content"] for result in payload["results"]] == [
        "Budget forecast for launch"
    ]


@pytest.mark.asyncio
async def test_hybrid_search_matches_assigned_person_display_name(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Search should match user-facing speaker/person names such as Оля."""
    headers = await _register(client, "search.person-name@example.com")
    recording_id = await _create_recording(client, headers, "Speaker Name Recording")
    person_response = await client.post(
        "/api/people",
        headers=headers,
        json={"display_name": "Оля"},
    )
    assert person_response.status_code == 201
    person_id = UUID(person_response.json()["id"])

    db_session.add_all(
        [
            Segment(
                recording_id=recording_id,
                speaker="Speaker 1",
                raw_label="Speaker 1",
                person_id=person_id,
                content="Обсуждали запуск и следующий созвон.",
                start_ms=0,
                end_ms=500,
                embedding=_vector_list(1),
            ),
            Segment(
                recording_id=recording_id,
                speaker="Speaker 2",
                raw_label="Speaker 2",
                content="Другой участник говорил о бюджете.",
                start_ms=500,
                end_ms=1000,
                embedding=_vector_list(0),
            ),
        ]
    )
    await db_session.flush()

    async def fake_generate_embedding(_: str) -> list[float]:
        return _vector_list(0)

    monkeypatch.setattr("app.api.routes.search.generate_embedding", fake_generate_embedding)

    response = await client.get(
        "/api/search",
        headers=headers,
        params={"q": "Оля", "limit": 20},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["results"][0]["speaker"] == "Оля"
    assert payload["results"][0]["content"] == "Обсуждали запуск и следующий созвон."


@pytest.mark.asyncio
async def test_semantic_search_honors_threshold(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Semantic search should respect similarity threshold."""
    headers = await _register(client, "search.semantic@example.com")
    recording_id = await _create_recording(client, headers, "Semantic Recording")

    db_session.add_all(
        [
            Segment(
                recording_id=recording_id,
                content="Similar vector",
                start_ms=0,
                end_ms=500,
                embedding=_vector_list(0),
            ),
            Segment(
                recording_id=recording_id,
                content="Dissimilar vector",
                start_ms=500,
                end_ms=1000,
                embedding=_vector_list(2),
            ),
        ]
    )
    await db_session.flush()

    async def fake_generate_embedding(_: str) -> list[float]:
        return _vector_list(0)

    monkeypatch.setattr("app.api.routes.search.generate_embedding", fake_generate_embedding)

    response = await client.get(
        "/api/search/semantic",
        headers=headers,
        params={"q": "vector", "threshold": 0.8},
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["content"] == "Similar vector"


@pytest.mark.asyncio
async def test_semantic_search_total_counts_all_matches_with_limit(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Semantic search total should reflect all matches, not just limited rows."""
    headers = await _register(client, "search.semantic.total@example.com")
    recording_id = await _create_recording(client, headers, "Semantic Total Recording")

    db_session.add_all(
        [
            Segment(
                recording_id=recording_id,
                content="Match one",
                start_ms=0,
                end_ms=500,
                embedding=_vector_list(0),
            ),
            Segment(
                recording_id=recording_id,
                content="Match two",
                start_ms=500,
                end_ms=1000,
                embedding=_vector_list(0),
            ),
        ]
    )
    await db_session.flush()

    async def fake_generate_embedding(_: str) -> list[float]:
        return _vector_list(0)

    monkeypatch.setattr("app.api.routes.search.generate_embedding", fake_generate_embedding)

    response = await client.get(
        "/api/search/semantic",
        headers=headers,
        params={"q": "vector", "threshold": 0.1, "limit": 1},
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) == 1
    assert payload["total"] == 2


@pytest.mark.asyncio
async def test_fulltext_search_returns_matches(client: AsyncClient, db_session: AsyncSession):
    """FTS endpoint should return content matching query terms."""
    headers = await _register(client, "search.fts@example.com")
    recording_id = await _create_recording(client, headers, "FTS Recording")

    db_session.add_all(
        [
            Segment(
                recording_id=recording_id,
                content="Customer onboarding checklist",
                start_ms=0,
                end_ms=700,
            ),
            Segment(
                recording_id=recording_id,
                content="Unrelated retrospective notes",
                start_ms=700,
                end_ms=1200,
            ),
        ]
    )
    await db_session.flush()

    response = await client.get("/api/search/fts", headers=headers, params={"q": "onboarding"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert any("onboarding" in result["content"].lower() for result in payload["results"])


@pytest.mark.asyncio
async def test_search_requires_auth(client: AsyncClient):
    """All search endpoints should require auth."""
    response = await client.get("/api/search", params={"q": "anything"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_search_rejects_empty_query(client: AsyncClient, auth_headers: dict):
    """Query string should enforce min length."""
    response = await client.get("/api/search", headers=auth_headers, params={"q": ""})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_with_special_characters(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Search with special characters should not crash and should return valid results."""
    headers = await _register(client, "search.special@example.com")
    recording_id = await _create_recording(client, headers, "Special Chars Recording")

    db_session.add(
        Segment(
            recording_id=recording_id,
            content="SQL injection test: DROP TABLE; --",
            start_ms=0,
            end_ms=500,
            embedding=_vector_list(0),
        ),
    )
    await db_session.flush()

    async def fake_generate_embedding(_: str) -> list[float]:
        return _vector_list(0)

    monkeypatch.setattr("app.api.routes.search.generate_embedding", fake_generate_embedding)

    response = await client.get(
        "/api/search",
        headers=headers,
        params={"q": "DROP TABLE; --"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["results"], list)
    assert isinstance(payload["total"], int)


@pytest.mark.asyncio
async def test_fts_search_rejects_empty_query(client: AsyncClient, auth_headers: dict):
    """FTS endpoint should also reject empty query."""
    response = await client.get("/api/search/fts", headers=auth_headers, params={"q": ""})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_semantic_search_rejects_empty_query(client: AsyncClient, auth_headers: dict):
    """Semantic endpoint should also reject empty query."""
    response = await client.get("/api/search/semantic", headers=auth_headers, params={"q": ""})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_fts_search_requires_auth(client: AsyncClient):
    """FTS endpoint should require authentication."""
    response = await client.get("/api/search/fts", params={"q": "anything"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_semantic_search_requires_auth(client: AsyncClient):
    """Semantic endpoint should require authentication."""
    response = await client.get("/api/search/semantic", params={"q": "anything"})
    assert response.status_code == 401
