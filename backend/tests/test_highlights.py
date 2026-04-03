"""Tests for recording highlights / key moments feature."""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.summarizer as summarizer_module
from app.core.summarizer import SummaryResult, summarize_transcript
from app.models.highlight import Highlight
from app.models.recording import Segment


def _make_claude_response(text: str):
    """Create a mock Claude API response with the given text content."""
    mock_content_block = MagicMock()
    mock_content_block.text = text
    mock_message = MagicMock()
    mock_message.content = [mock_content_block]
    return mock_message


def _summary_result_with_highlights(highlights: list[dict]) -> SummaryResult:
    """Return a SummaryResult that includes a highlights list."""
    return SummaryResult(
        title="Highlights Test Meeting",
        summary="A meeting with key moments.",
        key_points=["Point 1"],
        decisions=[],
        action_items=[],
        topics=["testing"],
        people_mentioned=["Alice"],
        follow_up_questions=[],
        sentiment="neutral",
        highlights=highlights,
    )


SAMPLE_HIGHLIGHTS = [
    {
        "category": "decision",
        "title": "Approved Q2 budget",
        "description": "Team voted to approve the Q2 budget of $500k.",
        "speaker": "Alice",
        "importance": "high",
    },
    {
        "category": "insight",
        "title": "Customer churn is declining",
        "description": "Bob noted that customer churn dropped 15% this quarter.",
        "speaker": "Bob",
        "importance": "medium",
    },
    {
        "category": "question",
        "title": "When is the next board meeting?",
        "description": None,
        "speaker": None,
        "importance": "low",
    },
]


async def _create_recording(
    client: AsyncClient,
    headers: dict,
    title: str | None = "Test Recording",
) -> dict:
    response = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": title, "type": "meeting", "language": "en"},
    )
    assert response.status_code == 201
    return response.json()


# ---------------------------------------------------------------------------
# 1. Summarizer parses highlights from Claude's JSON response
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_settings():
    """Patch settings for summarizer tests."""
    with (
        patch.object(summarizer_module.settings, "anthropic_api_key", "sk-ant-test-key"),
        patch.object(summarizer_module.settings, "anthropic_model", "claude-sonnet-4-20250514"),
    ):
        yield


@pytest.mark.asyncio
async def test_highlight_extraction_from_summary():
    """summarize_transcript() should parse highlights from the Claude response."""
    response_data = {
        "title": "Budget Review",
        "summary": "The team reviewed the Q2 budget.",
        "key_points": ["Budget approved"],
        "decisions": [{"decision": "Approve budget", "context": "Q2"}],
        "action_items": [],
        "topics": ["budget"],
        "people_mentioned": ["Alice"],
        "follow_up_questions": [],
        "sentiment": "positive",
        "highlights": SAMPLE_HIGHLIGHTS,
    }

    mock_response = _make_claude_response(json.dumps(response_data))
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("app.core.summarizer._get_anthropic_client", return_value=mock_client):
        result = await summarize_transcript("Some transcript")

    assert hasattr(result, "highlights")
    assert len(result.highlights) == 3
    assert result.highlights[0]["category"] == "decision"
    assert result.highlights[0]["title"] == "Approved Q2 budget"
    assert result.highlights[1]["importance"] == "medium"
    assert result.highlights[2]["speaker"] is None


# ---------------------------------------------------------------------------
# 2. Timestamp resolution — map highlight text to segment timestamps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_highlight_timestamp_resolution():
    """resolve_highlight_timestamps() should map highlights to segment time ranges."""
    from app.core.summarizer import resolve_highlight_timestamps

    segments = [
        {"content": "Let's discuss the Q2 budget approval.", "start_ms": 0, "end_ms": 5000},
        {"content": "Customer churn dropped 15% this quarter.", "start_ms": 5000, "end_ms": 10000},
        {"content": "When is the next board meeting scheduled?",
         "start_ms": 10000, "end_ms": 15000},
    ]

    highlights = [
        {
            "category": "decision",
            "title": "Approved Q2 budget",
            "description": "Team voted to approve the Q2 budget of $500k.",
            "speaker": "Alice",
            "importance": "high",
        },
        {
            "category": "question",
            "title": "When is the next board meeting?",
            "description": None,
            "speaker": None,
            "importance": "low",
        },
    ]

    resolved = resolve_highlight_timestamps(highlights, segments)

    assert len(resolved) == 2
    # First highlight should map to the budget segment
    assert resolved[0]["start_ms"] == 0
    assert resolved[0]["end_ms"] == 5000
    # Second highlight should map to the board meeting segment
    assert resolved[1]["start_ms"] == 10000
    assert resolved[1]["end_ms"] == 15000


