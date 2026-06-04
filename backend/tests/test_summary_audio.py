"""Tests for server-generated summary audio artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item, ItemSummary
from app.models.recording import Recording, Summary
from app.models.summary_audio import SummaryAudioArtifact, SummaryAudioStatus
from tests.conftest import LEGAL_ACCEPTANCE


async def _register_headers(client: AsyncClient, email: str) -> dict[str, str]:
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "testpassword123", **LEGAL_ACCEPTANCE},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_summary_recording(
    client: AsyncClient,
    db_session: AsyncSession,
    headers: dict[str, str],
) -> str:
    response = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": "Summary audio", "type": "note", "language": "ru"},
    )
    assert response.status_code == 201
    recording_id = response.json()["id"]

    recording = (
        await db_session.execute(select(Recording).where(Recording.id == UUID(recording_id)))
    ).scalar_one()
    db_session.add(
        Summary(
            recording_id=recording.id,
            summary="Короткое саммари встречи.",
            key_points=["Обсудили запуск", "Зафиксировали следующий шаг"],
            topics=["запуск"],
            people_mentioned=["Mik"],
            decisions=[],
            sentiment="neutral",
        )
    )
    await db_session.commit()
    return recording_id


async def _create_summary_item(db_session: AsyncSession, user_id: UUID) -> str:
    item = Item(
        user_id=user_id,
        source="paste",
        kind="note",
        title="Item",
        body="Body",
        content_hash="summary-audio-item",
        state="raw",
    )
    db_session.add(item)
    await db_session.flush()
    db_session.add(
        ItemSummary(
            item_id=item.id,
            summary="Item summary.",
            key_points=["Point"],
            topics=["topic"],
            people_mentioned=[],
            action_items=[],
            highlights=[],
            key_moments=[],
            sentiment="neutral",
        )
    )
    await db_session.commit()
    return str(item.id)


@pytest.mark.asyncio
async def test_recording_summary_audio_can_be_queued_and_streamed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "summary_audio_storage_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.api.routes.recordings.enqueue_summary_audio_generation",
        lambda job_id: "task-summary-audio",
    )

    recording_id = await _create_summary_recording(client, db_session, auth_headers)

    queued = await client.post(
        f"/api/recordings/{recording_id}/summary/audio",
        headers=auth_headers,
    )

    assert queued.status_code == 202
    payload = queued.json()
    assert payload["source_kind"] == "recording"
    assert payload["source_id"] == recording_id
    assert payload["status"] == "queued"
    assert payload["provider"] == "xai"
    assert payload["audio_url"] is None

    artifact = (
        await db_session.execute(
            select(SummaryAudioArtifact).where(
                SummaryAudioArtifact.recording_id == UUID(recording_id)
            )
        )
    ).scalar_one()
    audio_path = tmp_path / str(artifact.user_id) / f"{artifact.id}.mp3"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"ID3summary-audio")
    artifact.status = SummaryAudioStatus.SUCCEEDED.value
    artifact.stage = "complete"
    artifact.progress_percent = 100
    artifact.storage_path = f"{artifact.user_id}/{artifact.id}.mp3"
    artifact.content_type = "audio/mpeg"
    artifact.byte_size = audio_path.stat().st_size
    artifact.completed_at = datetime.now(timezone.utc)
    await db_session.commit()

    state = await client.get(
        f"/api/recordings/{recording_id}/summary/audio",
        headers=auth_headers,
    )
    assert state.status_code == 200
    assert state.json()["audio_url"] == f"/api/recordings/{recording_id}/summary/audio/file"

    streamed = await client.get(
        f"/api/recordings/{recording_id}/summary/audio/file",
        headers={**auth_headers, "Range": "bytes=0-2"},
    )
    assert streamed.status_code == 206
    assert streamed.headers["content-type"] == "audio/mpeg"
    assert streamed.content == b"ID3"


@pytest.mark.asyncio
async def test_summary_audio_is_owner_scoped(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.routes.recordings.enqueue_summary_audio_generation",
        lambda job_id: "task-summary-audio",
    )
    recording_id = await _create_summary_recording(client, db_session, auth_headers)
    other_headers = await _register_headers(client, "summary-audio-other@example.com")

    response = await client.post(
        f"/api/recordings/{recording_id}/summary/audio",
        headers=other_headers,
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_item_summary_audio_can_be_queued(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.routes.items.enqueue_summary_audio_generation",
        lambda job_id: "task-summary-audio",
    )
    user = (
        await db_session.execute(
            select(Recording.user_id).join(Summary).limit(1)
        )
    ).scalar_one_or_none()
    if user is None:
        recording_id = await _create_summary_recording(client, db_session, auth_headers)
        user = (
            await db_session.execute(
                select(Recording.user_id).where(Recording.id == UUID(recording_id))
            )
        ).scalar_one()
    item_id = await _create_summary_item(db_session, user)

    queued = await client.post(f"/api/items/{item_id}/summary/audio", headers=auth_headers)

    assert queued.status_code == 202
    payload = queued.json()
    assert payload["source_kind"] == "item"
    assert payload["source_id"] == item_id
    assert payload["status"] == "queued"
