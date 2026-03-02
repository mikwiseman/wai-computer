"""Performance and stress tests.

All tests in this module are marked ``@pytest.mark.slow`` and are skipped
during normal test runs.  Run them explicitly with::

    pytest -m slow tests/test_performance.py
"""

import asyncio

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.slow


# ---------------------------------------------------------------------------
# 1. Pagination with many recordings
# ---------------------------------------------------------------------------


async def test_pagination_across_pages(client: AsyncClient, auth_headers: dict):
    """Create 25 recordings and verify pagination returns correct page sizes."""
    # Create 25 recordings
    for i in range(25):
        resp = await client.post(
            "/api/recordings",
            json={"title": f"Pagination recording {i}", "type": "note"},
            headers=auth_headers,
        )
        assert resp.status_code == 201

    # Page 1: first 10
    page1 = await client.get(
        "/api/recordings?limit=10&skip=0",
        headers=auth_headers,
    )
    assert page1.status_code == 200
    assert len(page1.json()) == 10

    # Page 2: next 10
    page2 = await client.get(
        "/api/recordings?limit=10&skip=10",
        headers=auth_headers,
    )
    assert page2.status_code == 200
    assert len(page2.json()) == 10

    # Page 3: remaining 5
    page3 = await client.get(
        "/api/recordings?limit=10&skip=20",
        headers=auth_headers,
    )
    assert page3.status_code == 200
    assert len(page3.json()) == 5

    # Verify no overlap between pages
    ids_p1 = {r["id"] for r in page1.json()}
    ids_p2 = {r["id"] for r in page2.json()}
    ids_p3 = {r["id"] for r in page3.json()}
    assert ids_p1.isdisjoint(ids_p2), "Page 1 and page 2 should not overlap"
    assert ids_p2.isdisjoint(ids_p3), "Page 2 and page 3 should not overlap"
    assert ids_p1.isdisjoint(ids_p3), "Page 1 and page 3 should not overlap"

    # All 25 unique recordings accounted for
    all_ids = ids_p1 | ids_p2 | ids_p3
    assert len(all_ids) == 25


# ---------------------------------------------------------------------------
# 2. Bulk creation via asyncio.gather
# ---------------------------------------------------------------------------


async def test_bulk_creation_parallel(client: AsyncClient, auth_headers: dict):
    """Create 20 recordings concurrently and verify all succeed."""

    async def _create(idx: int):
        return await client.post(
            "/api/recordings",
            json={"title": f"Bulk recording {idx}", "type": "note"},
            headers=auth_headers,
        )

    responses = await asyncio.gather(*[_create(i) for i in range(20)])

    # Every response should be 201
    for i, resp in enumerate(responses):
        assert resp.status_code == 201, (
            f"Recording {i} creation failed with {resp.status_code}: {resp.text}"
        )

    # All IDs should be unique
    ids = [resp.json()["id"] for resp in responses]
    assert len(set(ids)) == 20

    # Listing should return all 20
    list_resp = await client.get(
        "/api/recordings?limit=50",
        headers=auth_headers,
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 20


# ---------------------------------------------------------------------------
# 3. Concurrent read requests
# ---------------------------------------------------------------------------


async def test_concurrent_list_requests(client: AsyncClient, auth_headers: dict):
    """Send 10 simultaneous GET /api/recordings requests; all return 200."""
    # Seed a few recordings so the response is non-trivial
    for i in range(5):
        resp = await client.post(
            "/api/recordings",
            json={"title": f"Concurrent seed {i}", "type": "note"},
            headers=auth_headers,
        )
        assert resp.status_code == 201

    async def _list_recordings():
        return await client.get("/api/recordings", headers=auth_headers)

    responses = await asyncio.gather(*[_list_recordings() for _ in range(10)])

    for i, resp in enumerate(responses):
        assert resp.status_code == 200, (
            f"Concurrent request {i} failed with {resp.status_code}: {resp.text}"
        )
        # Each response should contain the same 5 recordings
        assert len(resp.json()) == 5
