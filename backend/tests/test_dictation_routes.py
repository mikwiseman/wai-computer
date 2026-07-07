"""Tests for dictation cleanup routes (Cerebras Chat Completions API)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import openai
import pytest
from httpx import AsyncClient

from app.api.routes import dictation as dictation_routes


def _make_response(text: str, *, model: str = "gpt-oss-120b", finish_reason: str = "stop"):
    """Build a mock Chat Completions result."""
    response = MagicMock()
    response.model = model
    response.choices = [
        SimpleNamespace(
            finish_reason=finish_reason,
            message=SimpleNamespace(content=text),
        )
    ]
    return response


def _make_stream_chunk(
    *,
    delta: str | None = None,
    finish_reason: str | None = None,
    model: str = "gpt-oss-120b",
    usage: object | None = None,
):
    return SimpleNamespace(
        id="chatcmpl-test",
        model=model,
        usage=usage,
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=delta),
                finish_reason=finish_reason,
            )
        ],
    )


def _make_mock_client(
    response_text: str = "Cleaned text.",
    error: Exception | None = None,
):
    """Mock client that exposes chat.completions.create() returning a canned result."""
    mock = MagicMock()

    async def _create(**_: object):
        if error is not None:
            raise error
        return _make_response(response_text)

    mock.chat.completions.create = _create
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
            cerebras_api_key=api_key,
            cerebras_llm_model="gpt-oss-120b",
        ),
    )


def _patch_client(monkeypatch: pytest.MonkeyPatch, mock_client) -> None:
    monkeypatch.setattr(
        "app.api.routes.dictation.get_cerebras_client", lambda: mock_client
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
    _patch_client(monkeypatch, _make_mock_client(response_text="This is raw dictated text."))
    await _enable_post_filter(client, auth_headers)

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "um this is raw dictated text"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "This is raw dictated text."}


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

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
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
    assert captured["model"] == "gpt-oss-120b"
    assert captured["reasoning_effort"] == "low"
    assert captured["max_completion_tokens"] == 512
    instructions = captured["messages"][0]["content"]
    assert "Translate the dictated text into Russian (ru)." in instructions
    assert "Output only the translated text" in instructions
    assert "<preserve_exact>" in instructions
    assert "WaiComputer" in instructions
    assert "<dictation_context>" in instructions
    assert captured["messages"][1]["content"] == "<dictated_text>\nHello team.\n</dictated_text>"


@pytest.mark.asyncio
async def test_cleanup_dictation_applies_user_style_rules(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Personal style rules from settings are injected into the cleanup prompt."""
    captured: dict[str, object] = {}

    async def _create(**kwargs: object):
        captured.update(kwargs)
        # Echo the content words: the cleanup output validator rejects
        # responses that drop or replace them.
        return _make_response("Please utilize the API for this.")

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _enable_post_filter(client, auth_headers)

    rules = "Never use the word utilize.\nAlways capitalize API."
    patched = await client.patch(
        "/api/settings",
        headers=auth_headers,
        json={"dictation_style_rules": rules},
    )
    assert patched.status_code == 200

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "please utilize the api for this"},
    )

    assert response.status_code == 200
    instructions = captured["messages"][0]["content"]
    assert "<user_style_rules>" in instructions
    assert "Never use the word utilize." in instructions
    assert "style and wording only" in instructions


