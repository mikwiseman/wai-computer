"""Tests for bug fixes from comprehensive analysis round 1.

Covers:
- format_embedding utility consistency
- Password whitespace validation in settings
- Highlight timestamp resolution with punctuation
- Summarization highlights field parsing
"""

import pytest
from httpx import AsyncClient

from app.core.embeddings import format_embedding
from app.core.summarizer import resolve_highlight_timestamps
from tests.conftest import LEGAL_ACCEPTANCE

# ---------------------------------------------------------------------------
# 1. format_embedding — consistent vector string formatting
# ---------------------------------------------------------------------------


class TestFormatEmbedding:
    def test_produces_bracket_format_without_spaces(self):
        """format_embedding() should produce '[0.1,0.2,0.3]' without spaces."""
        embedding = [0.1, 0.2, 0.3]
        result = format_embedding(embedding)
        assert result == "[0.1,0.2,0.3]"
        assert " " not in result

    def test_empty_embedding(self):
        """format_embedding() should handle empty list."""
        result = format_embedding([])
        assert result == "[]"

    def test_single_element(self):
        """format_embedding() should handle single-element list."""
        result = format_embedding([0.5])
        assert result == "[0.5]"

    def test_negative_values(self):
        """format_embedding() should handle negative values."""
        result = format_embedding([-0.1, 0.2, -0.3])
        assert result == "[-0.1,0.2,-0.3]"

    def test_1536_dimensional_embedding(self):
        """format_embedding() should handle a full 1536-dim embedding."""
        embedding = [float(i) / 1536 for i in range(1536)]
        result = format_embedding(embedding)
        assert result.startswith("[")
        assert result.endswith("]")
        parts = result[1:-1].split(",")
        assert len(parts) == 1536

    def test_result_differs_from_str_repr(self):
        """format_embedding() should produce different output than str() for multi-element lists."""
        embedding = [0.1, 0.2, 0.3]
        fmt_result = format_embedding(embedding)
        str_result = str(embedding)
        # str() adds spaces after commas: "[0.1, 0.2, 0.3]"
        # format_embedding should not: "[0.1,0.2,0.3]"
        assert fmt_result != str_result
        assert ", " not in fmt_result


# ---------------------------------------------------------------------------
# 2. Password whitespace validation in settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_password_rejects_whitespace_only_new_password(client: AsyncClient):
    """New password that is only whitespace should be rejected."""
    response = await client.post(
        "/api/auth/register",
        json={
            "email": "bugfix.whitespace@example.com",
            "password": "valid-password-123",
            **LEGAL_ACCEPTANCE,
        },
    )
    assert response.status_code == 200
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    change_response = await client.post(
        "/api/settings/change-password",
        headers=headers,
        json={"current_password": "valid-password-123", "new_password": "        "},
    )
    assert change_response.status_code == 422


@pytest.mark.asyncio
async def test_change_password_rejects_padded_short_password(client: AsyncClient):
    """Password that is 8+ chars but only 3 non-space chars should be rejected."""
    response = await client.post(
        "/api/auth/register",
        json={
            "email": "bugfix.padded@example.com",
            "password": "valid-password-123",
            **LEGAL_ACCEPTANCE,
        },
    )
    assert response.status_code == 200
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    change_response = await client.post(
        "/api/settings/change-password",
        headers=headers,
        json={"current_password": "valid-password-123", "new_password": "   abc  "},
    )
    assert change_response.status_code == 422


@pytest.mark.asyncio
async def test_change_password_accepts_valid_long_password(client: AsyncClient):
    """A valid 8+ char non-whitespace password should be accepted."""
    response = await client.post(
        "/api/auth/register",
        json={
            "email": "bugfix.validpw@example.com",
            "password": "valid-password-123",
            **LEGAL_ACCEPTANCE,
        },
    )
    assert response.status_code == 200
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    change_response = await client.post(
        "/api/settings/change-password",
        headers=headers,
        json={"current_password": "valid-password-123", "new_password": "new-secure-password"},
    )
    assert change_response.status_code == 200


