"""Observability middleware tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_echoes_request_id(client: AsyncClient):
    response = await client.get("/health", headers={"X-Request-ID": "req-health-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-health-123"


@pytest.mark.asyncio
async def test_request_id_header_present_on_unauthorized_response(client: AsyncClient):
    response = await client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.headers["X-Request-ID"]
