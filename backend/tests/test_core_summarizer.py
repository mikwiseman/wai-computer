"""Tests for app/core/summarizer.py - Claude API summarization and entity extraction."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.core.summarizer as summarizer_module
from app.core.summarizer import (
    EntityResult,
    SummarizationError,
    SummaryResult,
    build_summary_prompt,
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
         patch.object(summarizer_module.settings, "anthropic_model", "claude-sonnet-4-6"):
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
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        assert call_kwargs["max_tokens"] == 4096
        assert "My meeting notes" in call_kwargs["messages"][0]["content"]

    async def test_language_param_injected_into_prompt(self):
        """summarize_transcript() injects language into the Claude prompt."""
        mock_response = _make_claude_response(VALID_SUMMARY_JSON)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer._get_anthropic_client", return_value=mock_client):
            await summarize_transcript("Notes", language="ru")

        content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "ru" in content
        assert "OUTPUT LANGUAGE" in content

    async def test_style_param_injected_into_prompt(self):
        """summarize_transcript() injects style into the Claude prompt."""
        mock_response = _make_claude_response(VALID_SUMMARY_JSON)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer._get_anthropic_client", return_value=mock_client):
            await summarize_transcript("Notes", style="brief")

        content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "1-2 sentences" in content

    async def test_custom_instructions_injected_into_prompt(self):
        """summarize_transcript() injects custom instructions into the Claude prompt."""
        mock_response = _make_claude_response(VALID_SUMMARY_JSON)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer._get_anthropic_client", return_value=mock_client):
            await summarize_transcript("Notes", instructions="Focus on deadlines")

        content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "Focus on deadlines" in content
        assert "ADDITIONAL INSTRUCTIONS" in content

    async def test_auto_language_follows_transcript_language(self):
        """summarize_transcript() with language='auto' follows the transcript language."""
        mock_response = _make_claude_response(VALID_SUMMARY_JSON)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer._get_anthropic_client", return_value=mock_client):
            await summarize_transcript("Notes", language="auto")

        content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "OUTPUT LANGUAGE" in content
        assert "dominant language of the transcript" in content


class TestBuildSummaryPrompt:
    def test_default_prompt_has_medium_style(self):
        """build_summary_prompt() includes medium style by default."""
        prompt = build_summary_prompt()
        assert "2-3 sentence" in prompt
        assert "OUTPUT LANGUAGE" in prompt
        assert "dominant language of the transcript" in prompt
        assert "ADDITIONAL INSTRUCTIONS" not in prompt

    def test_brief_style(self):
        """build_summary_prompt(style='brief') includes brief instructions."""
        prompt = build_summary_prompt(style="brief")
        assert "1-2 sentences" in prompt

    def test_detailed_style(self):
        """build_summary_prompt(style='detailed') includes detailed instructions."""
        prompt = build_summary_prompt(style="detailed")
        assert "4-6 sentence" in prompt

    def test_language_directive(self):
        """build_summary_prompt(language='ru') adds OUTPUT LANGUAGE directive."""
        prompt = build_summary_prompt(language="ru")
        assert "OUTPUT LANGUAGE" in prompt
        assert "ru" in prompt

    def test_custom_instructions(self):
        """build_summary_prompt(instructions=...) adds ADDITIONAL INSTRUCTIONS."""
        prompt = build_summary_prompt(instructions="Emphasize risks")
        assert "ADDITIONAL INSTRUCTIONS" in prompt
        assert "Emphasize risks" in prompt

    def test_all_params_combined(self):
        """build_summary_prompt() combines all parameters correctly."""
        prompt = build_summary_prompt(language="en", style="detailed", instructions="Be formal")
        assert "OUTPUT LANGUAGE" in prompt
        assert "4-6 sentence" in prompt
        assert "Be formal" in prompt
        assert "Transcript:" in prompt


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
