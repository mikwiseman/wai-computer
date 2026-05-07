"""Tests for dictation cleanup routes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest
from httpx import AsyncClient


class _FakeMessage:
    def __init__(self, text: str):
        self.content = [SimpleNamespace(text=text)]


class _FakeEmptyMessage:
    """Message with no content blocks."""

    def __init__(self):
        self.content = []


def _make_mock_client(response_text: str = "", error: Exception | None = None) -> AsyncMock:
    mock_client = AsyncMock()

    async def _create(**_: object) -> _FakeMessage:
        if error is not None:
            raise error
        return _FakeMessage(response_text)

    mock_client.messages.create = _create
    return mock_client


def _make_empty_response_client() -> AsyncMock:
    """Mock client that returns a message with no content blocks."""
    mock_client = AsyncMock()

    async def _create(**_: object) -> _FakeEmptyMessage:
        return _FakeEmptyMessage()

    mock_client.messages.create = _create
    return mock_client


def _patch_settings(monkeypatch: pytest.MonkeyPatch, api_key: str = "test-key") -> None:
    """Patch settings with a test API key (or empty string to simulate missing key)."""
    monkeypatch.setattr(
        "app.api.routes.dictation.get_settings",
        lambda: SimpleNamespace(
            anthropic_api_key=api_key,
            anthropic_model="test-model",
            anthropic_dictation_model="test-dictation-model",
        ),
    )


def _patch_client(monkeypatch: pytest.MonkeyPatch, mock_client: AsyncMock) -> None:
    """Patch the Anthropic client factory."""
    monkeypatch.setattr(
        "app.api.routes.dictation._get_anthropic_client",
        lambda: mock_client,
    )


def _fake_httpx_response(status_code: int = 429) -> httpx.Response:
    """Build a minimal httpx.Response for anthropic error constructors."""
    return httpx.Response(status_code=status_code, request=httpx.Request("POST", "https://test"))


@pytest.mark.asyncio
async def test_cleanup_dictation_returns_cleaned_text(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, _make_mock_client(response_text="Cleaned text."))

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "um this is raw dictated text"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "Cleaned text."}


@pytest.mark.asyncio
async def test_cleanup_dictation_prompt_targets_russian_fillers_and_false_starts(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    async def _create(**kwargs: object) -> _FakeMessage:
        captured.update(kwargs)
        return _FakeMessage("Что мы хотим дать LLM в России.")

    mock_client = SimpleNamespace(messages=SimpleNamespace(create=_create))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)  # type: ignore[arg-type]

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "э-э-э, что мы х-- мы хотим, а-а-а, дать LLM в России"},
    )

    assert response.status_code == 200
    prompt = captured["messages"][0]["content"]  # type: ignore[index]
    assert "э-э-э" in prompt
    assert "а-а-а" in prompt
    assert "мы х-- мы предлагаем" in prompt
    assert "Do not summarize" in prompt


@pytest.mark.asyncio
async def test_cleanup_dictation_maps_upstream_connection_errors(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_settings(monkeypatch)
    _patch_client(
        monkeypatch,
        _make_mock_client(error=anthropic.APIConnectionError(request=None)),
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


# ---------------------------------------------------------------------------
# Missing-coverage tests — lines 39, 46, 50, 79, 87, 101, 107-120
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_missing_api_key_returns_503(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Line 39: no ANTHROPIC_API_KEY configured → 503."""
    _patch_settings(monkeypatch, api_key="")

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "some dictated text here please"},
    )

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


@pytest.mark.asyncio
async def test_cleanup_whitespace_only_text_returns_empty(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Line 46: text that becomes empty after .strip() → returns empty string without AI call."""
    _patch_settings(monkeypatch)

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "   \n\t  "},
    )

    assert response.status_code == 200
    assert response.json() == {"text": ""}


@pytest.mark.asyncio
async def test_cleanup_short_text_returned_as_is(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Line 50: text shorter than 10 chars → returned unchanged, no AI call."""
    _patch_settings(monkeypatch)

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "Hi there"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "Hi there"}