# ---------------------------------------------------------------------------
# 3. Highlight timestamp resolution with punctuation
# ---------------------------------------------------------------------------


class TestHighlightTimestampPunctuation:
    def test_punctuation_stripped_from_segment_words(self):
        """Punctuation in segment content should not prevent matching."""
        segments = [
            {
                "content": "Customer, onboarding, process!",
                "start_ms": 0,
                "end_ms": 5000,
            },
            {
                "content": "Budget review complete.",
                "start_ms": 5000,
                "end_ms": 10000,
            },
        ]

        highlights = [
            {
                "category": "insight",
                "title": "Customer onboarding",
                "description": "Important process for customer onboarding.",
            },
        ]

        resolved = resolve_highlight_timestamps(highlights, segments)
        assert resolved[0]["start_ms"] == 0
        assert resolved[0]["end_ms"] == 5000

    def test_punctuation_stripped_from_highlight_words(self):
        """Punctuation in highlight text should not prevent matching."""
        segments = [
            {
                "content": "The team discussed the quarterly review",
                "start_ms": 0,
                "end_ms": 5000,
            },
        ]

        highlights = [
            {
                "category": "topic_shift",
                "title": "Quarterly review!",
                "description": "Team's quarterly review, discussed.",
            },
        ]

        resolved = resolve_highlight_timestamps(highlights, segments)
        assert resolved[0]["start_ms"] == 0
        assert resolved[0]["end_ms"] == 5000

    def test_mixed_punctuation_and_case(self):
        """Mixed punctuation, quotes, and case should all be normalized."""
        segments = [
            {
                "content": 'He said: "Let\'s finalize the contract!"',
                "start_ms": 10000,
                "end_ms": 15000,
            },
            {
                "content": "Nothing relevant here.",
                "start_ms": 15000,
                "end_ms": 20000,
            },
        ]

        highlights = [
            {
                "category": "quote",
                "title": "Finalize the contract",
                "description": None,
            },
        ]

        resolved = resolve_highlight_timestamps(highlights, segments)
        assert resolved[0]["start_ms"] == 10000
        assert resolved[0]["end_ms"] == 15000

    def test_no_match_returns_no_timestamps(self):
        """When no words overlap, highlight should not get timestamps."""
        segments = [
            {
                "content": "Completely unrelated segment about weather.",
                "start_ms": 0,
                "end_ms": 5000,
            },
        ]

        highlights = [
            {
                "category": "decision",
                "title": "Budget approved",
                "description": "Financial decision",
            },
        ]

        resolved = resolve_highlight_timestamps(highlights, segments)
        assert "start_ms" not in resolved[0] or resolved[0].get("start_ms") is None

    def test_empty_segments_returns_highlights_unchanged(self):
        """Empty segments list should return highlights without timestamps."""
        highlights = [
            {"category": "decision", "title": "Test", "description": None},
        ]
        resolved = resolve_highlight_timestamps(highlights, [])
        assert resolved == highlights

    def test_empty_highlights_returns_empty(self):
        """Empty highlights list should return empty."""
        segments = [{"content": "Some content", "start_ms": 0, "end_ms": 5000}]
        resolved = resolve_highlight_timestamps([], segments)
        assert resolved == []


# ---------------------------------------------------------------------------
# 4. Summarizer highlights field present in result
# ---------------------------------------------------------------------------


class TestSummarizerHighlightsField:
    def test_summary_result_has_highlights_field(self):
        """SummaryResult dataclass should have highlights field."""
        from app.core.summarizer import SummaryResult

        result = SummaryResult(
            title="Test",
            summary="Test summary",
            key_points=[],
            decisions=[],
            action_items=[],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
            highlights=[{"category": "decision", "title": "Test"}],
        )
        assert result.highlights == [{"category": "decision", "title": "Test"}]

    def test_summary_result_defaults_highlights_to_none(self):
        """SummaryResult should default highlights to None if not provided."""
        from app.core.summarizer import SummaryResult

        result = SummaryResult(
            title="Test",
            summary="Test",
            key_points=[],
            decisions=[],
            action_items=[],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
        )
        assert result.highlights is None
