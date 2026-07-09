"""Upload route: capture sidecar persistence and invalid-sidecar tolerance."""

import json
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recording import Recording


async def _create_recording(client: AsyncClient, auth_headers: dict) -> str:
    response = await client.post(
        "/api/recordings",
        headers=auth_headers,
        json={"type": "meeting", "language": "multi"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.asyncio
async def test_upload_persists_valid_capture_metadata(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording_id = await _create_recording(client, auth_headers)

    enqueued: list[dict] = []

    async def fake_enqueue(**kwargs):
        enqueued.append(kwargs)

    monkeypatch.setattr(
        "app.api.routes.recordings.enqueue_recording_audio_processing",
        fake_enqueue,
    )

    sidecar = {
        "version": 1,
        "capture": "dual_mono_mix",
        "local_speech_ms": [[0, 2500], [4000, 6000]],
        "aec": False,
    }
    response = await client.post(
        f"/api/recordings/{recording_id}/upload",
        headers=auth_headers,
        files={"file": ("meeting.wav", b"RIFFfakewav", "audio/wav")},
        data={"capture_metadata": json.dumps(sidecar)},
    )
    assert response.status_code == 200, response.text
    assert enqueued, "processing should be enqueued"

    db_session.expire_all()
    recording = await db_session.get(Recording, UUID(recording_id))
    assert recording is not None
    assert recording.capture_metadata == {
        "version": 1,
        "capture": "dual_mono_mix",
        "local_speech_ms": [[0, 2500], [4000, 6000]],
        "aec": False,
    }


@pytest.mark.asyncio
async def test_upload_tolerates_invalid_capture_metadata(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording_id = await _create_recording(client, auth_headers)

    async def fake_enqueue(**kwargs):
        return None

    monkeypatch.setattr(
        "app.api.routes.recordings.enqueue_recording_audio_processing",
        fake_enqueue,
    )
    anomalies: list[str] = []
    monkeypatch.setattr(
        "app.api.routes.recordings.capture_sentry_anomaly",
        lambda code, *args, **kwargs: anomalies.append(code),
    )

    response = await client.post(
        f"/api/recordings/{recording_id}/upload",
        headers=auth_headers,
        files={"file": ("meeting.wav", b"RIFFfakewav", "audio/wav")},
        data={"capture_metadata": "{broken json"},
    )
    assert response.status_code == 200, response.text

    db_session.expire_all()
    recording = await db_session.get(Recording, UUID(recording_id))
    assert recording is not None
    assert recording.capture_metadata is None
    assert "recording.capture_metadata.invalid" in anomalies
