"""Tests for dictation cleanup routes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import pytest
from httpx import AsyncClient


class _FakeMessage:
    def __init__(self, text: str):
        self.content = [SimpleNamespace(text=text)]


def _make_mock_client(response_text: str = "", error: Exception | None = None) -> AsyncMock:
    mock_client = AsyncMock()

    async def _create(**_: object) -> _FakeMessage:
        if error is not None:
            raise error
        return _FakeMessage(response_text)

    mock_client.messages.create = _create
    return mock_client


@pytest.mark.asyncio
async def test_cleanup_dictation_returns_cleaned_text(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.api.routes.dictation.get_settings",
        lambda: SimpleNamespace(anthropic_api_key="test-key", anthropic_model="test-model"),
    )
    mock_client = _make_mock_client(response_text="Cleaned text.")
    monkeypatch.setattr(
        "app.api.routes.dictation._get_anthropic_client",
        lambda: mock_client,
    )

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "um this is raw dictated text"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "Cleaned text."}


@pytest.mark.asyncio
async def test_cleanup_dictation_maps_upstream_connection_errors(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.api.routes.dictation.get_settings",
        lambda: SimpleNamespace(anthropic_api_key="test-key", anthropic_model="test-model"),
    )
    mock_client = _make_mock_client(
        error=anthropic.APIConnectionError(request=None),
    )
    monkeypatch.setattr(
        "app.api.routes.dictation._get_anthropic_client",
        lambda: mock_client,
    )

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "please clean up this long dictated sentence"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Unable to connect to AI service"


@pytest.mark.asyncio
async def test_cleanup_dictation_rejects_oversized_payload(
    client: AsyncClient,
    auth_headers: dict,
):
    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "x" * 8001},
    )

    assert response.status_code == 422
