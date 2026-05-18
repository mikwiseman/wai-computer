"""Tests for app/core/summarizer.py — OpenAI Responses API structured outputs."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.core.summarizer as summarizer_module
from app.core.summarizer import (
    EntityResult,
    SummarizationError,
    SummaryResult,
    _ActionItem,
    _Decision,
    _Entity,
    _EntityExtractionSchema,
    _EntityRelation,
    _Highlight,
    _SummarySchema,
    build_summary_prompt,
    extract_entities,
    summarize_transcript,
)


def _summary_schema_payload(**overrides) -> _SummarySchema:
    """Construct a complete _SummarySchema instance with reasonable defaults."""
    base = dict(
        title="Q1 Planning Meeting",
        summary="Team discussed Q1 goals and timelines.",
        key_points=["Budget approved", "Hiring plan finalized"],
        decisions=[_Decision(decision="Hire 3 engineers", context="Team growth")],
        action_items=[
            _ActionItem(task="Post job listings", owner="Alice", due="2026-03-01", priority="high")
        ],
        topics=["hiring", "budget"],
        people_mentioned=["Alice", "Bob"],
        follow_up_questions=["When is the next review?"],
        sentiment="positive",
        highlights=[
            _Highlight(
                category="decision",
                title="Approved hiring plan",
                description="Team agreed to hire 3 engineers.",
                speaker="Alice",
                importance="high",
            )
        ],
    )
    base.update(overrides)
    return _SummarySchema(**base)


def _entity_schema_payload() -> _EntityExtractionSchema:
    return _EntityExtractionSchema(
        entities=[
            _Entity(
                name="Alice",
                type="person",
                context="Lead engineer discussed hiring",
                relations=[
                    _EntityRelation(related_to="Engineering Team", relation_type="works_on")
                ],
            ),
            _Entity(
                name="Project Alpha",
                type="project",
                context="Main project under discussion",
                relations=[],
            ),
        ]
    )


def _parsed_response(parsed) -> MagicMock:
    response = MagicMock()
    response.output_parsed = parsed
    response.status = "completed"
    response.error = None
    response.incomplete_details = None
    response.output = []
    return response


@pytest.fixture(autouse=True)
def mock_settings():
    """Patch settings attributes on the already-imported module."""
    with patch.object(summarizer_module.settings, "openai_api_key", "sk-test"), \
         patch.object(summarizer_module.settings, "openai_llm_model", "gpt-5.5"):
        yield


class TestSummarizeTranscript:
    async def test_returns_summary_result_from_parsed_payload(self):
        mock_response = _parsed_response(_summary_schema_payload())
        mock_client = MagicMock()
        mock_client.responses.parse = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_openai_client", return_value=mock_client):
            result = await summarize_transcript("Some transcript text")

        assert isinstance(result, SummaryResult)
        assert result.title == "Q1 Planning Meeting"
        assert result.summary == "Team discussed Q1 goals and timelines."
        assert len(result.key_points) == 2
        assert result.sentiment == "positive"
        assert len(result.action_items) == 1
        assert result.action_items[0]["owner"] == "Alice"
        assert result.highlights[0]["category"] == "decision"

    async def test_no_padding_when_action_items_empty(self):
        """When the model returns no action items, the result has an empty list (not invented)."""
        mock_response = _parsed_response(_summary_schema_payload(action_items=[]))
        mock_client = MagicMock()
        mock_client.responses.parse = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_openai_client", return_value=mock_client):
            result = await summarize_transcript("Casual chitchat with no commitments")

        assert result.action_items == []

    async def test_missing_api_key_raises_value_error(self):
        with patch.object(summarizer_module.settings, "openai_api_key", ""):
            with pytest.raises(ValueError, match="OPENAI_API_KEY not configured"):
                await summarize_transcript("Some transcript")

    async def test_parser_error_wrapped_in_summarization_error(self):
        mock_client = MagicMock()
        mock_client.responses.parse = AsyncMock(side_effect=Exception("upstream blew up"))

        with patch("app.core.summarizer.get_openai_client", return_value=mock_client):
            with pytest.raises(SummarizationError, match="Summarization failed"):
                await summarize_transcript("Transcript")

    async def test_none_parsed_payload_raises_summarization_error(self):
        mock_client = MagicMock()
        mock_client.responses.parse = AsyncMock(return_value=_parsed_response(None))

        with patch("app.core.summarizer.get_openai_client", return_value=mock_client):
            with pytest.raises(SummarizationError, match="no parsed summary"):
                await summarize_transcript("Transcript")

    async def test_calls_responses_parse_with_correct_params(self):
        mock_response = _parsed_response(_summary_schema_payload())
        mock_client = MagicMock()
        mock_client.responses.parse = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_openai_client", return_value=mock_client):
            await summarize_transcript("My meeting notes")

        mock_client.responses.parse.assert_awaited_once()
        kwargs = mock_client.responses.parse.await_args.kwargs
        assert kwargs["model"] == "gpt-5.5"
        assert kwargs["max_output_tokens"] == 4096
        assert kwargs["text_format"] is _SummarySchema
        assert kwargs["reasoning"] == {"effort": "medium"}
        assert "My meeting notes" in kwargs["input"]

    async def test_language_param_injected_into_prompt(self):
        mock_response = _parsed_response(_summary_schema_payload())
        mock_client = MagicMock()
        mock_client.responses.parse = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_openai_client", return_value=mock_client):
            await summarize_transcript("Notes", language="ru")

        content = mock_client.responses.parse.await_args.kwargs["input"]
        assert "ru" in content
        assert "OUTPUT LANGUAGE" in content

    async def test_style_param_injected_into_prompt(self):
        mock_response = _parsed_response(_summary_schema_payload())
        mock_client = MagicMock()
        mock_client.responses.parse = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_openai_client", return_value=mock_client):
            await summarize_transcript("Notes", style="brief")

        content = mock_client.responses.parse.await_args.kwargs["input"]
        assert "1-2 sentences" in content

    async def test_custom_instructions_injected_into_prompt(self):
        mock_response = _parsed_response(_summary_schema_payload())
        mock_client = MagicMock()
        mock_client.responses.parse = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_openai_client", return_value=mock_client):
            await summarize_transcript("Notes", instructions="Focus on deadlines")

        content = mock_client.responses.parse.await_args.kwargs["input"]
        assert "Focus on deadlines" in content
        assert "ADDITIONAL INSTRUCTIONS" in content

    async def test_auto_language_follows_transcript_language(self):
        mock_response = _parsed_response(_summary_schema_payload())
        mock_client = MagicMock()
        mock_client.responses.parse = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_openai_client", return_value=mock_client):
            await summarize_transcript("Notes", language="auto")

        content = mock_client.responses.parse.await_args.kwargs["input"]
        assert "OUTPUT LANGUAGE" in content
        assert "dominant language of the transcript" in content


class TestBuildSummaryPrompt:
    def test_default_prompt_has_medium_style(self):
        prompt = build_summary_prompt()
        assert "2-3 sentence" in prompt
        assert "OUTPUT LANGUAGE" in prompt
        assert "dominant language of the transcript" in prompt
        assert "ADDITIONAL INSTRUCTIONS" not in prompt

    def test_anti_hallucination_rule_present(self):
        prompt = build_summary_prompt()
        assert "Do not invent facts" in prompt
        assert "Do not pad" in prompt

    def test_brief_style(self):
        prompt = build_summary_prompt(style="brief")
        assert "1-2 sentences" in prompt

    def test_detailed_style(self):
        prompt = build_summary_prompt(style="detailed")
        assert "4-6 sentence" in prompt

    def test_language_directive(self):
        prompt = build_summary_prompt(language="ru")
        assert "OUTPUT LANGUAGE" in prompt
        assert "ru" in prompt

    def test_custom_instructions(self):
        prompt = build_summary_prompt(instructions="Emphasize risks")
        assert "ADDITIONAL INSTRUCTIONS" in prompt
        assert "Emphasize risks" in prompt

    def test_all_params_combined(self):
        prompt = build_summary_prompt(language="en", style="detailed", instructions="Be formal")
        assert "OUTPUT LANGUAGE" in prompt
        assert "4-6 sentence" in prompt
        assert "Be formal" in prompt
        assert "Transcript:" in prompt


class TestExtractEntities:
    async def test_returns_entity_results_correctly(self):
        mock_response = _parsed_response(_entity_schema_payload())
        mock_client = MagicMock()
        mock_client.responses.parse = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_openai_client", return_value=mock_client):
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

    async def test_parser_error_wrapped_in_summarization_error(self):
        mock_client = MagicMock()
        mock_client.responses.parse = AsyncMock(side_effect=Exception("upstream blew up"))

        with patch("app.core.summarizer.get_openai_client", return_value=mock_client):
            with pytest.raises(SummarizationError, match="Entity extraction failed"):
                await extract_entities("Transcript")

    async def test_missing_api_key_raises_value_error(self):
        with patch.object(summarizer_module.settings, "openai_api_key", ""):
            with pytest.raises(ValueError, match="OPENAI_API_KEY not configured"):
                await extract_entities("Some transcript")