@pytest.mark.asyncio
async def test_transform_dictation_rewrites_selection(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Command mode: a dictated instruction transforms the selected text."""
    captured: dict[str, object] = {}

    async def _create(**kwargs: object):
        captured.update(kwargs)
        return _make_response("Ship the release notes today.")

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)

    response = await client.post(
        "/api/dictation/transform",
        headers=auth_headers,
        json={
            "instruction": "make this more concise",
            "selected_text": (
                "So basically what I want to say is that we should really try to "
                "ship the release notes at some point today."
            ),
            "vocabulary": ["WaiComputer"],
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
    assert response.json() == {"text": "Ship the release notes today."}
    assert captured["model"] == "gpt-oss-120b"
    assert captured["reasoning_effort"] == "low"
    instructions = captured["messages"][0]["content"]
    assert "Apply the dictated instruction to the selected text" in instructions
    assert "Output only the resulting text" in instructions
    assert "<preserve_exact>" in instructions
    assert "WaiComputer" in instructions
    assert "<dictation_context>" in instructions
    user_content = captured["messages"][1]["content"]
    assert "<instruction>" in user_content
    assert "make this more concise" in user_content
    assert "<selected_text>" in user_content
    assert "ship the release notes" in user_content


@pytest.mark.asyncio
async def test_transform_dictation_generates_without_selection(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Command mode with no selection generates text to insert at the cursor."""
    captured: dict[str, object] = {}

    async def _create(**kwargs: object):
        captured.update(kwargs)
        return _make_response("Dear team, the launch moves to Friday.")

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)

    response = await client.post(
        "/api/dictation/transform",
        headers=auth_headers,
        json={"instruction": "write a one-line note that the launch moves to Friday"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "Dear team, the launch moves to Friday."}
    instructions = captured["messages"][0]["content"]
    assert "no text is selected" in instructions.lower()
    user_content = captured["messages"][1]["content"]
    assert "<instruction>" in user_content
    assert "<selected_text>" not in user_content


@pytest.mark.asyncio
async def test_transform_dictation_rejects_blank_instruction(
    client: AsyncClient,
    auth_headers: dict,
):
    response = await client.post(
        "/api/dictation/transform",
        headers=auth_headers,
        json={"instruction": "   ", "selected_text": "Some text."},
    )

    assert response.status_code == 422


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
        return _make_response("Please clean up this dictated sentence.")

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)

    await _enable_post_filter(client, auth_headers)

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "please clean up this dictated sentence"},
    )

    assert response.status_code == 200
    assert captured["model"] == "gpt-oss-120b"
    assert captured["max_completion_tokens"] == 512
    assert captured["reasoning_effort"] == "low"
    assert captured["messages"][1]["content"] == (
        "<dictated_text>\nplease clean up this dictated sentence\n</dictated_text>"
    )


