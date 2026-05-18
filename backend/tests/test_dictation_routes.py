"""Tests for dictation cleanup routes (OpenAI Responses API)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import openai
import pytest
from httpx import AsyncClient


def _make_response(text: str):
    """Build a mock Responses API result."""
    response = MagicMock()
    response.output_text = text
    response.status = "completed"
    response.error = None
    response.incomplete_details = None
    response.output = []
    return response


def _make_mock_client(
    response_text: str = "Cleaned text.",
    error: Exception | None = None,
):
    """Mock client that exposes responses.create() returning a canned result."""
    mock = MagicMock()

    async def _create(**_: object):
        if error is not None:
            raise error
        return _make_response(response_text)

    mock.responses.create = _create
    return mock


def _patch_settings(monkeypatch: pytest.MonkeyPatch, api_key: str = "test-key") -> None:
    monkeypatch.setattr(
        "app.api.routes.dictation.get_settings",
        lambda: SimpleNamespace(
            openai_api_key=api_key,
            openai_llm_model="gpt-5.5",
        ),
    )


def _patch_client(monkeypatch: pytest.MonkeyPatch, mock_client) -> None:
    monkeypatch.setattr(
        "app.api.routes.dictation.get_openai_client", lambda: mock_client
    )


def _fake_httpx_response(status_code: int = 429) -> httpx.Response:
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
async def test_cleanup_dictation_skips_when_post_filter_disabled(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_settings(monkeypatch, api_key="")

    settings_response = await client.patch(
        "/api/settings",
        headers=auth_headers,
        json={"dictation_post_filter_enabled": False},
    )
    assert settings_response.status_code == 200

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "um this is raw dictated text"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "um this is raw dictated text"}


@pytest.mark.asyncio
async def test_cleanup_dictation_uses_selected_post_filter_model(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    async def _create(**kwargs: object):
        captured.update(kwargs)
        return _make_response("Cleaned text.")

    mock_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)

    settings_response = await client.patch(
        "/api/settings",
        headers=auth_headers,
        json={
            "dictation_post_filter_provider": "openai",
            "dictation_post_filter_model": "gpt-5.5",
        },
    )
    assert settings_response.status_code == 200

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "please clean up this dictated sentence"},
    )

    assert response.status_code == 200
    assert captured["model"] == "gpt-5.5"
    assert "max_output_tokens" not in captured
    assert captured["reasoning"] == {"effort": "none"}
    assert captured["text"] == {"verbosity": "low"}


@pytest.mark.asyncio
async def test_cleanup_dictation_prompt_targets_russian_fillers_and_false_starts(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    async def _create(**kwargs: object):
        captured.update(kwargs)
        return _make_response("Что мы хотим дать LLM в России.")

    mock_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "э-э-э, что мы х-- мы хотим, а-а-а, дать LLM в России"},
    )

    assert response.status_code == 200
    instructions = captured["instructions"]
    assert "э-э-э" in instructions
    assert "а-а-а" in instructions
    assert "мы х-- мы предлагаем" in instructions
    assert "Do not summarize" in instructions
    assert "<dictated_text>" in captured["input"]


@pytest.mark.asyncio
async def test_cleanup_dictation_maps_upstream_connection_errors(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_settings(monkeypatch)
    _patch_client(
        monkeypatch,
        _make_mock_client(error=openai.APIConnectionError(request=None)),
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
        json={"text": "x" * 100_001},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_cleanup_missing_api_key_returns_503(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
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
    _patch_settings(monkeypatch)

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "Hi there"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "Hi there"}


@pytest.mark.asyncio
async def test_cleanup_empty_output_text_returns_502(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Model returns an empty output_text → 502."""
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, _make_mock_client(response_text=""))

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "this is a longer sentence that needs cleanup"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "AI service returned an incomplete cleanup response."


@pytest.mark.asyncio
async def test_cleanup_blank_output_text_returns_502(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Whitespace-only output_text → 502."""
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, _make_mock_client(response_text="   "))

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "this is a longer sentence that needs cleanup"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "AI service returned an incomplete cleanup response."


@pytest.mark.asyncio
async def test_cleanup_rate_limit_error_returns_429(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_settings(monkeypatch)
    _patch_client(
        monkeypatch,
        _make_mock_client(
            error=openai.RateLimitError(
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
    _patch_settings(monkeypatch)
    _patch_client(
        monkeypatch,
        _make_mock_client(
            error=openai.APIStatusError(
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
    """Vocabulary entries are wrapped in <preserve_exact> tags."""
    captured: dict[str, object] = {}

    async def _create(**kwargs: object):
        captured.update(kwargs)
        return _make_response("WaiComputer is great with OpenAI.")

    mock_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={
            "text": "wai computer is great with openai",
            "vocabulary": ["WaiComputer", "OpenAI", "  WaiComputer  ", "", "WAICOMPUTER"],
        },
    )

    assert response.status_code == 200
    prompt = captured["instructions"]
    assert "<preserve_exact>" in prompt
    assert "</preserve_exact>" in prompt
    assert "WaiComputer" in prompt
    assert "OpenAI" in prompt
    block_start = prompt.index("<preserve_exact>")
    block_end = prompt.index("</preserve_exact>")
    block = prompt[block_start:block_end]
    assert block.count("WaiComputer") == 1
    assert block.count("WAICOMPUTER") == 0


@pytest.mark.asyncio
async def test_cleanup_dictation_omits_preserve_block_when_vocabulary_empty(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    async def _create(**kwargs: object):
        captured.update(kwargs)
        return _make_response("Cleaned text.")

    mock_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)

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
        assert "<preserve_exact>" not in captured["instructions"]
