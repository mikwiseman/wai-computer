"""Tests for generate_title function."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.summarizer import generate_title


def _make_response(text: str):
    response = MagicMock()
    response.output_text = text
    response.status = "completed"
    response.error = None
    response.incomplete_details = None
    response.output = []
    return response


@pytest.mark.asyncio
async def test_generate_title_no_api_key():
    """Should raise ValueError when OPENAI_API_KEY is not set."""
    with patch("app.core.summarizer.settings") as mock_settings:
        mock_settings.openai_api_key = ""
        with pytest.raises(ValueError, match="OPENAI_API_KEY not configured"):
            await generate_title("Hello world")


@pytest.mark.asyncio
async def test_generate_title_returns_whitespace_stripped_text():
    """Returns the model's title verbatim, with surrounding whitespace stripped."""
    mock_client = MagicMock()
    mock_client.responses.create = AsyncMock(
        return_value=_make_response("  Team Standup Notes  ")
    )

    with (
        patch("app.core.summarizer.settings") as mock_settings,
        patch("app.core.summarizer.get_openai_client", return_value=mock_client),
    ):
        mock_settings.openai_api_key = "test-key"
        mock_settings.openai_llm_model = "gpt-5.5"

        title = await generate_title("We discussed the Q1 roadmap...")
        assert title == "Team Standup Notes"


@pytest.mark.asyncio
async def test_generate_title_uses_first_500_chars():
    """Should use only the first 500 characters of transcript."""
    long_transcript = "x" * 1000

    mock_client = MagicMock()
    mock_client.responses.create = AsyncMock(
        return_value=_make_response("Short Title")
    )

    with (
        patch("app.core.summarizer.settings") as mock_settings,
        patch("app.core.summarizer.get_openai_client", return_value=mock_client),
    ):
        mock_settings.openai_api_key = "test-key"
        mock_settings.openai_llm_model = "gpt-5.5"

        await generate_title(long_transcript)

        content = mock_client.responses.create.await_args.kwargs["input"]
        assert long_transcript[:500] in content
        assert long_transcript[:501] not in content
