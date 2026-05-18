"""Tests for /api/voice-enrollment voice samples."""

from __future__ import annotations

import math
import struct
import wave
from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import Person, User, Voiceprint


def _wav_bytes(duration_s: float, freq_hz: float = 220.0, sr: int = 16_000) -> bytes:
    """Return an in-memory mono 16-bit WAV at the given duration."""
    buffer = BytesIO()
    with wave.open(buffer, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        for i in range(int(duration_s * sr)):
            value = int(0.5 * 32767 * math.sin(2 * math.pi * freq_hz * i / sr))
            wf.writeframesraw(struct.pack("<h", value))
    return buffer.getvalue()


async def _register(client) -> dict[str, str]:
    email = f"voice-{uuid4().hex}@example.com"
    resp = await client.post(
        "/api/auth/register", json={"email": email, "password": "testpassword123"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def fake_voiceprint_store(monkeypatch):
    async def _store_voiceprint(
        *,
        db,
        user_id,
        person_id,
        audio_path,
        start_ms,
        end_ms,
        source_recording_id,
    ):
        voiceprint = Voiceprint(
            user_id=user_id,
            person_id=person_id,
            embedding=[0.0] * 192,
            model="test-ecapa",
            source_recording_id=source_recording_id,
            duration_s=(end_ms - start_ms) / 1000.0,
            quality_score=None,
        )
        db.add(voiceprint)
        await db.flush()
        return voiceprint.id

    monkeypatch.setattr(
        "app.api.routes.voice_enrollment.store_voiceprint_from_path",
        _store_voiceprint,
    )


async def test_enroll_too_short_returns_422(client):
    auth = await _register(client)
    resp = await client.post(
        "/api/voice-enrollment",
        headers=auth,
        files={"audio": ("voice.wav", _wav_bytes(duration_s=2.0), "audio/wav")},
    )
    assert resp.status_code == 422
    assert "too short" in resp.json()["detail"].lower()


async def test_enroll_malformed_returns_422(client):
    auth = await _register(client)
    resp = await client.post(
        "/api/voice-enrollment",
        headers=auth,
        files={"audio": ("garbage.wav", b"not-a-wav-file", "audio/wav")},
    )
    assert resp.status_code == 422
    assert "decode" in resp.json()["detail"].lower()


async def test_enroll_creates_person_and_voiceprint(
    client, db_session, fake_voiceprint_store
):
    """Happy path: 6s WAV → Person "You" created + 1 voiceprint row in DB."""
    auth = await _register(client)

    resp = await client.post(
        "/api/voice-enrollment",
        headers=auth,
        files={"audio": ("voice.wav", _wav_bytes(duration_s=6.0), "audio/wav")},
        data={"display_name": "Mik"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["person"]["display_name"] == "Mik"
    assert body["duration_s"] == pytest.approx(6.0, abs=0.05)
    assert body["voiceprint_id"]

    voiceprints = (
        await db_session.execute(
            select(Voiceprint).where(Voiceprint.id == body["voiceprint_id"])
        )
    ).scalars().all()
    assert len(voiceprints) == 1
    assert voiceprints[0].duration_s == pytest.approx(6.0, abs=0.05)


async def test_enroll_default_display_name_is_you(client, fake_voiceprint_store):
    auth = await _register(client)
    resp = await client.post(
        "/api/voice-enrollment",
        headers=auth,
        files={"audio": ("voice.wav", _wav_bytes(duration_s=6.0), "audio/wav")},
    )
    assert resp.status_code == 200
    assert resp.json()["person"]["display_name"] == "You"


async def test_enroll_reuses_existing_person_by_name(
    client, db_session, fake_voiceprint_store
):
    """Second enrollment with the same display_name attaches a voiceprint to the same Person."""
    auth = await _register(client)

    first = await client.post(
        "/api/voice-enrollment",
        headers=auth,
        files={"audio": ("voice.wav", _wav_bytes(duration_s=6.0), "audio/wav")},
        data={"display_name": "Mik"},
    )
    second = await client.post(
        "/api/voice-enrollment",
        headers=auth,
        files={
            "audio": (
                "voice2.wav",
                _wav_bytes(duration_s=6.0, freq_hz=440.0),
                "audio/wav",
            )
        },
        data={"display_name": "Mik"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["person"]["id"] == second.json()["person"]["id"]

    user = (await db_session.execute(select(User).limit(1))).scalar_one()
    persons = (
        await db_session.execute(select(Person).where(Person.user_id == user.id))
    ).scalars().all()
    assert len(persons) == 1


async def test_enroll_with_person_id_attaches_to_specified_person(
    client, fake_voiceprint_store
):
    auth = await _register(client)

    create = await client.post(
        "/api/people", headers=auth, json={"display_name": "Friend"}
    )
    person_id = create.json()["id"]

    resp = await client.post(
        "/api/voice-enrollment",
        headers=auth,
        files={"audio": ("voice.wav", _wav_bytes(duration_s=6.0), "audio/wav")},
        data={"person_id": person_id},
    )
    assert resp.status_code == 200
    assert resp.json()["person"]["id"] == person_id


async def test_enroll_with_unknown_person_id_returns_404(client):
    auth = await _register(client)
    resp = await client.post(
        "/api/voice-enrollment",
        headers=auth,
        files={"audio": ("voice.wav", _wav_bytes(duration_s=6.0), "audio/wav")},
        data={"person_id": str(uuid4())},
    )
    assert resp.status_code == 404
