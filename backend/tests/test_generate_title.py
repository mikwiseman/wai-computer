"""Tests for generate_title function."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.summarizer import generate_title


@pytest.mark.asyncio
async def test_generate_title_no_api_key():
    """Should raise ValueError when ANTHROPIC_API_KEY is not set."""
    with patch("app.core.summarizer.settings") as mock_settings:
        mock_settings.anthropic_api_key = ""
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY not configured"):
            await generate_title("Hello world")


@pytest.mark.asyncio
async def test_generate_title_returns_stripped_title():
    """Should strip quotes and whitespace from title."""
    mock_content = MagicMock()
    mock_content.text = '  "Team Standup Notes"  '

    mock_message = MagicMock()
    mock_message.content = [mock_content]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with (
        patch("app.core.summarizer.settings") as mock_settings,
        patch("app.core.summarizer._get_anthropic_client", return_value=mock_client),
    ):
        mock_settings.anthropic_api_key = "test-key"
        mock_settings.anthropic_model = "claude-sonnet-4-6"

        title = await generate_title("We discussed the Q1 roadmap...")
        assert title == "Team Standup Notes"


@pytest.mark.asyncio
async def test_generate_title_truncates_long_titles():
    """Should truncate titles longer than 100 characters."""
    mock_content = MagicMock()
    mock_content.text = "A" * 200

    mock_message = MagicMock()
    mock_message.content = [mock_content]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with (
        patch("app.core.summarizer.settings") as mock_settings,
        patch("app.core.summarizer._get_anthropic_client", return_value=mock_client),
    ):
        mock_settings.anthropic_api_key = "test-key"
        mock_settings.anthropic_model = "claude-sonnet-4-6"

        title = await generate_title("Some transcript text")
        assert len(title) == 100
        assert title.endswith("...")


@pytest.mark.asyncio
async def test_generate_title_uses_first_500_chars():
    """Should use only the first 500 characters of transcript."""
    long_transcript = "x" * 1000

    mock_content = MagicMock()
    mock_content.text = "Short Title"

    mock_message = MagicMock()
    mock_message.content = [mock_content]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with (
        patch("app.core.summarizer.settings") as mock_settings,
        patch("app.core.summarizer._get_anthropic_client", return_value=mock_client),
    ):
        mock_settings.anthropic_api_key = "test-key"
        mock_settings.anthropic_model = "claude-sonnet-4-6"

        await generate_title(long_transcript)

        call_args = mock_client.messages.create.call_args
        content = call_args.kwargs["messages"][0]["content"]
        # The transcript snippet in the prompt should be at most 500 chars
        assert long_transcript[:500] in content
        assert long_transcript[:501] not in content
