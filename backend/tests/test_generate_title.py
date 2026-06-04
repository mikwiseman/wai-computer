"""Tests for generate_title function."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.summarizer import build_summary_prompt, generate_title


def _make_response(text: str):
    response = MagicMock()
    response.model = "gpt-oss-120b"
    response.choices = [
        SimpleNamespace(
            finish_reason="stop",
            message=SimpleNamespace(content=text),
        )
    ]
    return response


@pytest.mark.asyncio
async def test_generate_title_no_api_key():
    """Should raise ValueError when CEREBRAS_API_KEY is not set."""
    with patch("app.core.summarizer.settings") as mock_settings:
        mock_settings.cerebras_api_key = ""
        with pytest.raises(ValueError, match="CEREBRAS_API_KEY not configured"):
            await generate_title("Hello world")


@pytest.mark.asyncio
async def test_generate_title_returns_whitespace_stripped_text():
    """Returns the model's title verbatim, with surrounding whitespace stripped."""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_response("  Team Standup Notes  ")
    )

    with (
        patch("app.core.summarizer.settings") as mock_settings,
        patch("app.core.summarizer.get_cerebras_client", return_value=mock_client),
    ):
        mock_settings.cerebras_api_key = "test-key"
        mock_settings.cerebras_llm_model = "gpt-oss-120b"

        title = await generate_title("We discussed the Q1 roadmap...")
        assert title == "Team Standup Notes"
        assert (
            mock_client.chat.completions.create.await_args.kwargs["max_completion_tokens"]
            == 256
        )


@pytest.mark.asyncio
async def test_generate_title_uses_first_500_chars():
    """Should use only the first 500 characters of transcript."""
    long_transcript = "x" * 1000

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_response("Short Title")
    )

    with (
        patch("app.core.summarizer.settings") as mock_settings,
        patch("app.core.summarizer.get_cerebras_client", return_value=mock_client),
    ):
        mock_settings.cerebras_api_key = "test-key"
        mock_settings.cerebras_llm_model = "gpt-oss-120b"

        await generate_title(long_transcript)

        content = mock_client.chat.completions.create.await_args.kwargs["messages"][1]["content"]
        assert long_transcript[:500] in content
        assert long_transcript[:501] not in content


@pytest.mark.asyncio
async def test_generate_title_injects_explicit_language():
    """Title generation should respect the recording/user language when known."""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_make_response("План запуска"))

    with (
        patch("app.core.summarizer.settings") as mock_settings,
        patch("app.core.summarizer.get_cerebras_client", return_value=mock_client),
    ):
        mock_settings.cerebras_api_key = "test-key"
        mock_settings.cerebras_llm_model = "gpt-oss-120b"

        title = await generate_title("Обсудили запуск продукта", language="ru")

    assert title == "План запуска"
    content = mock_client.chat.completions.create.await_args.kwargs["messages"][1]["content"]
    assert "Write the title in ru." in content


def test_summary_auto_language_prompt_mentions_title_and_russian_output():
    prompt = build_summary_prompt(language="auto")
    assert "title, summary, key_points" in prompt
    assert "If the transcript is primarily in Russian, output Russian." in prompt