# ---------------------------------------------------------------------------
# 3. GET /recordings/{id} includes highlights in the detail response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_highlights_included_in_recording_detail(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """GET /recordings/{id} should return highlights in the detail response."""
    recording = await _create_recording(client, auth_headers)
    recording_id = UUID(recording["id"])

    db_session.add(Highlight(
        recording_id=recording_id,
        category="decision",
        title="Approved Q2 budget",
        description="Team voted to approve the Q2 budget.",
        speaker="Alice",
        start_ms=0,
        end_ms=5000,
        importance="high",
    ))
    db_session.add(Highlight(
        recording_id=recording_id,
        category="insight",
        title="Churn is declining",
        description=None,
        speaker="Bob",
        start_ms=5000,
        end_ms=10000,
        importance="medium",
    ))
    await db_session.flush()

    response = await client.get(f"/api/recordings/{recording_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    assert "highlights" in data
    assert len(data["highlights"]) == 2
    assert data["highlights"][0]["category"] == "decision"
    assert data["highlights"][0]["title"] == "Approved Q2 budget"
    assert data["highlights"][0]["start_ms"] == 0
    assert data["highlights"][1]["importance"] == "medium"


# ---------------------------------------------------------------------------
# 4. Re-summarize replaces old highlights
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_highlights_replaced_on_resummarize(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Regenerating a summary should replace previous highlights."""
    recording = await _create_recording(client, auth_headers, title="Highlight Regen")
    recording_id = UUID(recording["id"])

    db_session.add(Segment(
        recording_id=recording_id,
        speaker="Speaker 1",
        content="We decided to approve the Q2 budget.",
        start_ms=0,
        end_ms=5000,
        confidence=0.95,
    ))
    await db_session.flush()

    v1_highlights = [
        {"category": "decision", "title": "Old highlight", "description": None,
         "speaker": None, "importance": "medium"},
    ]

    async def summarize_v1(_: str, **kwargs) -> SummaryResult:
        return _summary_result_with_highlights(v1_highlights)

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", summarize_v1)
    first = await client.post(
        f"/api/recordings/{recording_id}/generate-summary", headers=auth_headers,
    )
    assert first.status_code == 200

    detail_v1 = await client.get(f"/api/recordings/{recording_id}", headers=auth_headers)
    assert len(detail_v1.json()["highlights"]) == 1
    assert detail_v1.json()["highlights"][0]["title"] == "Old highlight"

    v2_highlights = [
        {"category": "insight", "title": "New highlight A", "description": None,
         "speaker": None, "importance": "high"},
        {"category": "concern", "title": "New highlight B", "description": None,
         "speaker": None, "importance": "low"},
    ]

    async def summarize_v2(_: str, **kwargs) -> SummaryResult:
        return _summary_result_with_highlights(v2_highlights)

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", summarize_v2)
    second = await client.post(
        f"/api/recordings/{recording_id}/generate-summary", headers=auth_headers,
    )
    assert second.status_code == 200

    detail_v2 = await client.get(f"/api/recordings/{recording_id}", headers=auth_headers)
    highlights = detail_v2.json()["highlights"]
    assert len(highlights) == 2
    titles = {h["title"] for h in highlights}
    assert titles == {"New highlight A", "New highlight B"}


# ---------------------------------------------------------------------------
# 5. Empty highlights handled gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_highlights_handled(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Claude returning an empty highlights array should not crash."""
    recording = await _create_recording(client, auth_headers, title="No Highlights")
    recording_id = UUID(recording["id"])

    db_session.add(Segment(
        recording_id=recording_id,
        speaker="Speaker 1",
        content="A simple transcript with no special moments.",
        start_ms=0,
        end_ms=3000,
        confidence=0.9,
    ))
    await db_session.flush()

    async def summarize_empty(_: str, **kwargs) -> SummaryResult:
        return _summary_result_with_highlights([])

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", summarize_empty)
    response = await client.post(
        f"/api/recordings/{recording_id}/generate-summary", headers=auth_headers,
    )
    assert response.status_code == 200

    detail = await client.get(f"/api/recordings/{recording_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["highlights"] == []
