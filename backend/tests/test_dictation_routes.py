"""Tests for dictation cleanup routes."""

import sys
from types import SimpleNamespace

import pytest
from httpx import AsyncClient


class _FakeMessage:
    def __init__(self, text: str):
        self.content = [SimpleNamespace(text=text)]


class _FakeAnthropicClient:
    def __init__(self, response_text: str = "", error: Exception | None = None):
        self._response_text = response_text
        self._error = error
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **_: object) -> _FakeMessage:
        if self._error is not None:
            raise self._error
        return _FakeMessage(self._response_text)


class _FakeAnthropicConnectionError(Exception):
    pass


class _FakeAnthropicRateLimitError(Exception):
    pass


class _FakeAnthropicAPIStatusError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


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
    fake_module = SimpleNamespace(
        AsyncAnthropic=lambda api_key: _FakeAnthropicClient(response_text="Cleaned text."),
        APIConnectionError=_FakeAnthropicConnectionError,
        RateLimitError=_FakeAnthropicRateLimitError,
        APIStatusError=_FakeAnthropicAPIStatusError,
    )
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

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
    fake_module = SimpleNamespace(
        AsyncAnthropic=lambda api_key: _FakeAnthropicClient(error=_FakeAnthropicConnectionError()),
        APIConnectionError=_FakeAnthropicConnectionError,
        RateLimitError=_FakeAnthropicRateLimitError,
        APIStatusError=_FakeAnthropicAPIStatusError,
    )
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

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
