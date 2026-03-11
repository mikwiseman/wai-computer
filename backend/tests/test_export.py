"""Tests for recording export endpoint (markdown, txt, srt)."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.highlight import Highlight
from app.models.recording import Recording, Segment, Summary


async def _create_recording(
    client: AsyncClient,
    headers: dict,
    title: str | None = "Test Recording",
    type_: str = "note",
) -> dict:
    response = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": title, "type": type_, "language": "en"},
    )
    assert response.status_code == 201
    return response.json()


async def _create_recording_with_segments(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
    *,
    title: str = "Team Standup",
    type_: str = "meeting",
    duration_seconds: int = 930,
    add_summary: bool = False,
    add_highlights: bool = False,
) -> dict:
    """Create a recording with segments (and optionally summary/highlights) for export tests."""
    recording = await _create_recording(client, headers, title=title, type_=type_)
    recording_id = UUID(recording["id"])

    # Update duration on the model directly
    from sqlalchemy import select

    result = await db_session.execute(
        select(Recording).where(Recording.id == recording_id)
    )
    rec = result.scalar_one()
    rec.duration_seconds = duration_seconds

    db_session.add_all([
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Hello everyone, welcome to the standup.",
            start_ms=0,
            end_ms=15000,
            confidence=0.95,
        ),
        Segment(
            recording_id=recording_id,
            speaker="Speaker 2",
            content="Thanks for joining. Let's review the sprint.",
            start_ms=15000,
            end_ms=30000,
            confidence=0.92,
        ),
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="I finished the export feature yesterday.",
            start_ms=30000,
            end_ms=45000,
            confidence=0.97,
        ),
    ])

    if add_summary:
        db_session.add(Summary(
            recording_id=recording_id,
            summary="Team discussed sprint progress and the export feature.",
            key_points=["Export feature completed", "Sprint on track"],
            decisions=[{"decision": "Ship export this week", "context": "Sprint planning"}],
            topics=["sprint", "export"],
            people_mentioned=["Speaker 1", "Speaker 2"],
            sentiment="positive",
        ))

    if add_highlights:
        db_session.add_all([
            Highlight(
                recording_id=recording_id,
                category="decision",
                title="Budget approved for Q3",
                description=None,
                speaker="Speaker 1",
                start_ms=2500,
                end_ms=5000,
                importance="high",
            ),
            Highlight(
                recording_id=recording_id,
                category="insight",
                title="Customer retention up 15%",
                description=None,
                speaker="Speaker 2",
                start_ms=5400,
                end_ms=8000,
                importance="medium",
            ),
        ])

    await db_session.flush()
    return recording


# ---- Markdown export ----


@pytest.mark.asyncio
async def test_export_markdown_format(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Markdown export should include title, metadata, summary, highlights, and transcript."""
    recording = await _create_recording_with_segments(
        client, auth_headers, db_session,
        add_summary=True,
        add_highlights=True,
    )

    response = await client.get(
        f"/api/recordings/{recording['id']}/export",
        headers=auth_headers,
        params={"format": "markdown"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"

    body = response.text
    # Title
    assert "# Team Standup" in body
    # Metadata line with duration
    assert "15:30" in body
    assert "meeting" in body.lower()
    # Summary section
    assert "## Summary" in body
    assert "Team discussed sprint progress" in body
    # Highlights section
    assert "## Key Highlights" in body
    assert "**[Decision]**" in body
    assert "Budget approved for Q3" in body
    assert "**[Insight]**" in body
    assert "Customer retention up 15%" in body
    # Transcript section
    assert "## Transcript" in body
    assert "**Speaker 1**" in body
    assert "Hello everyone, welcome to the standup." in body
    assert "**Speaker 2**" in body
    assert "Thanks for joining." in body


@pytest.mark.asyncio
async def test_export_markdown_without_summary_or_highlights(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Markdown export should omit summary/highlights sections when not present."""
    recording = await _create_recording_with_segments(
        client, auth_headers, db_session,
        add_summary=False,
        add_highlights=False,
    )

    response = await client.get(
        f"/api/recordings/{recording['id']}/export",
        headers=auth_headers,
        params={"format": "markdown"},
    )
    assert response.status_code == 200
    body = response.text
    assert "# Team Standup" in body
    assert "## Summary" not in body
    assert "## Key Highlights" not in body
    assert "## Transcript" in body


# ---- Plain text export ----


@pytest.mark.asyncio
async def test_export_txt_format(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Plain text export should include title, date, duration, and bracketed speaker lines."""
    recording = await _create_recording_with_segments(
        client, auth_headers, db_session,
    )

    response = await client.get(
        f"/api/recordings/{recording['id']}/export",
        headers=auth_headers,
        params={"format": "txt"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"

    body = response.text
    assert "Team Standup" in body
    assert "15:30" in body
    assert "[Speaker 1, 0:00]" in body
    assert "Hello everyone, welcome to the standup." in body
    assert "[Speaker 2, 0:15]" in body
    assert "Thanks for joining." in body


# ---- SRT subtitle export ----


@pytest.mark.asyncio
async def test_export_srt_format(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """SRT export should have numbered entries with HH:MM:SS,mmm timestamps."""
    recording = await _create_recording_with_segments(
        client, auth_headers, db_session,
    )

    response = await client.get(
        f"/api/recordings/{recording['id']}/export",
        headers=auth_headers,
        params={"format": "srt"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/srt; charset=utf-8"

    body = response.text
    # Entry 1
    assert "1\n" in body
    assert "00:00:00,000 --> 00:00:15,000" in body
    assert "[Speaker 1] Hello everyone" in body
    # Entry 2
    assert "2\n" in body
    assert "00:00:15,000 --> 00:00:30,000" in body
    assert "[Speaker 2] Thanks for joining" in body
    # Entry 3
    assert "3\n" in body
    assert "00:00:30,000 --> 00:00:45,000" in body


# ---- Error cases ----


@pytest.mark.asyncio
async def test_export_invalid_format_returns_422(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Invalid format parameter should return 422."""
    recording = await _create_recording_with_segments(
        client, auth_headers, db_session,
    )

    response = await client.get(
        f"/api/recordings/{recording['id']}/export",
        headers=auth_headers,
        params={"format": "pdf"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_export_nonexistent_recording_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Export of a nonexistent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(
        f"/api/recordings/{fake_id}/export",
        headers=auth_headers,
        params={"format": "markdown"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_export_auth_required(client: AsyncClient):
    """Export without auth should return 401."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(
        f"/api/recordings/{fake_id}/export",
        params={"format": "markdown"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_export_no_segments_exports_gracefully(
    client: AsyncClient,
    auth_headers: dict,
):
    """A recording with no transcript should export without errors."""
    recording = await _create_recording(client, auth_headers, title="Empty Recording")

    response = await client.get(
        f"/api/recordings/{recording['id']}/export",
        headers=auth_headers,
        params={"format": "markdown"},
    )
    assert response.status_code == 200
    body = response.text
    assert "# Empty Recording" in body
    assert "## Transcript" in body

    # Also check txt
    response_txt = await client.get(
        f"/api/recordings/{recording['id']}/export",
        headers=auth_headers,
        params={"format": "txt"},
    )
    assert response_txt.status_code == 200
    assert "Empty Recording" in response_txt.text

    # Also check srt — should be valid but empty
    response_srt = await client.get(
        f"/api/recordings/{recording['id']}/export",
        headers=auth_headers,
        params={"format": "srt"},
    )
    assert response_srt.status_code == 200
    # SRT with no segments is just empty or whitespace
    assert response_srt.text.strip() == ""


@pytest.mark.asyncio
async def test_export_content_disposition_header(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Export response should include Content-Disposition with a filename."""
    recording = await _create_recording_with_segments(
        client, auth_headers, db_session,
    )

    for fmt, ext in [("markdown", "md"), ("txt", "txt"), ("srt", "srt")]:
        response = await client.get(
            f"/api/recordings/{recording['id']}/export",
            headers=auth_headers,
            params={"format": fmt},
        )
        assert response.status_code == 200
        disposition = response.headers.get("content-disposition", "")
        assert "attachment" in disposition
        assert f".{ext}" in disposition


# ---- Edge cases ----


@pytest.mark.asyncio
async def test_export_null_speaker_and_null_timestamp(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Segments with null speaker or null timestamps should export without errors."""
    recording = await _create_recording(client, auth_headers, title="Null Fields")
    recording_id = UUID(recording["id"])

    db_session.add_all([
        Segment(
            recording_id=recording_id,
            speaker=None,
            content="Unknown speaker segment.",
            start_ms=None,
            end_ms=None,
            confidence=None,
        ),
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Known speaker, no timestamp.",
            start_ms=None,
            end_ms=None,
            confidence=0.9,
        ),
    ])
    await db_session.flush()

    # Markdown
    response = await client.get(
        f"/api/recordings/{recording['id']}/export",
        headers=auth_headers,
        params={"format": "markdown"},
    )
    assert response.status_code == 200
    assert "Unknown speaker segment." in response.text

    # TXT
    response_txt = await client.get(
        f"/api/recordings/{recording['id']}/export",
        headers=auth_headers,
        params={"format": "txt"},
    )
    assert response_txt.status_code == 200
    assert "Unknown speaker segment." in response_txt.text

    # SRT
    response_srt = await client.get(
        f"/api/recordings/{recording['id']}/export",
        headers=auth_headers,
        params={"format": "srt"},
    )
    assert response_srt.status_code == 200
    assert "Unknown speaker segment." in response_srt.text
