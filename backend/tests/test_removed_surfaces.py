from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_schemes_api_surface_is_removed(client, auth_headers) -> None:
    response = await client.get("/api/schemes", headers=auth_headers)

    assert response.status_code == 404
