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
async def test_generate_title_samples_across_long_transcript():
    """Long transcripts are sampled across head + middle + tail (not just the
    opening), and the prompt steers the model away from small-talk — so a topic
    that surfaces late isn't lost to the recording's opening chit-chat."""
    filler = "обсуждаем разные мелочи "  # neutral small-talk-ish padding
    long_transcript = "СТАРТ_МЕТКА " + filler * 600 + "ХВОСТ_МЕТКА"
    assert len(long_transcript) > 6000  # well past the sampling cap

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_response("Тема записи")
    )

    with (
        patch("app.core.summarizer.settings") as mock_settings,
        patch("app.core.summarizer.get_cerebras_client", return_value=mock_client),
    ):
        mock_settings.cerebras_api_key = "test-key"
        mock_settings.cerebras_llm_model = "gpt-oss-120b"

        await generate_title(long_transcript)

        content = mock_client.chat.completions.create.await_args.kwargs["messages"][1]["content"]
        # The tail reached the model — impossible under the old transcript[:500].
        assert "ХВОСТ_МЕТКА" in content
        assert "СТАРТ_МЕТКА" in content
        # And the prompt tells the model to title by subject, not opening small-talk.
        assert "MAIN subject" in content
        assert "small talk" in content


def test_title_sample_uses_whole_text_when_short():
    """Short transcripts are passed through untouched."""
    from app.core.summarizer import _title_sample

    text = "Короткая запись про геймификацию."
    assert _title_sample(text) == text


def test_title_sample_spans_head_middle_tail_for_long_text():
    """A long transcript yields a bounded head+middle+tail excerpt, not the head alone."""
    from app.core.summarizer import TITLE_SAMPLE_MAX_CHARS, _title_sample

    side = "блаблабла " * 1000  # 10k chars per side
    text = "НАЧАЛО_ТЕМА " + side + " СЕРЕДИНА_ТЕМА " + side + " КОНЕЦ_ТЕМА"
    assert len(text) > TITLE_SAMPLE_MAX_CHARS

    sample = _title_sample(text)
    assert "НАЧАЛО_ТЕМА" in sample
    assert "СЕРЕДИНА_ТЕМА" in sample
    assert "КОНЕЦ_ТЕМА" in sample
    assert "[...]" in sample  # head/middle/tail joined by an elision marker
    assert len(sample) < len(text)  # we did NOT send the whole transcript


def test_summary_prompt_requires_canonical_deduplicated_people():
    """The summary prompt must instruct one canonical, nominative entry per person
    so Russian case-forms/diminutives (Коля/Колей, Лёша/Лёш) don't duplicate."""
    prompt = build_summary_prompt(language="auto")
    assert "people_mentioned" in prompt
    assert "nominative case" in prompt
    assert "Never list the same person twice" in prompt


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