@pytest.mark.asyncio
async def test_cleanup_dictation_stream_emits_tokens_and_done(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    async def _create(**kwargs: object):
        captured.update(kwargs)
        usage = SimpleNamespace(
            prompt_tokens=111,
            completion_tokens=7,
            prompt_tokens_details=SimpleNamespace(cached_tokens=64),
        )
        return _AsyncStream(
            [
                _make_stream_chunk(delta="Please clean"),
                _make_stream_chunk(delta=" up this dictated sentence."),
                _make_stream_chunk(finish_reason="stop", usage=usage),
            ]
        )

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
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
    assert 'event: token\ndata: {"text": "Please clean"}' in body
    assert 'event: token\ndata: {"text": " up this dictated sentence."}' in body
    assert "event: done" in body
    assert '"text": "Please clean up this dictated sentence."' in body
    assert '"model": "gpt-oss-120b"' in body
    assert '"latency_ms":' in body
    assert '"input_tokens": 111' in body
    assert '"output_tokens": 7' in body
    assert '"cached_tokens": 64' in body
    assert captured["model"] == "gpt-oss-120b"
    assert captured["stream"] is True
    assert captured["reasoning_effort"] == "low"
    assert "email=polished paragraphs" in captured["messages"][0]["content"]


@pytest.mark.asyncio
async def test_cleanup_dictation_medium_keeps_low_reasoning_effort(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    async def _create(**kwargs: object):
        captured.update(kwargs)
        return _make_response("Please clean up this dictated sentence.")

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _set_cleanup_level(client, auth_headers, "medium")

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "please clean up this dictated sentence"},
    )

    assert response.status_code == 200
    assert captured["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_cleanup_dictation_stream_uses_chat_usage_dict(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    async def _create(**_: object):
        return _AsyncStream(
            [
                {
                    "id": "chatcmpl-test",
                    "model": "gpt-oss-120b",
                    "usage": None,
                    "choices": [
                        {
                            "delta": {"content": "Please clean up this dictated sentence."},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "chatcmpl-test",
                    "model": "gpt-oss-120b",
                    "usage": {
                        "prompt_tokens": 123,
                        "completion_tokens": 8,
                        "prompt_tokens_details": {"cached_tokens": 96},
                    },
                    "choices": [
                        {
                            "delta": {},
                            "finish_reason": "stop",
                        }
                    ],
                },
            ]
        )

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
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
        'event: token\ndata: {"text": "Please clean up this dictated sentence."}'
        in response.text
    )
    assert '"input_tokens": 123' in response.text
    assert '"output_tokens": 8' in response.text
    assert '"cached_tokens": 96' in response.text


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
async def test_cleanup_dictation_stream_maps_non_stop_finish_reason_to_sse_error(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    async def _create(**_: object):
        return _AsyncStream(
            [
                _make_stream_chunk(delta="partial"),
                _make_stream_chunk(finish_reason="content_filter"),
            ]
        )

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
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
async def test_cleanup_dictation_rejects_output_that_changes_protected_terms(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_settings(monkeypatch)
    _patch_client(
        monkeypatch,
        _make_mock_client(response_text="Ship Way Computer for MFC 123 on the website."),
    )
    await _enable_post_filter(client, auth_headers)

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={
            "text": "ship WaiComputer for MFC-123 at https://wai.computer/api",
            "vocabulary": ["WaiComputer"],
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "AI service returned an incomplete cleanup response."


@pytest.mark.asyncio
async def test_cleanup_dictation_stream_rejects_output_that_changes_protected_terms(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    async def _create(**_: object):
        return _AsyncStream(
            [
                _make_stream_chunk(delta="Ship Way Computer for MFC 123."),
                _make_stream_chunk(finish_reason="stop"),
            ]
        )

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _enable_post_filter(client, auth_headers)

    response = await client.post(
        "/api/dictation/cleanup/stream",
        headers=auth_headers,
        json={
            "text": "ship WaiComputer for MFC-123 at https://wai.computer/api",
            "vocabulary": ["WaiComputer"],
        },
    )

    assert response.status_code == 200
    assert 'event: error\ndata: {"code": "incomplete_response"' in response.text
    assert "event: done" not in response.text


@pytest.mark.asyncio
async def test_cleanup_light_rejects_output_that_rewrites_content_words(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_settings(monkeypatch)
    _patch_client(
        monkeypatch,
        _make_mock_client(response_text="Please ship this quickly today."),
    )
    await _set_cleanup_level(client, auth_headers, "light")

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "please ship this fast today"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "AI service returned an incomplete cleanup response."


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_level", ["medium", "high"])
async def test_cleanup_rejects_output_that_rewrites_content_words_for_stronger_levels(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_level: str,
):
    _patch_settings(monkeypatch)
    _patch_client(
        monkeypatch,
        _make_mock_client(response_text="Please ship this quickly today."),
    )
    await _set_cleanup_level(client, auth_headers, cleanup_level)

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "please ship this fast today"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "AI service returned an incomplete cleanup response."


@pytest.mark.asyncio
async def test_cleanup_light_allows_filler_removal_and_inflection_fix(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_settings(monkeypatch)
    _patch_client(
        monkeypatch,
        _make_mock_client(response_text="It sometimes changes words."),
    )
    await _set_cleanup_level(client, auth_headers, "light")

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "um it sometimes change words"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "It sometimes changes words."}


def test_cleanup_validator_matches_large_reordered_text_without_fuzzy_scan(
    monkeypatch: pytest.MonkeyPatch,
):
    words = [f"project{i}alpha" for i in range(120)]
    similarity_calls = 0

    def _count_similarity(left: str, right: str) -> float:
        nonlocal similarity_calls
        similarity_calls += 1
        return 0.0

    monkeypatch.setattr(
        dictation_routes,
        "_cleanup_token_similarity",
        _count_similarity,
    )

    dictation_routes._validate_cleanup_preserves_content_words(
        raw_text=" ".join(words),
        cleaned=" ".join(reversed(words)),
        protected_terms=(),
    )

    assert similarity_calls == 0


@pytest.mark.asyncio
async def test_cleanup_light_stream_rejects_output_that_rewrites_content_words(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    async def _create(**_: object):
        return _AsyncStream(
            [
                _make_stream_chunk(delta="Please ship this quickly today."),
                _make_stream_chunk(finish_reason="stop"),
            ]
        )

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _set_cleanup_level(client, auth_headers, "light")

    response = await client.post(
        "/api/dictation/cleanup/stream",
        headers=auth_headers,
        json={"text": "please ship this fast today"},
    )

    assert response.status_code == 200
    assert 'event: error\ndata: {"code": "incomplete_response"' in response.text
    assert "event: done" not in response.text


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

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _enable_post_filter(client, auth_headers)

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "э-э-э, что мы х-- мы хотим, а-а-а, дать LLM в России"},
    )

    assert response.status_code == 200
    instructions = captured["messages"][0]["content"]
    assert "э-э-э" in instructions
    assert "а-а-а" in instructions
    assert "мы х-- мы предлагаем" in instructions
    assert "Do not summarize" in instructions
    assert "Do not replace, normalize, or guess content words" in instructions
    assert "<dictated_text>" in captured["messages"][1]["content"]


@pytest.mark.asyncio
async def test_cleanup_dictation_medium_level_targets_clarity_and_conciseness(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    async def _create(**kwargs: object):
        captured.update(kwargs)
        return _make_response("Please clean up this dictated sentence.")

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _set_cleanup_level(client, auth_headers, "medium")

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "um please clean up this dictated sentence"},
    )

    assert response.status_code == 200
    instructions = captured["messages"][0]["content"]
    assert "clarity and conciseness" in instructions
    assert "Do not substitute, add, or drop content words" in instructions
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
        return _make_response("Please clean up this dictated sentence.")

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _set_cleanup_level(client, auth_headers, "high")

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "um please clean up this dictated sentence"},
    )

    assert response.status_code == 200
    instructions = captured["messages"][0]["content"]
    assert "brevity and polish" in instructions
    assert "Do not substitute, add, or drop content words" in instructions
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
        return _make_response("Remind me about bug one two three.")

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
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
    instructions = captured["messages"][0]["content"]
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
        return _make_response("Please clean up this dictated sentence.")

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
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
    instructions = captured["messages"][0]["content"]
    assert "a" * 400 in instructions
    assert "a" * 401 not in instructions
    assert "b" * 800 in instructions
    assert "b" * 801 not in instructions
    assert "c" * 400 in instructions
    assert "c" * 401 not in instructions


@pytest.mark.asyncio
async def test_cleanup_dictation_caps_large_output_token_budget(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}
    dictated_text = "word " * 20_000

    async def _create(**kwargs: object):
        captured.update(kwargs)
        return _make_response(dictated_text)

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _set_cleanup_level(client, auth_headers, "high")

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": dictated_text},
    )

    assert response.status_code == 200
    assert captured["max_completion_tokens"] == 33792


@pytest.mark.asyncio
async def test_cleanup_dictation_reserves_tokens_for_reasoning(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}
    dictated_text = "word " * 400

    async def _create(**kwargs: object):
        captured.update(kwargs)
        return _make_response(dictated_text)

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _set_cleanup_level(client, auth_headers, "medium")

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": dictated_text},
    )

    assert response.status_code == 200
    assert captured["max_completion_tokens"] == 1280


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
async def test_cleanup_dictation_retries_same_cerebras_request_after_rate_limit(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    sleeps: list[float] = []
    attempts = 0

    async def _sleep(delay: float) -> None:
        sleeps.append(delay)

    async def _create(**_: object):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise openai.RateLimitError(
                "rate limited",
                response=_fake_httpx_response(),
                body={"code": "queue_exceeded"},
            )
        return _make_response("Please clean up this long dictated sentence.")

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    monkeypatch.setattr("app.api.routes.dictation.asyncio.sleep", _sleep)
    _patch_settings(monkeypatch)
    _patch_client(monkeypatch, mock_client)
    await _enable_post_filter(client, auth_headers)

    response = await client.post(
        "/api/dictation/cleanup",
        headers=auth_headers,
        json={"text": "please clean up this long dictated sentence"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "Please clean up this long dictated sentence."}
    assert attempts == 3
    assert sleeps == [1.0, 2.0]


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
async def test_cleanup_empty_completion_text_returns_502(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Model returns an empty assistant message → 502."""
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
async def test_cleanup_blank_completion_text_returns_502(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Whitespace-only assistant message → 502."""
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

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
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
    prompt = captured["messages"][0]["content"]
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
        return _make_response("Please clean this up please.")

    mock_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
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
        assert "<preserve_exact>" not in captured["messages"][0]["content"]