@pytest.mark.asyncio
async def test_cleanup_empty_content_blocks_returns_502(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Line 79: AI returns message with empty content list → 502."""
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, _make_empty_response_client())

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "this is a longer sentence that needs cleanup"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Empty response from AI service"


@pytest.mark.asyncio
async def test_cleanup_blank_text_in_content_block_returns_502(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Line 87: AI returns content block whose text is whitespace-only → 502."""
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, _make_mock_client(response_text="   "))

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "this is a longer sentence that needs cleanup"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Empty response from AI service"


@pytest.mark.asyncio
async def test_cleanup_rate_limit_error_returns_429(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Line 107-111: anthropic.RateLimitError → 429."""
    _patch_settings(monkeypatch)
    _patch_client(
        monkeypatch,
        _make_mock_client(
            error=anthropic.RateLimitError(
                message="rate limited",
                response=_fake_httpx_response(429),
                body=None,
            ),
        ),
    )

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "please clean up this somewhat longer sentence"},
    )

    assert response.status_code == 429
    assert "rate limit" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cleanup_api_status_error_returns_502(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Lines 112-117: anthropic.APIStatusError → 502."""
    _patch_settings(monkeypatch)
    _patch_client(
        monkeypatch,
        _make_mock_client(
            error=anthropic.APIStatusError(
                message="upstream failure",
                response=_fake_httpx_response(500),
                body=None,
            ),
        ),
    )

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "please clean up this somewhat longer sentence"},
    )

    assert response.status_code == 502
    assert "AI service error" in response.json()["detail"]


@pytest.mark.asyncio
async def test_cleanup_unexpected_exception_returns_500(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Lines 118-123: unexpected exception → 500."""
    _patch_settings(monkeypatch)
    _patch_client(
        monkeypatch,
        _make_mock_client(error=RuntimeError("totally unexpected")),
    )

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "please clean up this somewhat longer sentence"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Dictation cleanup failed"


@pytest.mark.asyncio
async def test_cleanup_dictation_embeds_vocabulary_in_preserve_block(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Vocabulary entries are wrapped in <preserve_exact> per Anthropic best practice."""
    captured: dict[str, object] = {}

    async def _create(**kwargs: object) -> _FakeMessage:
        captured.update(kwargs)
        return _FakeMessage("WaiSay is great with Anthropic.")

    mock_client = SimpleNamespace(messages=SimpleNamespace(create=_create))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)  # type: ignore[arg-type]

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={
            "text": "wai say is great with anthropic",
            "vocabulary": ["WaiSay", "Anthropic", "  WaiSay  ", "", "WAISAY"],
        },
    )

    assert response.status_code == 200
    prompt = captured["messages"][0]["content"]  # type: ignore[index]
    assert "<preserve_exact>" in prompt
    assert "</preserve_exact>" in prompt
    assert "WaiSay" in prompt
    assert "Anthropic" in prompt
    # Dedup: WaiSay should appear once inside the preserve block, not three times.
    block_start = prompt.index("<preserve_exact>")
    block_end = prompt.index("</preserve_exact>")
    block = prompt[block_start:block_end]
    assert block.count("WaiSay") == 1
    assert block.count("WAISAY") == 0  # Lowercased duplicate of WaiSay was dropped


@pytest.mark.asyncio
async def test_cleanup_dictation_omits_preserve_block_when_vocabulary_empty(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """No vocabulary → no preserve_exact tag in the prompt at all."""
    captured: dict[str, object] = {}

    async def _create(**kwargs: object) -> _FakeMessage:
        captured.update(kwargs)
        return _FakeMessage("Cleaned text.")

    mock_client = SimpleNamespace(messages=SimpleNamespace(create=_create))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)  # type: ignore[arg-type]

    # Test both an explicit empty list and the default (omitted) field.
    for payload in (
        {"text": "please clean this up please"},
        {"text": "please clean this up please", "vocabulary": []},
        {"text": "please clean this up please", "vocabulary": ["", "  "]},
    ):
        captured.clear()
        response = await client.post(
            "/api/dictation/cleanup",
            headers=auth_headers,
            json=payload,
        )
        assert response.status_code == 200
        prompt = captured["messages"][0]["content"]  # type: ignore[index]
        assert "<preserve_exact>" not in prompt
