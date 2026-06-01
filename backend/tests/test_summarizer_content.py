"""Unit tests for the universal content summarizer + key-moments table.

The OpenAI Responses client is stubbed, so these assert our prompt-building,
schema wiring, and result mapping without a network call.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core import summarizer
from app.core.summarizer import (
    KeyMoment,
    _KeyMomentsSchema,
    _SummarySchema,
    build_content_summary_prompt,
    extract_key_moments,
    resolve_key_moment_timestamps,
    summarize_content,
)


def test_content_prompt_mentions_kind_and_language() -> None:
    prompt = build_content_summary_prompt(content_kind="web article", language="English")
    assert "web article" in prompt
    assert "English" in prompt
    assert prompt.rstrip().endswith("Content:")


def test_content_prompt_auto_language_default() -> None:
    prompt = build_content_summary_prompt()
    assert "dominant language" in prompt


def _summary_payload() -> _SummarySchema:
    return _SummarySchema(
        title="Solar in 2026",
        summary="An overview of solar deployment.",
        key_points=["costs fell", "storage grew"],
        decisions=[],
        action_items=[],
        topics=["energy"],
        people_mentioned=[],
        follow_up_questions=[],
        sentiment="neutral",
        highlights=[],
    )


@pytest.mark.asyncio
async def test_summarize_content_maps_result() -> None:
    fake_response = SimpleNamespace(output_parsed=_summary_payload(), status="completed")
    fake_client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=fake_response))
    )
    with (
        patch.object(summarizer, "get_openai_client", return_value=fake_client),
        patch.object(summarizer, "ensure_response_completed"),
        patch.object(summarizer.settings, "openai_api_key", "sk-test"),
    ):
        result = await summarize_content("Some article text", content_kind="web article")

    assert result.title == "Solar in 2026"
    assert result.key_points == ["costs fell", "storage grew"]
    # The general-content prompt (not the meeting one) was used.
    sent = fake_client.responses.parse.call_args.kwargs["input"]
    assert "web article" in sent
    assert fake_client.responses.parse.call_args.kwargs["text_format"] is _SummarySchema


@pytest.mark.asyncio
async def test_extract_key_moments_maps_rows() -> None:
    payload = _KeyMomentsSchema(
        moments=[
            {
                "timestamp": "01:23",
                "moment": "Thesis stated",
                "why_it_matters": "Frames the argument",
                "quote": "Solar is the cheapest power",
                "importance": "high",
            },
            {
                "timestamp": None,
                "moment": "Counterpoint",
                "why_it_matters": "Adds nuance",
                "quote": None,
                "importance": "medium",
            },
        ]
    )
    fake_response = SimpleNamespace(output_parsed=payload, status="completed")
    fake_client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=fake_response))
    )
    with (
        patch.object(summarizer, "get_openai_client", return_value=fake_client),
        patch.object(summarizer, "ensure_response_completed"),
        patch.object(summarizer.settings, "openai_api_key", "sk-test"),
    ):
        moments = await extract_key_moments("transcript with [01:23] marker")

    assert len(moments) == 2
    assert moments[0].timestamp == "01:23"
    assert moments[0].importance == "high"
    assert moments[1].timestamp is None
    assert fake_client.responses.parse.call_args.kwargs["text_format"] is _KeyMomentsSchema


def test_resolve_key_moment_timestamps_matches_segment() -> None:
    moments = [
        KeyMoment(
            timestamp=None,
            moment="discussion about the budget approval",
            why_it_matters="x",
            quote="budget approved",
            importance="high",
        )
    ]
    segments = [
        {"content": "unrelated small talk about weather", "start_ms": 0, "end_ms": 1000},
        {"content": "the budget approval was confirmed", "start_ms": 5000, "end_ms": 8000},
    ]
    resolved = resolve_key_moment_timestamps(moments, segments)
    assert resolved[0].start_ms == 5000
    assert resolved[0].end_ms == 8000


def test_resolve_key_moment_timestamps_no_segments_noop() -> None:
    moments = [
        KeyMoment(timestamp=None, moment="m", why_it_matters="w", quote=None, importance="low")
    ]
    assert resolve_key_moment_timestamps(moments, []) == moments


def test_content_prompt_appends_additional_instructions() -> None:
    prompt = build_content_summary_prompt(
        content_kind="web article",
        language="English",
        instructions="  Focus on pricing.  ",
    )
    assert "ADDITIONAL INSTRUCTIONS: Focus on pricing." in prompt


@pytest.mark.asyncio
async def test_summarize_content_requires_api_key() -> None:
    with patch.object(summarizer.settings, "openai_api_key", ""):
        with pytest.raises(ValueError, match="OPENAI_API_KEY not configured"):
            await summarize_content("text", content_kind="web article")


@pytest.mark.asyncio
async def test_extract_key_moments_requires_api_key() -> None:
    with patch.object(summarizer.settings, "openai_api_key", ""):
        with pytest.raises(ValueError, match="OPENAI_API_KEY not configured"):
            await extract_key_moments("text")
