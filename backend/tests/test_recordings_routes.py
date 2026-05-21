"""Tests for recording endpoints and summary generation flows."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import MissingGreenlet
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.summarizer import SummaryResult
from app.core.transcript_utils import TranscriptResult
from app.models.recording import ActionItem, Recording, RecordingShare, Segment, Summary
from app.models.user import User


async def _create_recording(
    client: AsyncClient,
    headers: dict,
    title: str | None = "Test Recording",
    type_: str = "note",
    language: str = "en",
) -> dict:
    response = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": title, "type": type_, "language": language},
    )
    assert response.status_code == 201
    return response.json()


async def _register_headers(client: AsyncClient, email: str) -> dict:
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "testpassword123"},
    )
    assert response.status_code == 200
    data = response.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


@pytest.mark.asyncio
async def test_create_recording_invalid_type_returns_422(client: AsyncClient, auth_headers: dict):
    """Recording type should be constrained to supported values."""
    response = await client.post(
        "/api/recordings",
        headers=auth_headers,
        json={"title": "Bad", "type": "invalid_type"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_recordings_can_filter_by_type(client: AsyncClient, auth_headers: dict):
    """List endpoint should filter recordings by type."""
    await _create_recording(client, auth_headers, title="Meeting A", type_="meeting")
    await _create_recording(client, auth_headers, title="Note A", type_="note")

    meeting_response = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"type": "meeting"},
    )
    assert meeting_response.status_code == 200
    meetings = meeting_response.json()
    assert len(meetings) == 1
    assert meetings[0]["type"] == "meeting"


@pytest.mark.asyncio
async def test_delete_recording_moves_to_trash_and_can_be_restored(
    client: AsyncClient,
    auth_headers: dict,
):
    """Delete should soft-delete into trash until explicitly restored or removed."""
    recording = await _create_recording(client, auth_headers, title="Trash Me")

    delete_response = await client.delete(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
    )
    assert delete_response.status_code == 204

    active_response = await client.get("/api/recordings", headers=auth_headers)
    assert active_response.status_code == 200
    assert active_response.json() == []

    trashed_response = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"trashed": "true"},
    )
    assert trashed_response.status_code == 200
    assert [item["id"] for item in trashed_response.json()] == [recording["id"]]
    assert trashed_response.json()[0]["deleted_at"] is not None

    restore_response = await client.post(
        f"/api/recordings/{recording['id']}/restore",
        headers=auth_headers,
    )
    assert restore_response.status_code == 200
    assert restore_response.json()["deleted_at"] is None

    restored_response = await client.get("/api/recordings", headers=auth_headers)
    assert restored_response.status_code == 200
    assert [item["id"] for item in restored_response.json()] == [recording["id"]]


@pytest.mark.asyncio
async def test_delete_recording_can_permanently_delete_from_trash(
    client: AsyncClient,
    auth_headers: dict,
):
    """A trashed recording should be removable permanently."""
    recording = await _create_recording(client, auth_headers, title="Permanent Delete")

    first_delete = await client.delete(f"/api/recordings/{recording['id']}", headers=auth_headers)
    assert first_delete.status_code == 204

    second_delete = await client.delete(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
        params={"permanent": "true"},
    )
    assert second_delete.status_code == 204

    detail_response = await client.get(f"/api/recordings/{recording['id']}", headers=auth_headers)
    assert detail_response.status_code == 404


@pytest.mark.asyncio
async def test_create_share_link_returns_public_web_url_and_token_is_hashed(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Share creation should return a public web URL without storing the raw token."""
    recording = await _create_recording(client, auth_headers, title="Shared Standup")

    response = await client.post(
        f"/api/recordings/{recording['id']}/share",
        headers=auth_headers,
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["recording_id"] == recording["id"]
    assert payload["token"]
    assert payload["url"].endswith(f"/share/{payload['token']}")

    share_result = await db_session.execute(select(RecordingShare))
    share = share_result.scalar_one()
    assert share.recording_id == UUID(recording["id"])
    assert share.token_hash != payload["token"]
    assert len(share.token_hash) == 64


@pytest.mark.asyncio
async def test_public_share_link_opens_recording_without_auth(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """A valid share token should expose a read-only note payload without auth."""
    recording = await _create_recording(client, auth_headers, title="Public Planning")
    recording_id = UUID(recording["id"])

    result = await db_session.execute(select(Recording).where(Recording.id == recording_id))
    stored_recording = result.scalar_one()
    stored_recording.duration_seconds = 125

    db_session.add_all(
        [
            Segment(
                recording_id=recording_id,
                speaker="Mik",
                content="Ship the public share page.",
                start_ms=0,
                end_ms=5000,
                confidence=0.96,
            ),
            Summary(
                recording_id=recording_id,
                summary="Public sharing was discussed.",
                key_points=["Open shared notes in web"],
                decisions=[],
                topics=["sharing"],
                people_mentioned=["Mik"],
                sentiment="positive",
            ),
            ActionItem(
                recording_id=recording_id,
                task="Add a share button",
                owner="Mik",
                priority="high",
                status="pending",
                source="generated",
            ),
        ]
    )
    await db_session.flush()

    share_response = await client.post(
        f"/api/recordings/{recording['id']}/share",
        headers=auth_headers,
    )
    token = share_response.json()["token"]

    public_response = await client.get(f"/api/recordings/shared/{token}")

    assert public_response.status_code == 200
    payload = public_response.json()
    assert payload["id"] == recording["id"]
    assert payload["title"] == "Public Planning"
    assert payload["duration_seconds"] == 125
    assert payload["summary"]["summary"] == "Public sharing was discussed."
    assert payload["segments"][0]["content"] == "Ship the public share page."
    assert payload["action_items"][0]["task"] == "Add a share button"
    assert "audio_url" not in payload


@pytest.mark.asyncio
async def test_public_share_link_exports_markdown_without_auth(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """A shared note should download the same Markdown format without auth."""
    recording = await _create_recording(client, auth_headers, title="Public Export")
    recording_id = UUID(recording["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Mik",
            content="Download the shared note as Markdown.",
            start_ms=0,
            end_ms=4000,
            confidence=0.97,
        )
    )
    await db_session.flush()

    share_response = await client.post(
        f"/api/recordings/{recording['id']}/share",
        headers=auth_headers,
    )
    token = share_response.json()["token"]

    export_response = await client.get(
        f"/api/recordings/shared/{token}/export",
        params={"format": "markdown"},
    )

    assert export_response.status_code == 200
    assert "text/markdown" in export_response.headers["content-type"]
    assert "Public_Export.md" in export_response.headers["content-disposition"]
    assert "# Public Export" in export_response.text
    assert "Download the shared note as Markdown." in export_response.text


@pytest.mark.asyncio
async def test_public_share_link_404s_after_recording_is_trashed(
    client: AsyncClient,
    auth_headers: dict,
):
    """Public links should stop opening once the source recording leaves the active library."""
    recording = await _create_recording(client, auth_headers, title="Temporary Share")
    share_response = await client.post(
        f"/api/recordings/{recording['id']}/share",
        headers=auth_headers,
    )
    token = share_response.json()["token"]

    delete_response = await client.delete(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
    )
    assert delete_response.status_code == 204

    public_response = await client.get(f"/api/recordings/shared/{token}")
    assert public_response.status_code == 404


@pytest.mark.asyncio
async def test_share_link_requires_recording_ownership(
    client: AsyncClient,
    auth_headers: dict,
):
    """Users must not be able to create share links for another user's recording."""
    recording = await _create_recording(client, auth_headers, title="Private")
    other_headers = await _register_headers(client, "other-share@example.com")

    response = await client.post(
        f"/api/recordings/{recording['id']}/share",
        headers=other_headers,
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_recordings_rejects_negative_skip(client: AsyncClient, auth_headers: dict):
    """Skip should not allow negative values."""
    response = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"skip": -1},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_recording_transcript_is_sorted_by_start_ms(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Transcript endpoint should return segments ordered by start timestamp."""
    recording = await _create_recording(client, auth_headers)
    recording_id = UUID(recording["id"])

    db_session.add_all(
        [
            Segment(
                recording_id=recording_id,
                speaker="Speaker 1",
                content="Second",
                start_ms=2000,
                end_ms=2500,
                confidence=0.9,
            ),
            Segment(
                recording_id=recording_id,
                speaker="Speaker 1",
                content="First",
                start_ms=500,
                end_ms=1000,
                confidence=0.95,
            ),
        ]
    )
    await db_session.flush()

    response = await client.get(f"/api/recordings/{recording_id}/transcript", headers=auth_headers)
    assert response.status_code == 200
    contents = [segment["content"] for segment in response.json()]
    assert contents == ["First", "Second"]


@pytest.mark.asyncio
async def test_get_summary_returns_404_when_not_generated(client: AsyncClient, auth_headers: dict):
    """Summary endpoint should return 404 until generated."""
    recording = await _create_recording(client, auth_headers)

    response = await client.get(f"/api/recordings/{recording['id']}/summary", headers=auth_headers)
    assert response.status_code == 404
    assert "not generated" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_generate_summary_requires_segments(client: AsyncClient, auth_headers: dict):
    """Generate summary should reject recordings without transcript segments."""
    recording = await _create_recording(client, auth_headers)
    response = await client.post(
        f"/api/recordings/{recording['id']}/generate-summary",
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "no transcript segments" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_generate_summary_returns_friendly_503_when_summarizer_fails(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Generate summary should return a friendly error when summarization fails."""
    recording = await _create_recording(client, auth_headers)
    recording_id = UUID(recording["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Summarize this transcript please.",
            start_ms=0,
            end_ms=1000,
            confidence=0.99,
        )
    )
    await db_session.flush()

    async def broken_summarizer(_: str, **kwargs) -> SummaryResult:
        raise RuntimeError("llm gateway timeout")

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", broken_summarizer)

    response = await client.post(
        f"/api/recordings/{recording_id}/generate-summary",
        headers=auth_headers,
    )
    assert response.status_code == 503
    assert response.json()["detail"] == (
        "We couldn't generate the summary right now. Please try again in a moment."
    )


@pytest.mark.asyncio
async def test_generate_summary_creates_summary_and_action_items(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Generate summary should populate summary and action items with sanitized values."""
    recording = await _create_recording(client, auth_headers, title=None)
    recording_id = UUID(recording["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Ship the roadmap update by Friday.",
            start_ms=0,
            end_ms=1200,
            confidence=0.98,
        )
    )
    await db_session.flush()

    async def fake_summarize_transcript(_: str, **kwargs) -> SummaryResult:
        return SummaryResult(
            title="Roadmap Review",
            summary="Team reviewed roadmap and agreed next steps.",
            key_points=["Roadmap approved"],
            decisions=[{"decision": "Ship roadmap update", "context": "Sprint planning"}],
            action_items=[
                {
                    "task": "Prepare customer update",
                    "owner": "Alex",
                    "due": "2026-03-01",
                    "priority": "high",
                },
                {
                    "task": "Handle malformed due date",
                    "owner": "Sam",
                    "due": "not-a-date",
                    "priority": "unknown-priority",
                },
                {"task": "   ", "owner": "Nobody", "due": None, "priority": "low"},
            ],
            topics=["roadmap"],
            people_mentioned=["Alex", "Sam"],
            follow_up_questions=[],
            sentiment="positive",
        )

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", fake_summarize_transcript)

    response = await client.post(
        f"/api/recordings/{recording_id}/generate-summary",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["summary"]

    detail_response = await client.get(f"/api/recordings/{recording_id}", headers=auth_headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["title"] == "Roadmap Review"
    assert len(detail["action_items"]) == 2
    assert {item["priority"] for item in detail["action_items"]} == {"high", "medium"}


@pytest.mark.asyncio
async def test_generate_summary_defaults_to_recording_language(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """When summary_language is auto, use the explicit recording language."""
    recording = await _create_recording(client, auth_headers, title="Russian Note", language="ru")
    recording_id = UUID(recording["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Обсудили план запуска и следующие шаги.",
            start_ms=0,
            end_ms=1000,
            confidence=0.95,
        )
    )
    await db_session.flush()

    captured: dict[str, str | None] = {}

    async def fake_summarize_transcript(_: str, **kwargs) -> SummaryResult:
        captured["language"] = kwargs.get("language")
        captured["style"] = kwargs.get("style")
        return SummaryResult(
            title="План запуска",
            summary="Краткая сводка.",
            key_points=[],
            decisions=[],
            action_items=[],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
        )

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", fake_summarize_transcript)

    response = await client.post(
        f"/api/recordings/{recording_id}/generate-summary",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert captured["language"] == "ru"
    assert captured["style"] == "medium"


@pytest.mark.asyncio
async def test_generate_summary_auto_language_persists_russian_title(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Russian transcript + auto preference should let the Russian title persist."""
    recording = await _create_recording(client, auth_headers, title=None, language="ru")
    recording_id = UUID(recording["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Обсудили план запуска и следующие шаги.",
            start_ms=0,
            end_ms=1000,
            confidence=0.95,
        )
    )
    await db_session.flush()

    captured: dict[str, str | None] = {}

    async def fake_summarize_transcript(_: str, **kwargs) -> SummaryResult:
        captured["language"] = kwargs.get("language")
        return SummaryResult(
            title="План запуска",
            summary="Краткое резюме на русском.",
            key_points=["Запуск согласован"],
            decisions=[],
            action_items=[],
            topics=["запуск"],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
        )

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", fake_summarize_transcript)

    response = await client.post(
        f"/api/recordings/{recording_id}/generate-summary",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert captured["language"] == "ru"

    detail_response = await client.get(f"/api/recordings/{recording_id}", headers=auth_headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["title"] == "План запуска"
    assert detail["summary"]["summary"] == "Краткое резюме на русском."


@pytest.mark.asyncio
async def test_generate_summary_preserves_custom_style_for_auto_language(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Auto language should still respect a user-selected summary style."""
    user = (await db_session.execute(select(User))).scalar_one()
    user.summary_style = "brief"
    user.summary_language = "auto"
    await db_session.flush()

    recording = await _create_recording(client, auth_headers, title="Mixed Note", language="multi")
    recording_id = UUID(recording["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Сегодня обсуждали релиз и blockers.",
            start_ms=0,
            end_ms=1000,
            confidence=0.95,
        )
    )
    await db_session.flush()

    captured: dict[str, str | None] = {}

    async def fake_summarize_transcript(_: str, **kwargs) -> SummaryResult:
        captured["language"] = kwargs.get("language")
        captured["style"] = kwargs.get("style")
        return SummaryResult(
            title="Release blockers",
            summary="Short summary.",
            key_points=[],
            decisions=[],
            action_items=[],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
        )

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", fake_summarize_transcript)

    response = await client.post(
        f"/api/recordings/{recording_id}/generate-summary",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert captured["language"] == "auto"
    assert captured["style"] == "brief"


@pytest.mark.asyncio
async def test_generate_summary_auto_language_uses_user_default_for_multilingual_recording(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """language=multi should not make Russian users get English titles/summaries."""
    user = (await db_session.execute(select(User))).scalar_one()
    user.default_language = "ru"
    user.summary_language = "auto"
    await db_session.flush()

    recording = await _create_recording(client, auth_headers, title=None, language="multi")
    recording_id = UUID(recording["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Q2 roadmap and budget were discussed.",
            start_ms=0,
            end_ms=1000,
            confidence=0.95,
        )
    )
    await db_session.flush()

    captured: dict[str, str | None] = {}

    async def fake_summarize_transcript(_: str, **kwargs) -> SummaryResult:
        captured["language"] = kwargs.get("language")
        return SummaryResult(
            title="План Q2",
            summary="Сводка на русском.",
            key_points=[],
            decisions=[],
            action_items=[],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
        )

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", fake_summarize_transcript)

    response = await client.post(
        f"/api/recordings/{recording_id}/generate-summary",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert captured["language"] == "ru"


@pytest.mark.asyncio
async def test_generate_summary_regeneration_replaces_action_items(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Regeneration should replace old generated action items instead of duplicating them."""
    recording = await _create_recording(client, auth_headers, title="Retrospective")
    recording_id = UUID(recording["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Action items changed after discussion.",
            start_ms=0,
            end_ms=900,
            confidence=0.92,
        )
    )
    await db_session.flush()

    async def summarize_v1(_: str, **kwargs) -> SummaryResult:
        return SummaryResult(
            title="Retrospective V1",
            summary="First summary.",
            key_points=[],
            decisions=[],
            action_items=[{"task": "Old task", "owner": None, "due": None, "priority": "medium"}],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
        )

    async def summarize_v2(_: str, **kwargs) -> SummaryResult:
        return SummaryResult(
            title="Retrospective V2",
            summary="Second summary.",
            key_points=[],
            decisions=[],
            action_items=[{"task": "New task", "owner": None, "due": None, "priority": "high"}],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
        )

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", summarize_v1)
    first = await client.post(
        f"/api/recordings/{recording_id}/generate-summary",
        headers=auth_headers,
    )
    assert first.status_code == 200

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", summarize_v2)
    second = await client.post(
        f"/api/recordings/{recording_id}/generate-summary",
        headers=auth_headers,
    )
    assert second.status_code == 200

    detail_response = await client.get(f"/api/recordings/{recording_id}", headers=auth_headers)
    detail = detail_response.json()
    assert len(detail["action_items"]) == 1
    assert detail["action_items"][0]["task"] == "New task"


@pytest.mark.asyncio
async def test_generate_summary_preserves_manual_action_items(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Regeneration should only replace generated action items, preserving manual ones."""
    recording = await _create_recording(client, auth_headers, title="Manual Preservation")
    recording_id = UUID(recording["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Discuss tasks.",
            start_ms=0,
            end_ms=900,
            confidence=0.92,
        )
    )
    db_session.add(
        ActionItem(
            recording_id=recording_id,
            task="Manual task",
            owner="Taylor",
            priority="low",
            source="manual",
        )
    )
    await db_session.flush()

    async def summarize(_: str, **kwargs) -> SummaryResult:
        return SummaryResult(
            title="Manual Preservation",
            summary="Summary.",
            key_points=[],
            decisions=[],
            action_items=[{
                "task": "Generated task", "owner": None,
                "due": None, "priority": "medium",
            }],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
        )

    monkeypatch.setattr("app.api.routes.recordings.summarize_transcript", summarize)
    response = await client.post(
        f"/api/recordings/{recording_id}/generate-summary",
        headers=auth_headers,
    )
    assert response.status_code == 200

    detail_response = await client.get(f"/api/recordings/{recording_id}", headers=auth_headers)
    detail = detail_response.json()
    tasks = sorted(item["task"] for item in detail["action_items"])
    assert tasks == ["Generated task", "Manual task"]


# ---- Upload endpoint tests ----


@pytest.mark.asyncio
async def test_upload_nonexistent_recording_returns_404(client: AsyncClient, auth_headers: dict):
    """Upload to a nonexistent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.post(
        f"/api/recordings/{fake_id}/upload",
        headers=auth_headers,
        files={"file": ("test.mp3", b"fake-audio", "audio/mpeg")},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_upload_unsupported_file_type_returns_415(client: AsyncClient, auth_headers: dict):
    """Upload with unsupported file extension should return 415."""
    recording = await _create_recording(client, auth_headers)
    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("test.txt", b"not-audio", "text/plain")},
    )
    assert response.status_code == 415
    assert "Unsupported file type" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_accepts_audio_content_type_without_extension(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Upload should accept a valid audio MIME type even when the filename has no extension."""
    recording = await _create_recording(client, auth_headers, title=None)

    fake_transcripts = [
        TranscriptResult(
            text="Recovered from MIME type",
            speaker="Speaker 0",
            is_final=True,
            start_ms=0,
            end_ms=1000,
            confidence=0.95,
        )
    ]

    async def fake_transcribe_audio_file(
        audio_data: bytes,
        language: str,
        content_type: str = "audio/mpeg",
        **kwargs,
    ) -> list[TranscriptResult]:
        assert audio_data == b"fake-audio"
        assert content_type == "audio/mpeg"
        return fake_transcripts

    async def fake_generate_title(text: str, **kwargs) -> str:
        return "Recovered from MIME"

    monkeypatch.setattr(
        "app.api.routes.recordings.transcribe_audio_file",
        fake_transcribe_audio_file,
    )
    monkeypatch.setattr("app.api.routes.recordings.generate_title", fake_generate_title)
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=None),
    )

    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("upload", b"fake-audio", "audio/mpeg")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["title"] == "Recovered from MIME"
    assert payload["segments"][0]["content"] == "Recovered from MIME type"


@pytest.mark.asyncio
async def test_upload_no_speech_fallback_uses_russian_recording_language(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Noise/no-speech provider placeholders should not create English UI copy."""
    recording = await _create_recording(client, auth_headers, title=None, language="ru")

    monkeypatch.setattr(
        "app.api.routes.recordings.transcribe_audio_file",
        AsyncMock(
            return_value=[
                TranscriptResult(
                    text="[noise]",
                    speaker=None,
                    is_final=True,
                    start_ms=0,
                    end_ms=1200,
                    confidence=0.1,
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=None),
    )
    title_mock = AsyncMock(return_value="No Speech Detected")
    monkeypatch.setattr("app.api.routes.recordings.generate_title", title_mock)

    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("noise.wav", b"noise", "audio/wav")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["segments"] == []
    assert data["title"] == "Без речи"
    assert data["failure_message"] == "Мы не обнаружили разборчивой речи в этой записи."
    title_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_no_speech_fallback_uses_user_default_for_multilingual_recording(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    user = (await db_session.execute(select(User))).scalar_one()
    user.default_language = "ru"
    await db_session.flush()
    recording = await _create_recording(client, auth_headers, title=None, language="multi")

    monkeypatch.setattr(
        "app.api.routes.recordings.transcribe_audio_file",
        AsyncMock(
            return_value=[
                TranscriptResult(
                    text="[noise]",
                    speaker=None,
                    is_final=True,
                    start_ms=0,
                    end_ms=1200,
                    confidence=0.1,
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=None),
    )

    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("noise.wav", b"noise", "audio/wav")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["segments"] == []
    assert data["title"] == "Без речи"
    assert data["failure_message"] == "Мы не обнаружили разборчивой речи в этой записи."


@pytest.mark.asyncio
async def test_upload_no_speech_fallback_stays_english_for_english_recordings(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    recording = await _create_recording(client, auth_headers, title=None, language="en")

    monkeypatch.setattr(
        "app.api.routes.recordings.transcribe_audio_file",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=None),
    )

    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("silence.wav", b"silence", "audio/wav")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["segments"] == []
    assert data["title"] == "No speech detected"
    assert data["failure_message"] == "We could not detect clear speech in this recording."


@pytest.mark.asyncio
async def test_upload_success_with_mocked_services(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Successful upload should transcribe and return recording detail."""
    recording = await _create_recording(client, auth_headers, title=None)

    fake_transcripts = [
        TranscriptResult(
            text="Hello world",
            speaker="Speaker 0",
            is_final=True,
            start_ms=0,
            end_ms=1500,
            confidence=0.98,
        ),
    ]

    transcribe_audio = AsyncMock(return_value=fake_transcripts)
    monkeypatch.setattr(
        "app.api.routes.recordings.transcribe_audio_file",
        transcribe_audio,
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Hello World Meeting"),
    )

    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("meeting.mp3", b"fake-mp3-data", "audio/mpeg")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Hello World Meeting"
    assert data["audio_url"] is None
    assert data["uploaded_at"] is not None
    assert data["status"] == "ready"
    assert data["duration_seconds"] == 1
    assert len(data["segments"]) == 1
    assert data["segments"][0]["content"] == "Hello world"
    transcribe_audio.assert_awaited_once()
    _, transcribe_kwargs = transcribe_audio.await_args
    assert "provider" not in transcribe_kwargs
    assert "model" not in transcribe_kwargs
    assert "user" not in transcribe_kwargs


@pytest.mark.asyncio
async def test_live_transcript_cannot_overwrite_uploaded_audio_transcript(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Once uploaded audio is processed, realtime transcript saves are not canonical."""
    recording = await _create_recording(client, auth_headers, title=None)

    audio_transcripts = [
        TranscriptResult(
            text="Audio transcript opening",
            speaker="Speaker 0",
            is_final=True,
            start_ms=0,
            end_ms=1500,
            confidence=0.98,
        ),
        TranscriptResult(
            text="Audio transcript ending",
            speaker="Speaker 1",
            is_final=True,
            start_ms=5000,
            end_ms=9000,
            confidence=0.97,
        ),
    ]

    monkeypatch.setattr(
        "app.api.routes.recordings.transcribe_audio_file",
        AsyncMock(return_value=audio_transcripts),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Audio Canonical"),
    )

    upload_response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("recording.wav", b"fake-wav-data", "audio/wav")},
    )
    assert upload_response.status_code == 200
    assert [segment["content"] for segment in upload_response.json()["segments"]] == [
        "Audio transcript opening",
        "Audio transcript ending",
    ]

    stale_live_response = await client.post(
        f"/api/recordings/{recording['id']}/transcript",
        headers=auth_headers,
        json={
            "duration_seconds": 55 * 60,
            "segments": [
                {
                    "text": "Realtime transcript with gaps",
                    "speaker": "Speaker 1",
                    "start_ms": 0,
                    "end_ms": 55 * 60 * 1000,
                    "confidence": 0.42,
                }
            ],
        },
    )

    assert stale_live_response.status_code == 200
    data = stale_live_response.json()
    assert data["status"] == "ready"
    assert data["duration_seconds"] == 9
    assert [segment["content"] for segment in data["segments"]] == [
        "Audio transcript opening",
        "Audio transcript ending",
    ]


@pytest.mark.asyncio
async def test_duplicate_audio_upload_cannot_overwrite_ready_audio_transcript(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Background retries must not replace an already-ready audio transcript."""
    recording = await _create_recording(client, auth_headers, title=None)
    first_transcripts = [
        TranscriptResult(
            text="Full canonical transcript",
            speaker="Speaker 0",
            is_final=True,
            start_ms=0,
            end_ms=55 * 60 * 1000,
            confidence=0.98,
        )
    ]
    second_transcripts = [
        TranscriptResult(
            text="Short stale retry transcript",
            speaker="Speaker 0",
            is_final=True,
            start_ms=0,
            end_ms=27 * 60 * 1000,
            confidence=0.72,
        )
    ]
    transcribe_mock = AsyncMock(side_effect=[first_transcripts, second_transcripts])

    monkeypatch.setattr("app.api.routes.recordings.transcribe_audio_file", transcribe_mock)
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Full Canonical"),
    )

    first_upload = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("recording.wav", b"full-audio", "audio/wav")},
    )
    assert first_upload.status_code == 200
    assert first_upload.json()["duration_seconds"] == 55 * 60

    duplicate_upload = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("recording.wav", b"stale-partial-audio", "audio/wav")},
    )

    assert duplicate_upload.status_code == 200
    data = duplicate_upload.json()
    assert data["duration_seconds"] == 55 * 60
    assert [segment["content"] for segment in data["segments"]] == [
        "Full canonical transcript"
    ]
    assert transcribe_mock.await_count == 1


@pytest.mark.asyncio
async def test_upload_too_large_marks_recording_failed_and_keeps_it_visible(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Oversized upload should fail explicitly without hiding the recording."""
    recording = await _create_recording(client, auth_headers)
    monkeypatch.setattr("app.api.routes.recordings.MAX_UPLOAD_SIZE", 4)

    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("large.mp3", b"12345", "audio/mpeg")},
    )
    assert response.status_code == 413
    assert "Maximum size" in response.json()["detail"]

    detail_response = await client.get(f"/api/recordings/{recording['id']}", headers=auth_headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["status"] == "failed"
    assert detail["failure_code"] == "file_too_large"
    assert detail["audio_url"] is None

    list_response = await client.get("/api/recordings", headers=auth_headers)
    assert list_response.status_code == 200
    items = {item["id"]: item for item in list_response.json()}
    assert items[recording["id"]]["status"] == "failed"


@pytest.mark.asyncio
async def test_save_transcript_persists_segments_before_audio_upload(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Live transcript segments should be savable before durable audio completes."""
    recording = await _create_recording(client, auth_headers, title=None)

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Transcript First"),
    )

    response = await client.post(
        f"/api/recordings/{recording['id']}/transcript",
        headers=auth_headers,
        json={
            "duration_seconds": 3,
            "segments": [
                {
                    "text": "Transcript saved first",
                    "speaker": "Speaker 1",
                    "start_ms": 0,
                    "end_ms": 2400,
                    "confidence": 0.93,
                }
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["title"] == "Transcript First"
    assert data["duration_seconds"] == 2
    assert [segment["content"] for segment in data["segments"]] == ["Transcript saved first"]


@pytest.mark.asyncio
async def test_save_transcript_accepts_empty_payload_without_erasing_existing_segments(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Empty transcript saves should complete cleanly without erasing existing content."""
    recording = await _create_recording(client, auth_headers, title=None)

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )

    first_response = await client.post(
        f"/api/recordings/{recording['id']}/transcript",
        headers=auth_headers,
        json={
            "duration_seconds": 3,
            "segments": [
                {
                    "text": "Keep this transcript",
                    "speaker": "Speaker 1",
                    "start_ms": 0,
                    "end_ms": 2000,
                    "confidence": 0.93,
                }
            ],
        },
    )
    assert first_response.status_code == 200

    empty_response = await client.post(
        f"/api/recordings/{recording['id']}/transcript",
        headers=auth_headers,
        json={
            "duration_seconds": 3,
            "segments": [
                {
                    "text": "   ",
                    "speaker": "Speaker 1",
                    "start_ms": 0,
                    "end_ms": 2000,
                    "confidence": 0.93,
                }
            ],
        },
    )
    assert empty_response.status_code == 200
    assert empty_response.json()["status"] == "ready"
    assert [segment["content"] for segment in empty_response.json()["segments"]] == [
        "Keep this transcript"
    ]

    detail_response = await client.get(f"/api/recordings/{recording['id']}", headers=auth_headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert [segment["content"] for segment in detail["segments"]] == [
        "Keep this transcript"
    ]
    assert detail["status"] == "ready"
    assert detail["failure_code"] is None
    assert detail["failure_message"] is None


@pytest.mark.asyncio
async def test_save_transcript_marks_recording_failed_when_server_processing_crashes(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    recording = await _create_recording(client, auth_headers, title=None)
    await db_session.commit()

    monkeypatch.setattr(
        "app.api.routes.recordings._reset_recording_processing_state",
        AsyncMock(side_effect=RuntimeError("database exploded")),
    )

    response = await client.post(
        f"/api/recordings/{recording['id']}/transcript",
        headers=auth_headers,
        json={
            "duration_seconds": 3,
            "segments": [
                {
                    "text": "Keep this transcript",
                    "speaker": "Speaker 1",
                    "start_ms": 0,
                    "end_ms": 2000,
                    "confidence": 0.93,
                }
            ],
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to save transcript"

    result = await db_session.execute(
        select(Recording).where(Recording.id == UUID(recording["id"]))
    )
    failed_recording = result.scalar_one()
    assert failed_recording.status == "failed"
    assert failed_recording.failure_code == "transcript_save_failed"
    assert failed_recording.failure_message == "database exploded"


@pytest.mark.asyncio
async def test_upload_processing_failure_returns_failed_recording_with_audio_preserved(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Transient upload should still return the failed recording when processing fails."""
    recording = await _create_recording(client, auth_headers, title=None)
    monkeypatch.setattr(
        "app.api.routes.recordings.transcribe_audio_file",
        AsyncMock(side_effect=RuntimeError("Deepgram unavailable")),
    )

    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("meeting.mp3", b"fake-mp3-data", "audio/mpeg")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["failure_code"] == "processing_failed"
    assert data["audio_url"] is None
    assert data["segments"] == []


@pytest.mark.asyncio
async def test_upload_processing_failure_hides_sqlalchemy_internal_error(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Async ORM infrastructure details should not be stored as user-facing failures."""
    recording = await _create_recording(client, auth_headers, title=None)
    monkeypatch.setattr(
        "app.api.routes.recordings.transcribe_audio_file",
        AsyncMock(side_effect=MissingGreenlet("greenlet_spawn has not been called")),
    )

    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("meeting.mp3", b"fake-mp3-data", "audio/mpeg")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["failure_code"] == "processing_failed"
    assert data["failure_message"] == "Imported audio processing failed"


@pytest.mark.asyncio
async def test_upload_staging_failure_marks_recording_failed_and_keeps_record_visible(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """If local staging fails, the recording should remain visible with a failed state."""
    recording = await _create_recording(client, auth_headers, title=None)

    monkeypatch.setattr(
        "app.api.routes.recordings._stage_upload_to_disk",
        AsyncMock(side_effect=RuntimeError("disk full")),
    )

    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("meeting.mp3", b"fake-mp3-data", "audio/mpeg")},
    )
    assert response.status_code == 200
    detail = response.json()
    assert detail["status"] == "failed"
    assert detail["failure_code"] == "staging_failed"
    assert detail["audio_url"] is None


@pytest.mark.asyncio
async def test_upload_processing_failure_for_trashed_recording_does_not_leave_processing(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Concurrent soft-delete during upload failure should still finalize the recording state."""
    recording = await _create_recording(client, auth_headers, title=None)
    recording_id = UUID(recording["id"])

    async def soft_delete_then_fail(*args, **kwargs):
        result = await db_session.execute(select(Recording).where(Recording.id == recording_id))
        trashed_recording = result.scalar_one()
        trashed_recording.deleted_at = datetime.now(timezone.utc)
        await db_session.commit()
        raise RuntimeError("transcription worker crashed")

    monkeypatch.setattr(
        "app.api.routes.recordings.transcribe_audio_file",
        soft_delete_then_fail,
    )

    response = await client.post(
        f"/api/recordings/{recording['id']}/upload",
        headers=auth_headers,
        files={"file": ("meeting.mp3", b"fake-mp3-data", "audio/mpeg")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["deleted_at"] is not None
    assert data["status"] == "failed"
    assert data["failure_code"] == "processing_failed"

    result = await db_session.execute(select(Recording).where(Recording.id == recording_id))
    final_recording = result.scalar_one()
    assert final_recording.deleted_at is not None
    assert final_recording.status == "failed"


@pytest.mark.asyncio
async def test_trashed_recording_cannot_be_updated_or_summarized(
    client: AsyncClient,
    auth_headers: dict,
):
    """Mutation endpoints should reject soft-deleted recordings."""
    recording = await _create_recording(client, auth_headers, title="Trash Mutations")
    delete_response = await client.delete(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
    )
    assert delete_response.status_code == 204

    update_response = await client.patch(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
        json={"title": "Should Not Apply"},
    )
    assert update_response.status_code == 404

    summary_response = await client.post(
        f"/api/recordings/{recording['id']}/generate-summary",
        headers=auth_headers,
    )
    assert summary_response.status_code == 404


@pytest.mark.asyncio
async def test_resaving_transcript_replaces_segments_summary_and_generated_action_items(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Retrying a transcript save should replace derived content instead of appending to it."""
    recording = await _create_recording(client, auth_headers, title=None)
    recording_id = UUID(recording["id"])

    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Recovered Recording"),
    )

    first_save = await client.post(
        f"/api/recordings/{recording['id']}/transcript",
        headers=auth_headers,
        json={
            "duration_seconds": 1,
            "segments": [
                {
                    "text": "First save",
                    "speaker": "Speaker 1",
                    "start_ms": 0,
                    "end_ms": 1000,
                    "confidence": 0.9,
                }
            ],
        },
    )
    assert first_save.status_code == 200

    db_session.add(
        Summary(
            recording_id=recording_id,
            summary="Old summary",
        )
    )
    db_session.add(
        ActionItem(
            recording_id=recording_id,
            task="Generated action",
            priority="medium",
            source="generated",
        )
    )
    db_session.add(
        ActionItem(
            recording_id=recording_id,
            task="Manual action",
            priority="low",
            source="manual",
        )
    )
    await db_session.flush()

    second_save = await client.post(
        f"/api/recordings/{recording['id']}/transcript",
        headers=auth_headers,
        json={
            "duration_seconds": 2,
            "segments": [
                {
                    "text": "Second save",
                    "speaker": "Speaker 2",
                    "start_ms": 0,
                    "end_ms": 1500,
                    "confidence": 0.95,
                }
            ],
        },
    )
    assert second_save.status_code == 200
    data = second_save.json()
    assert [segment["content"] for segment in data["segments"]] == ["Second save"]
    assert data["summary"] is None
    assert [item["task"] for item in data["action_items"]] == ["Manual action"]


# ---- PATCH recording endpoint tests ----


@pytest.mark.asyncio
async def test_update_recording_title(client: AsyncClient, auth_headers: dict):
    """PATCH should update the recording title."""
    recording = await _create_recording(client, auth_headers, title="Old Title")

    response = await client.patch(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
        json={"title": "New Title"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "New Title"

    detail = await client.get(f"/api/recordings/{recording['id']}", headers=auth_headers)
    assert detail.json()["title"] == "New Title"


@pytest.mark.asyncio
async def test_update_recording_type(client: AsyncClient, auth_headers: dict):
    """PATCH should update the recording type."""
    recording = await _create_recording(client, auth_headers, type_="note")

    response = await client.patch(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
        json={"type": "meeting"},
    )
    assert response.status_code == 200
    assert response.json()["type"] == "meeting"


@pytest.mark.asyncio
async def test_update_recording_nonexistent_returns_404(client: AsyncClient, auth_headers: dict):
    """PATCH on nonexistent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.patch(
        f"/api/recordings/{fake_id}",
        headers=auth_headers,
        json={"title": "Nope"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_recording_folder_id(client: AsyncClient, auth_headers: dict):
    """PATCH should move recording to a folder."""
    folder_resp = await client.post(
        "/api/folders", headers=auth_headers, json={"name": "Work"}
    )
    assert folder_resp.status_code == 201
    folder_id = folder_resp.json()["id"]

    recording = await _create_recording(client, auth_headers)

    response = await client.patch(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
        json={"folder_id": folder_id},
    )
    assert response.status_code == 200
    assert response.json()["folder_id"] == folder_id

    # Clear folder_id
    clear_response = await client.patch(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
        json={"folder_id": None},
    )
    assert clear_response.status_code == 200
    assert clear_response.json()["folder_id"] is None


# ---- Export endpoint tests ----


@pytest.mark.asyncio
async def test_export_recording_markdown(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Export as markdown should return a markdown file."""
    recording = await _create_recording(client, auth_headers, title="Export Test")
    recording_id = UUID(recording["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Hello from the test",
            start_ms=0,
            end_ms=2000,
            confidence=0.95,
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/export",
        headers=auth_headers,
        params={"format": "markdown"},
    )
    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert "Export_Test.md" in response.headers["content-disposition"]
    assert "Hello from the test" in response.text


@pytest.mark.asyncio
async def test_export_recording_txt(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Export as txt should return plain text."""
    recording = await _create_recording(client, auth_headers, title="Text Export")
    recording_id = UUID(recording["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Plain text content",
            start_ms=0,
            end_ms=1500,
            confidence=0.9,
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/export",
        headers=auth_headers,
        params={"format": "txt"},
    )
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "Text_Export.txt" in response.headers["content-disposition"]
    assert "Plain text content" in response.text


@pytest.mark.asyncio
async def test_export_recording_srt(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Export as SRT should return subtitle format."""
    recording = await _create_recording(client, auth_headers, title="SRT Export")
    recording_id = UUID(recording["id"])

    db_session.add(
        Segment(
            recording_id=recording_id,
            speaker="Speaker 1",
            content="Subtitle line one",
            start_ms=0,
            end_ms=2000,
            confidence=0.9,
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{recording_id}/export",
        headers=auth_headers,
        params={"format": "srt"},
    )
    assert response.status_code == 200
    assert "text/srt" in response.headers["content-type"]
    assert "SRT_Export.srt" in response.headers["content-disposition"]
    assert "Subtitle line one" in response.text
    assert "00:00:00,000" in response.text


@pytest.mark.asyncio
async def test_export_nonexistent_recording_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Export for nonexistent recording returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(
        f"/api/recordings/{fake_id}/export",
        headers=auth_headers,
        params={"format": "markdown"},
    )
    assert response.status_code == 404


# ---- Related recordings endpoint tests ----


@pytest.mark.asyncio
async def test_related_recordings_returns_empty_when_no_embeddings(
    client: AsyncClient,
    auth_headers: dict,
):
    """Related recordings should return empty list when no embeddings exist."""
    recording = await _create_recording(client, auth_headers, title="No Embeddings")

    response = await client.get(
        f"/api/recordings/{recording['id']}/related",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["recording_id"] == recording["id"]
    assert data["related"] == []


@pytest.mark.asyncio
async def test_related_recordings_nonexistent_returns_404(
    client: AsyncClient,
    auth_headers: dict,
):
    """Related recordings for nonexistent recording returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(
        f"/api/recordings/{fake_id}/related",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_related_recordings_auth_required(client: AsyncClient):
    """Related recordings should require authentication."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/api/recordings/{fake_id}/related")
    assert response.status_code == 401


# ---- Additional recording edge case tests ----


@pytest.mark.asyncio
async def test_get_recording_detail_not_found(client: AsyncClient, auth_headers: dict):
    """GET detail for nonexistent recording returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/api/recordings/{fake_id}", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_recording_with_null_title(client: AsyncClient, auth_headers: dict):
    """Creating a recording with null title should succeed."""
    response = await client.post(
        "/api/recordings",
        headers=auth_headers,
        json={"title": None, "type": "note", "language": "en"},
    )
    assert response.status_code == 201
    assert response.json()["title"] is None


@pytest.mark.asyncio
async def test_restore_nonexistent_recording_returns_404(client: AsyncClient, auth_headers: dict):
    """Restoring a nonexistent recording returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.post(
        f"/api/recordings/{fake_id}/restore",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_recording_with_folder_id(client: AsyncClient, auth_headers: dict):
    """Creating a recording with a valid folder_id should assign it to that folder."""
    folder_resp = await client.post(
        "/api/folders", headers=auth_headers, json={"name": "Projects"}
    )
    assert folder_resp.status_code == 201
    folder_id = folder_resp.json()["id"]

    response = await client.post(
        "/api/recordings",
        headers=auth_headers,
        json={"title": "In Folder", "type": "note", "folder_id": folder_id},
    )
    assert response.status_code == 201
    assert response.json()["folder_id"] == folder_id


@pytest.mark.asyncio
async def test_create_recording_with_invalid_folder_returns_404(
    client: AsyncClient, auth_headers: dict
):
    """Creating a recording with a non-existent folder_id should return 404."""
    fake_folder_id = "00000000-0000-0000-0000-000000000000"
    response = await client.post(
        "/api/recordings",
        headers=auth_headers,
        json={"title": "Orphan", "type": "note", "folder_id": fake_folder_id},
    )
    assert response.status_code == 404
    assert "folder not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_recordings_type_filter(client: AsyncClient, auth_headers: dict):
    """Filtering recordings by type should return only matching recordings."""
    await _create_recording(client, auth_headers, title="Meeting 1", type_="meeting")
    await _create_recording(client, auth_headers, title="Meeting 2", type_="meeting")
    await _create_recording(client, auth_headers, title="Note 1", type_="note")
    await _create_recording(client, auth_headers, title="Reflection 1", type_="reflection")

    response = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"type": "meeting"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(r["type"] == "meeting" for r in data)
