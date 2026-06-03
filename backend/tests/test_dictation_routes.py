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


class _AsyncStream:
    def __init__(self, events: list[object]):
        self._events = events

    def __aiter__(self):
        self._iter = iter(self._events)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


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


async def _enable_post_filter(client: AsyncClient, headers: dict) -> None:
    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"dictation_post_filter_enabled": True},
    )
    assert response.status_code == 200


async def _set_cleanup_level(client: AsyncClient, headers: dict, level: str) -> None:
    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"dictation_cleanup_level": level},
    )
    assert response.status_code == 200


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
    await _enable_post_filter(client, auth_headers)

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "um this is raw dictated text"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "Cleaned text."}


@pytest.mark.asyncio
async def test_translate_dictation_translates_to_selected_target_language(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    async def _create(**kwargs: object):
        captured.update(kwargs)
        return _make_response("Привет, команда.")

    mock_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)

    response = await client.post(
        "/api/dictation/translate",
        headers=auth_headers,
        json={
            "text": "Hello team.",
            "target_language_code": "ru",
            "target_language_name": "Russian",
            "vocabulary": ["WaiComputer", "OpenAI"],
            "context": {
                "app": {
                    "name": "Slack",
                    "bundle_id": "com.tinyspeck.slackmacgap",
                    "category": "chat",
                }
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {"text": "Привет, команда."}
    assert captured["model"] == "gpt-5.5"
    assert captured["reasoning"] == {"effort": "low"}
    assert captured["text"] == {"format": {"type": "text"}, "verbosity": "low"}
    assert captured["store"] is False
    assert captured["max_output_tokens"] == 1536
    instructions = captured["instructions"]
    assert "Translate the dictated text into Russian (ru)." in instructions
    assert "Output only the translated text" in instructions
    assert "<preserve_exact>" in instructions
    assert "WaiComputer" in instructions
    assert "<dictation_context>" in instructions
    assert captured["input"] == "<dictated_text>\nHello team.\n</dictated_text>"


@pytest.mark.asyncio
async def test_translate_dictation_rejects_blank_target_language(
    client: AsyncClient,
    auth_headers: dict,
):
    response = await client.post(
        "/api/dictation/translate",
        headers=auth_headers,
        json={
            "text": "Hello team.",
            "target_language_code": " ",
            "target_language_name": "Russian",
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_translate_dictation_whitespace_only_text_returns_empty(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_settings(monkeypatch)

    response = await client.post(
        "/api/dictation/translate",
        headers=auth_headers,
        json={
            "text": "   \n\t  ",
            "target_language_code": "ru",
            "target_language_name": "Russian",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"text": ""}


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
async def test_cleanup_dictation_skips_when_cleanup_level_none(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_settings(monkeypatch, api_key="")
    await _set_cleanup_level(client, auth_headers, "none")

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "um this is raw dictated text"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "um this is raw dictated text"}


@pytest.mark.asyncio
async def test_cleanup_dictation_uses_fixed_post_filter_model(
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

    await _enable_post_filter(client, auth_headers)

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "please clean up this dictated sentence"},
    )

    assert response.status_code == 200
    assert captured["model"] == "gpt-5.5"
    assert captured["max_output_tokens"] == 1536
    assert captured["reasoning"] == {"effort": "low"}
    assert captured["text"] == {"format": {"type": "text"}, "verbosity": "low"}
    assert captured["prompt_cache_key"].startswith("wai-dictation-cleanup-")
    assert captured["prompt_cache_retention"] == "24h"
    assert captured["store"] is False


@pytest.mark.asyncio
async def test_cleanup_dictation_stream_emits_tokens_and_done(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    async def _create(**kwargs: object):
        captured.update(kwargs)
        completed_response = SimpleNamespace(
            status="completed",
            error=None,
            incomplete_details=None,
            output_text="Cleaned text.",
            output=[],
            model="gpt-5.5",
            usage=SimpleNamespace(
                input_tokens=111,
                output_tokens=7,
                input_tokens_details=SimpleNamespace(cached_tokens=64),
            ),
        )
        return _AsyncStream(
            [
                SimpleNamespace(type="response.output_text.delta", delta="Cleaned"),
                SimpleNamespace(type="response.output_text.delta", delta=" text."),
                SimpleNamespace(type="response.completed", response=completed_response),
            ]
        )

    mock_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _set_cleanup_level(client, auth_headers, "light")

    response = await client.post(
        "/api/dictation/cleanup/stream",
        headers=auth_headers,
        json={
            "text": "please clean up this dictated sentence",
            "context": {"app": {"category": "email", "name": "Gmail"}},
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert 'event: token\ndata: {"text": "Cleaned"}' in body
    assert 'event: token\ndata: {"text": " text."}' in body
    assert "event: done" in body
    assert '"text": "Cleaned text."' in body
    assert '"model": "gpt-5.5"' in body
    assert '"latency_ms":' in body
    assert '"input_tokens": 111' in body
    assert '"output_tokens": 7' in body
    assert '"cached_tokens": 64' in body
    assert captured["model"] == "gpt-5.5"
    assert captured["stream"] is True
    assert captured["reasoning"] == {"effort": "low"}
    assert captured["text"] == {"format": {"type": "text"}, "verbosity": "low"}
    assert captured["prompt_cache_key"].startswith("wai-dictation-cleanup-")
    assert captured["prompt_cache_retention"] == "24h"
    assert captured["store"] is False
    assert "email: use complete, polished paragraphs" in captured["instructions"]


@pytest.mark.asyncio
async def test_cleanup_dictation_stream_extracts_text_from_done_event_dict(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    async def _create(**_: object):
        return _AsyncStream(
            [
                {
                    "type": "response.completed",
                    "response": {
                        "status": "completed",
                        "error": None,
                        "incomplete_details": None,
                        "output_text": "Cleaned from done.",
                        "output": [],
                        "model": "gpt-5.5",
                        "usage": {
                            "input_tokens": 123,
                            "output_tokens": 8,
                            "input_tokens_details": {"cached_tokens": 96},
                        },
                    },
                }
            ]
        )

    mock_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _set_cleanup_level(client, auth_headers, "light")

    response = await client.post(
        "/api/dictation/cleanup/stream",
        headers=auth_headers,
        json={"text": "please clean up this dictated sentence"},
    )

    assert response.status_code == 200
    assert 'event: token\ndata: {"text": "Cleaned from done."}' in response.text
    assert '"input_tokens": 123' in response.text
    assert '"output_tokens": 8' in response.text
    assert '"cached_tokens": 96' in response.text


@pytest.mark.asyncio
async def test_cleanup_dictation_stream_uses_output_text_done_when_completed_lacks_output_text(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    async def _create(**_: object):
        return _AsyncStream(
            [
                {
                    "type": "response.output_text.done",
                    "text": "Cleaned from output text done.",
                },
                {
                    "type": "response.completed",
                    "response": {
                        "status": "completed",
                        "error": None,
                        "incomplete_details": None,
                        "output": [
                            {
                                "type": "message",
                                "status": "completed",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "Cleaned from output text done.",
                                    }
                                ],
                            }
                        ],
                        "model": "gpt-5.5",
                    },
                },
            ]
        )

    mock_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _set_cleanup_level(client, auth_headers, "light")

    response = await client.post(
        "/api/dictation/cleanup/stream",
        headers=auth_headers,
        json={"text": "please clean up this dictated sentence"},
    )

    assert response.status_code == 200
    assert (
        'event: token\ndata: {"text": "Cleaned from output text done."}'
        in response.text
    )
    assert '"text": "Cleaned from output text done."' in response.text


@pytest.mark.asyncio
async def test_cleanup_dictation_stream_uses_content_part_done_text(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    async def _create(**_: object):
        return _AsyncStream(
            [
                {
                    "type": "response.content_part.done",
                    "part": {
                        "type": "output_text",
                        "text": "Cleaned from content part done.",
                    },
                },
                {
                    "type": "response.completed",
                    "response": {
                        "status": "completed",
                        "error": None,
                        "incomplete_details": None,
                        "output": [],
                        "model": "gpt-5.5",
                    },
                },
            ]
        )

    mock_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _set_cleanup_level(client, auth_headers, "light")

    response = await client.post(
        "/api/dictation/cleanup/stream",
        headers=auth_headers,
        json={"text": "please clean up this dictated sentence"},
    )

    assert response.status_code == 200
    assert (
        'event: token\ndata: {"text": "Cleaned from content part done."}'
        in response.text
    )
    assert '"text": "Cleaned from content part done."' in response.text


@pytest.mark.asyncio
async def test_cleanup_dictation_stream_skips_when_cleanup_level_none(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_settings(monkeypatch, api_key="")
    await _set_cleanup_level(client, auth_headers, "none")

    response = await client.post(
        "/api/dictation/cleanup/stream",
        headers=auth_headers,
        json={"text": "um this is raw dictated text"},
    )

    assert response.status_code == 200
    assert response.text == (
        'event: token\ndata: {"text": "um this is raw dictated text"}\n\n'
        'event: done\ndata: {"text": "um this is raw dictated text", '
        '"model": null, "latency_ms": 0, "input_tokens": null, '
        '"output_tokens": null, "cached_tokens": null}\n\n'
    )


@pytest.mark.asyncio
async def test_cleanup_dictation_stream_whitespace_only_text_returns_done_without_token(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_settings(monkeypatch, api_key="")

    response = await client.post(
        "/api/dictation/cleanup/stream",
        headers=auth_headers,
        json={"text": "   \n\t  "},
    )

    assert response.status_code == 200
    assert response.text == (
        'event: done\ndata: {"text": "", "model": null, "latency_ms": 0, '
        '"input_tokens": null, "output_tokens": null, "cached_tokens": null}\n\n'
    )


@pytest.mark.asyncio
async def test_cleanup_dictation_stream_maps_upstream_error_to_sse_error(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_settings(monkeypatch)
    _patch_client(
        monkeypatch,
        _make_mock_client(error=openai.APIConnectionError(request=None)),
    )
    await _enable_post_filter(client, auth_headers)

    response = await client.post(
        "/api/dictation/cleanup/stream",
        headers=auth_headers,
        json={"text": "please clean up this long dictated sentence"},
    )

    assert response.status_code == 200
    assert 'event: error\ndata: {"code": "connection_error"' in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_error", "code"),
    [
        (
            openai.RateLimitError(
                message="rate limited",
                response=_fake_httpx_response(429),
                body=None,
            ),
            "rate_limit",
        ),
        (
            openai.APIStatusError(
                message="upstream failure",
                response=_fake_httpx_response(500),
                body=None,
            ),
            "upstream_error",
        ),
        (RuntimeError("unexpected"), "cleanup_failed"),
    ],
)
async def test_cleanup_dictation_stream_maps_upstream_failures_to_sse_errors(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
    upstream_error: Exception,
    code: str,
):
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, _make_mock_client(error=upstream_error))
    await _enable_post_filter(client, auth_headers)

    response = await client.post(
        "/api/dictation/cleanup/stream",
        headers=auth_headers,
        json={"text": "please clean up this long dictated sentence"},
    )

    assert response.status_code == 200
    assert f'event: error\ndata: {{"code": "{code}"' in response.text


@pytest.mark.asyncio
async def test_cleanup_dictation_stream_maps_model_error_event_to_sse_error(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    async def _create(**_: object):
        return _AsyncStream(
            [
                {
                    "type": "response.error",
                    "error": {"message": "model stopped"},
                }
            ]
        )

    mock_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _set_cleanup_level(client, auth_headers, "light")

    response = await client.post(
        "/api/dictation/cleanup/stream",
        headers=auth_headers,
        json={"text": "please clean up this dictated sentence"},
    )

    assert response.status_code == 200
    assert 'event: error\ndata: {"code": "incomplete_response"' in response.text


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
    await _enable_post_filter(client, auth_headers)

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
async def test_cleanup_dictation_medium_level_targets_clarity_and_conciseness(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    async def _create(**kwargs: object):
        captured.update(kwargs)
        return _make_response("Clear concise text.")

    mock_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _set_cleanup_level(client, auth_headers, "medium")

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "um please clean up this dictated sentence"},
    )

    assert response.status_code == 200
    instructions = captured["instructions"]
    assert "clarity and conciseness" in instructions
    assert "Do not summarize" in instructions


@pytest.mark.asyncio
async def test_cleanup_dictation_high_level_targets_brevity_and_polish(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    async def _create(**kwargs: object):
        captured.update(kwargs)
        return _make_response("Polished text.")

    mock_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _set_cleanup_level(client, auth_headers, "high")

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "um please clean up this dictated sentence"},
    )

    assert response.status_code == 200
    instructions = captured["instructions"]
    assert "brevity and polish" in instructions
    assert "Do not summarize away details" in instructions


@pytest.mark.asyncio
async def test_cleanup_dictation_includes_context_for_formatting(
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
    await _set_cleanup_level(client, auth_headers, "light")

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={
            "text": "um remind me about bug one two three",
            "context": {
                "app": {
                    "name": "Cursor",
                    "bundle_id": "com.todesktop.230313mzl4w4u92",
                    "category": "engineering",
                },
                "textbox": {
                    "before_text": "Fix failing test in backend/app/api/routes/dictation.py\n",
                    "selected_text": "TODO",
                    "after_text": "\nThen run pytest.",
                },
            },
        },
    )

    assert response.status_code == 200
    instructions = captured["instructions"]
    assert "<dictation_context>" in instructions
    assert "<app_category>engineering</app_category>" in instructions
    assert "<app_name>Cursor</app_name>" in instructions
    assert "preserve code-like tokens" in instructions
    assert "Fix failing test" in instructions
    assert "<selected_text>TODO</selected_text>" in instructions
    assert "Then run pytest." in instructions


@pytest.mark.asyncio
async def test_cleanup_dictation_rejects_unknown_context_category(
    client: AsyncClient,
    auth_headers: dict,
):
    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={
            "text": "please clean up this dictated sentence",
            "context": {"app": {"category": "finance"}},
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_cleanup_dictation_truncates_large_textbox_context(
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
    await _set_cleanup_level(client, auth_headers, "medium")

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={
            "text": "please clean up this dictated sentence",
            "context": {
                "textbox": {
                    "before_text": "a" * 900,
                    "selected_text": "b" * 2100,
                    "after_text": "c" * 900,
                },
            },
        },
    )

    assert response.status_code == 200
    instructions = captured["instructions"]
    assert "a" * 800 in instructions
    assert "a" * 801 not in instructions
    assert "b" * 2000 in instructions
    assert "b" * 2001 not in instructions
    assert "c" * 800 in instructions
    assert "c" * 801 not in instructions


@pytest.mark.asyncio
async def test_cleanup_dictation_caps_large_output_token_budget(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    async def _create(**kwargs: object):
        captured.update(kwargs)
        return _make_response("Polished text.")

    mock_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _set_cleanup_level(client, auth_headers, "high")

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "word " * 20_000},
    )

    assert response.status_code == 200
    assert captured["max_output_tokens"] == 34560


@pytest.mark.asyncio
async def test_cleanup_dictation_reserves_tokens_for_reasoning(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    async def _create(**kwargs: object):
        captured.update(kwargs)
        return _make_response("Polished text.")

    mock_client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _set_cleanup_level(client, auth_headers, "medium")

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "word " * 400},
    )

    assert response.status_code == 200
    assert captured["max_output_tokens"] == 1792


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
    await _enable_post_filter(client, auth_headers)

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
    await _enable_post_filter(client, auth_headers)

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
    await _enable_post_filter(client, auth_headers)

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
    await _enable_post_filter(client, auth_headers)

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
    await _enable_post_filter(client, auth_headers)

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
    await _enable_post_filter(client, auth_headers)

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
    await _enable_post_filter(client, auth_headers)

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
    await _enable_post_filter(client, auth_headers)

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
    await _enable_post_filter(client, auth_headers)

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
