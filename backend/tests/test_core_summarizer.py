"""Tests for app/core/summarizer.py - Claude API summarization and entity extraction."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.core.summarizer as summarizer_module
from app.core.summarizer import (
    EntityResult,
    SummarizationError,
    SummaryResult,
    extract_entities,
    summarize_transcript,
)


def _make_claude_response(text: str):
    """Create a mock Claude API response with the given text content."""
    mock_content_block = MagicMock()
    mock_content_block.text = text
    mock_message = MagicMock()
    mock_message.content = [mock_content_block]
    return mock_message


VALID_SUMMARY_JSON = json.dumps({
    "title": "Q1 Planning Meeting",
    "summary": "Team discussed Q1 goals and timelines.",
    "key_points": ["Budget approved", "Hiring plan finalized"],
    "decisions": [{"decision": "Hire 3 engineers", "context": "Team growth"}],
    "action_items": [
        {"task": "Post job listings", "owner": "Alice", "due": "2026-03-01", "priority": "high"}
    ],
    "topics": ["hiring", "budget"],
    "people_mentioned": ["Alice", "Bob"],
    "follow_up_questions": ["When is the next review?"],
    "sentiment": "positive",
})

VALID_ENTITY_JSON = json.dumps({
    "entities": [
        {
            "name": "Alice",
            "type": "person",
            "context": "Lead engineer discussed hiring",
            "relations": [{"related_to": "Engineering Team", "relation_type": "works_on"}],
        },
        {
            "name": "Project Alpha",
            "type": "project",
            "context": "Main project under discussion",
            "relations": [],
        },
    ]
})


@pytest.fixture(autouse=True)
def mock_settings():
    """Patch settings attributes on the already-imported module."""
    with patch.object(summarizer_module.settings, "anthropic_api_key", "sk-ant-test-key"), \
         patch.object(summarizer_module.settings, "anthropic_model", "claude-sonnet-4-20250514"):
        yield


class TestSummarizeTranscript:
    async def test_plain_json_response(self):
        """summarize_transcript() parses plain JSON response correctly."""
        mock_response = _make_claude_response(VALID_SUMMARY_JSON)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer._get_anthropic_client", return_value=mock_client):
            result = await summarize_transcript("Some transcript text")

        assert isinstance(result, SummaryResult)
        assert result.title == "Q1 Planning Meeting"
        assert result.summary == "Team discussed Q1 goals and timelines."
        assert len(result.key_points) == 2
        assert result.sentiment == "positive"
        assert len(result.action_items) == 1
        assert result.action_items[0]["owner"] == "Alice"

    async def test_json_in_json_code_block(self):
        """summarize_transcript() extracts JSON from ```json code blocks."""
        wrapped = f"Here is the analysis:\n```json\n{VALID_SUMMARY_JSON}\n```\nDone."
        mock_response = _make_claude_response(wrapped)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer._get_anthropic_client", return_value=mock_client):
            result = await summarize_transcript("Transcript here")

        assert isinstance(result, SummaryResult)
        assert result.title == "Q1 Planning Meeting"

    async def test_json_in_plain_code_block(self):
        """summarize_transcript() extracts JSON from plain ``` code blocks."""
        wrapped = f"Result:\n```\n{VALID_SUMMARY_JSON}\n```"
        mock_response = _make_claude_response(wrapped)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer._get_anthropic_client", return_value=mock_client):
            result = await summarize_transcript("Transcript here")

        assert isinstance(result, SummaryResult)
        assert result.title == "Q1 Planning Meeting"

    async def test_missing_api_key_raises_value_error(self):
        """summarize_transcript() raises ValueError when API key is empty."""
        with patch.object(summarizer_module.settings, "anthropic_api_key", ""):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY not configured"):
                await summarize_transcript("Some transcript")

    async def test_invalid_json_raises_summarization_error(self):
        """summarize_transcript() raises SummarizationError when Claude returns invalid JSON."""
        mock_response = _make_claude_response("This is not valid JSON at all {{{")
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer._get_anthropic_client", return_value=mock_client):
            with pytest.raises(SummarizationError, match="Invalid JSON response from Claude"):
                await summarize_transcript("Transcript")

    async def test_calls_claude_api_with_correct_params(self):
        """summarize_transcript() calls Claude API with correct model and prompt."""
        mock_response = _make_claude_response(VALID_SUMMARY_JSON)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch(
            "app.core.summarizer._get_anthropic_client",
            return_value=mock_client,
        ):
            await summarize_transcript("My meeting notes")

        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-20250514"
        assert call_kwargs["max_tokens"] == 4096
        assert "My meeting notes" in call_kwargs["messages"][0]["content"]


class TestExtractEntities:
    async def test_returns_entity_results_correctly(self):
        """extract_entities() returns a list of EntityResult dataclasses."""
        mock_response = _make_claude_response(VALID_ENTITY_JSON)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer._get_anthropic_client", return_value=mock_client):
            results = await extract_entities("Transcript with entities")

        assert len(results) == 2
        assert all(isinstance(r, EntityResult) for r in results)

        assert results[0].name == "Alice"
        assert results[0].type == "person"
        assert results[0].context == "Lead engineer discussed hiring"
        assert len(results[0].relations) == 1
        assert results[0].relations[0]["relation_type"] == "works_on"

        assert results[1].name == "Project Alpha"
        assert results[1].type == "project"

    async def test_invalid_json_raises_summarization_error(self):
        """extract_entities() raises SummarizationError when Claude returns invalid JSON."""
        mock_response = _make_claude_response("not json!!")
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer._get_anthropic_client", return_value=mock_client):
            with pytest.raises(SummarizationError, match="Invalid JSON response from Claude"):
                await extract_entities("Transcript")

    async def test_missing_api_key_raises_value_error(self):
        """extract_entities() raises ValueError when API key is empty."""
        with patch.object(summarizer_module.settings, "anthropic_api_key", ""):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY not configured"):
                await extract_entities("Some transcript")

    async def test_extracts_from_json_code_block(self):
        """extract_entities() handles JSON wrapped in ```json code blocks."""
        wrapped = f"```json\n{VALID_ENTITY_JSON}\n```"
        mock_response = _make_claude_response(wrapped)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer._get_anthropic_client", return_value=mock_client):
            results = await extract_entities("Transcript")

        assert len(results) == 2
        assert results[0].name == "Alice"
