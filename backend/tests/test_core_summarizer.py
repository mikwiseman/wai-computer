"""Tests for app/core/summarizer.py — Cerebras Chat Completions structured outputs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.core.summarizer as summarizer_module
from app.core.summarizer import (
    EntityResult,
    KeyMoment,
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
    extract_key_moments,
    generate_title,
    resolve_highlight_timestamps,
    resolve_key_moment_timestamps,
    summarize_content,
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


def _key_moments_payload():
    return summarizer_module._KeyMomentsSchema(
        moments=[
            summarizer_module._KeyMoment(
                timestamp="00:10",
                moment="Alice approved the launch plan",
                why_it_matters="The release is unblocked.",
                quote="approved the launch",
                importance="high",
            ),
            summarizer_module._KeyMoment(
                timestamp=None,
                moment="Budget needs a second review",
                why_it_matters="Finance follow-up is required.",
                quote=None,
                importance="medium",
            ),
        ]
    )


def _parsed_response(parsed) -> MagicMock:
    if parsed is None:
        return _text_response("")
    return _text_response(parsed.model_dump_json())


def _text_response(text: str) -> MagicMock:
    response = MagicMock()
    response.model = "gpt-oss-120b"
    response.choices = [
        SimpleNamespace(
            finish_reason="stop",
            message=SimpleNamespace(content=text),
        )
    ]
    return response


@pytest.fixture(autouse=True)
def mock_settings():
    """Patch settings attributes on the already-imported module."""
    with patch.object(summarizer_module.settings, "cerebras_api_key", "sk-test"), \
         patch.object(summarizer_module.settings, "cerebras_llm_model", "gpt-oss-120b"):
        yield


class TestSummarizeTranscript:
    async def test_returns_summary_result_from_parsed_payload(self):
        mock_response = _parsed_response(_summary_schema_payload())
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
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
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
            result = await summarize_transcript("Casual chitchat with no commitments")

        assert result.action_items == []

    async def test_missing_api_key_raises_value_error(self):
        with patch.object(summarizer_module.settings, "cerebras_api_key", ""):
            with pytest.raises(ValueError, match="CEREBRAS_API_KEY not configured"):
                await summarize_transcript("Some transcript")

    async def test_parser_error_wrapped_in_summarization_error(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("upstream blew up"))

        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
            with pytest.raises(SummarizationError, match="Summarization failed"):
                await summarize_transcript("Transcript")

    async def test_none_parsed_payload_raises_summarization_error(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_parsed_response(None))

        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
            with pytest.raises(SummarizationError, match="returned empty text"):
                await summarize_transcript("Transcript")

    async def test_calls_chat_completions_with_correct_params(self):
        mock_response = _parsed_response(_summary_schema_payload())
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
            await summarize_transcript("My meeting notes")

        mock_client.chat.completions.create.assert_awaited_once()
        kwargs = mock_client.chat.completions.create.await_args.kwargs
        assert kwargs["model"] == "gpt-oss-120b"
        assert kwargs["max_completion_tokens"] == 4096
        assert kwargs["response_format"]["json_schema"]["name"] == "recording_summary"
        assert kwargs["reasoning_effort"] == "medium"
        assert "My meeting notes" in kwargs["messages"][1]["content"]

    async def test_language_param_injected_into_prompt(self):
        mock_response = _parsed_response(_summary_schema_payload())
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
            await summarize_transcript("Notes", language="ru")

        content = mock_client.chat.completions.create.await_args.kwargs["messages"][1]["content"]
        assert "ru" in content
        assert "OUTPUT LANGUAGE" in content

    async def test_style_param_injected_into_prompt(self):
        mock_response = _parsed_response(_summary_schema_payload())
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
            await summarize_transcript("Notes", style="brief")

        content = mock_client.chat.completions.create.await_args.kwargs["messages"][1]["content"]
        assert "1-2 sentences" in content

    async def test_custom_instructions_injected_into_prompt(self):
        mock_response = _parsed_response(_summary_schema_payload())
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
            await summarize_transcript("Notes", instructions="Focus on deadlines")

        content = mock_client.chat.completions.create.await_args.kwargs["messages"][1]["content"]
        assert "Focus on deadlines" in content
        assert "ADDITIONAL INSTRUCTIONS" in content

    async def test_auto_language_follows_transcript_language(self):
        mock_response = _parsed_response(_summary_schema_payload())
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
            await summarize_transcript("Notes", language="auto")

        content = mock_client.chat.completions.create.await_args.kwargs["messages"][1]["content"]
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

    def test_structured_style_has_no_sentence_count(self):
        prompt = build_summary_prompt(style="structured")
        # No positive sentence-count directive (the bug that forced prose).
        assert "2-3 sentence" not in prompt
        assert "4-6 sentence" not in prompt
        assert "1-2 sentences" not in prompt
        assert "Cover the content completely" in prompt

    def test_base_framing_is_kind_neutral_not_meeting_only(self):
        # Was "You summarize a meeting transcript"; must not bias non-meeting audio.
        prompt = build_summary_prompt()
        assert "a meeting transcript. " not in prompt
        assert "voice note" in prompt

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


class TestContentSummariesAndMoments:
    def test_content_summary_prompt_variants(self):
        prompt = summarizer_module.build_content_summary_prompt(
            content_kind="article",
            language="ru",
            style="detailed",
            instructions="Keep project names exact",
        )

        assert "content is a article" in prompt
        assert "4-6 sentence" in prompt
        assert "ru" in prompt
        assert "Keep project names exact" in prompt

        default_prompt = summarizer_module.build_content_summary_prompt(
            content_kind="content",
            language="auto",
            style="unknown-style",
        )
        assert "dominant language of the content" in default_prompt
        assert "2-3 sentence" in default_prompt

    async def test_summarize_content_returns_structured_result(self):
        mock_response = _parsed_response(_summary_schema_payload(title="Saved Article"))
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
            result = await summarize_content(
                "Article body",
                content_kind="article",
                language="en",
                style="brief",
                instructions="No fluff",
            )

        assert result.title == "Saved Article"
        assert result.highlights[0]["title"] == "Approved hiring plan"
        kwargs = mock_client.chat.completions.create.await_args.kwargs
        assert kwargs["response_format"]["json_schema"]["name"] == "content_summary"
        assert kwargs["reasoning_effort"] == "medium"
        assert "Article body" in kwargs["messages"][1]["content"]
        assert "No fluff" in kwargs["messages"][1]["content"]

    async def test_summarize_content_errors_are_explicit(self):
        with patch.object(summarizer_module.settings, "cerebras_api_key", ""):
            with pytest.raises(ValueError, match="CEREBRAS_API_KEY not configured"):
                await summarize_content("body")

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("upstream"))
        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
            with pytest.raises(SummarizationError, match="Content summarization failed"):
                await summarize_content("body")

        mock_client.chat.completions.create = AsyncMock(return_value=_parsed_response(None))
        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
            with pytest.raises(SummarizationError, match="returned empty text"):
                await summarize_content("body")

    async def test_extract_key_moments_returns_rows_and_builds_language_prompt(self):
        mock_response = _parsed_response(_key_moments_payload())
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
            result = await extract_key_moments("Transcript", language="ru")

        assert [moment.importance for moment in result] == ["high", "medium"]
        assert result[0].quote == "approved the launch"
        kwargs = mock_client.chat.completions.create.await_args.kwargs
        assert kwargs["response_format"]["json_schema"]["name"] == "key_moments"
        assert kwargs["reasoning_effort"] == "medium"
        assert "Write all text in ru" in kwargs["messages"][1]["content"]

    async def test_extract_key_moments_errors_are_explicit(self):
        with patch.object(summarizer_module.settings, "cerebras_api_key", ""):
            with pytest.raises(ValueError, match="CEREBRAS_API_KEY not configured"):
                await extract_key_moments("body")

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("upstream"))
        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
            with pytest.raises(SummarizationError, match="Key moments extraction failed"):
                await extract_key_moments("body")

        mock_client.chat.completions.create = AsyncMock(return_value=_parsed_response(None))
        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
            with pytest.raises(SummarizationError, match="returned empty text"):
                await extract_key_moments("body")

    async def test_generate_title_uses_response_text_and_wraps_incomplete_response(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_text_response("Roadmap Sync"))

        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
            title = await generate_title("Transcript body", language="multi")

        assert title == "Roadmap Sync"
        kwargs = mock_client.chat.completions.create.await_args.kwargs
        assert "dominant language of the transcript" in kwargs["messages"][1]["content"]

        with patch.object(summarizer_module.settings, "cerebras_api_key", ""):
            with pytest.raises(ValueError, match="CEREBRAS_API_KEY not configured"):
                await generate_title("Transcript")

        failed = _text_response("ignored")
        failed.choices[0].finish_reason = "length"
        mock_client.chat.completions.create = AsyncMock(return_value=failed)
        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
            with pytest.raises(SummarizationError, match="Title generation failed"):
                await generate_title("Transcript", language="ru")

    def test_timestamp_resolvers_match_words_without_mutating_when_empty(self):
        moments = [
            KeyMoment(
                timestamp=None,
                moment="Alice approved launch",
                why_it_matters="Release can proceed",
                quote="approved launch",
                importance="high",
            )
        ]
        assert resolve_key_moment_timestamps(moments, []) is moments
        resolved = resolve_key_moment_timestamps(
            moments,
            [
                {"content": "Budget discussion only", "start_ms": 0, "end_ms": 1_000},
                {
                    "content": "Alice approved launch yesterday",
                    "start_ms": 2_000,
                    "end_ms": 3_000,
                },
            ],
        )
        assert resolved[0].start_ms == 2_000
        assert resolved[0].end_ms == 3_000

        highlights = [{"title": "Budget", "description": "No matching words"}]
        assert resolve_highlight_timestamps(highlights, []) is highlights
        matched = resolve_highlight_timestamps(
            [{"title": "Launch approved", "description": "Alice said yes"}],
            [{"content": "Alice said the launch was approved", "start_ms": 4_000, "end_ms": 5_000}],
        )
        assert matched[0]["start_ms"] == 4_000
        assert matched[0]["end_ms"] == 5_000


class TestExtractEntities:
    async def test_returns_entity_results_correctly(self):
        mock_response = _parsed_response(_entity_schema_payload())
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
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
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("upstream blew up"))

        with patch("app.core.summarizer.get_cerebras_client", return_value=mock_client):
            with pytest.raises(SummarizationError, match="Entity extraction failed"):
                await extract_entities("Transcript")

    async def test_missing_api_key_raises_value_error(self):
        with patch.object(summarizer_module.settings, "cerebras_api_key", ""):
            with pytest.raises(ValueError, match="CEREBRAS_API_KEY not configured"):
                await extract_entities("Some transcript")


def test_chunk_transcript_splits_with_overlap():
    from app.core.summarizer import _chunk_transcript

    text = "\n".join(f"line {i} " + "y" * 50 for i in range(50))
    chunks = _chunk_transcript(text, max_chars=500, overlap_lines=2)
    assert len(chunks) > 1
    # The trailing lines of one chunk reappear at the start of the next (overlap).
    last_line_of_first = chunks[0].split("\n")[-1]
    assert last_line_of_first in chunks[1]


def test_chunk_transcript_single_chunk_when_short():
    from app.core.summarizer import _chunk_transcript

    assert _chunk_transcript("a\nb\nc", max_chars=10_000) == ["a\nb\nc"]


def test_dedup_strings_dedups_and_caps():
    from app.core.summarizer import _dedup_strings

    assert _dedup_strings(["A", "a", " A ", "B", ""], cap=10) == ["A", "B"]
    assert _dedup_strings(["x"] * 20, cap=3) == ["x"]


def test_dedup_dicts_by_key():
    from app.core.summarizer import _dedup_dicts

    items = [{"task": "Do X"}, {"task": "do x"}, {"task": "Y"}, {"task": ""}]
    assert _dedup_dicts(items, "task", cap=10) == [{"task": "Do X"}, {"task": "Y"}]


def _canned_summary(**overrides):
    base = dict(
        title="T",
        summary="chunk summary",
        key_points=["kp"],
        decisions=[],
        action_items=[{"task": "do x", "owner": None, "due": None, "priority": "medium"}],
        topics=["topic"],
        people_mentioned=[],
        follow_up_questions=[],
        sentiment="neutral",
        highlights=[],
    )
    base.update(overrides)
    return SummaryResult(**base)


async def test_summarize_transcript_single_pass_below_threshold(monkeypatch):
    calls: list[str] = []

    async def fake_once(transcript, **kwargs):
        calls.append(kwargs.get("name", "recording_summary"))
        return _canned_summary()

    monkeypatch.setattr(summarizer_module, "_summarize_transcript_once", fake_once)
    await summarizer_module.summarize_transcript("short transcript")
    assert calls == ["recording_summary"]


async def test_summarize_transcript_map_reduces_above_threshold(monkeypatch):
    calls: list[str] = []

    async def fake_once(transcript, **kwargs):
        calls.append(kwargs.get("name", "recording_summary"))
        return _canned_summary(summary=f"sum-{len(calls)}")

    monkeypatch.setattr(summarizer_module, "_summarize_transcript_once", fake_once)
    big = ("speaker: " + "x" * 100 + "\n") * 800  # ~88k chars > threshold
    result = await summarizer_module.summarize_transcript(big)

    assert calls.count("recording_summary_chunk") >= 2
    assert calls.count("recording_summary_reduce") == 1
    # Identical per-chunk lists are deterministically deduped in the merge.
    assert result.key_points == ["kp"]
    assert len(result.action_items) == 1
