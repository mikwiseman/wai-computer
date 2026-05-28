"""Tests for the voice-sharing directory API + cross-user matching."""

from __future__ import annotations

import math
import struct
import wave
from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.voice_embedding import MODEL_NAME
from app.core.voice_identification import _best_public_directory_match
from app.core.voice_sharing import refresh_published_voiceprint_if_any, unpublish_voice_sharing
from app.models.person import Person, PublicVoiceprint, Voiceprint
from app.models.recording import Recording, Segment
from app.models.user import User
from tests.conftest import LEGAL_ACCEPTANCE


def _wav_bytes(duration_s: float, freq_hz: float = 220.0, sr: int = 16_000) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        for i in range(int(duration_s * sr)):
            value = int(0.5 * 32767 * math.sin(2 * math.pi * freq_hz * i / sr))
            wf.writeframesraw(struct.pack("<h", value))
    return buffer.getvalue()


@pytest.fixture
def fake_voiceprint_store(monkeypatch):
    async def _store_voiceprint(
        *, db, user_id, person_id, audio_path, start_ms, end_ms, source_recording_id
    ):
        voiceprint = Voiceprint(
            user_id=user_id,
            person_id=person_id,
            embedding=[0.0] * 192,
            model=MODEL_NAME,
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


async def _register(client, email: str | None = None) -> tuple[dict[str, str], str]:
    email = email or f"voice-share-{uuid4().hex}@example.com"
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "testpassword123", **LEGAL_ACCEPTANCE},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, email


async def _enroll(client, auth: dict[str, str], display_name: str = "Me") -> str:
    resp = await client.post(
        "/api/voice-enrollment",
        headers=auth,
        files={"audio": ("voice.wav", _wav_bytes(duration_s=6.0), "audio/wav")},
        data={"display_name": display_name},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["person"]["id"]


async def test_voice_sharing_default_state_is_off_with_missing_prereqs(client):
    auth, _ = await _register(client)
    response = await client.get("/api/settings/voice-sharing", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["can_enable"] is False
    assert body["has_first_name"] is False
    assert body["has_last_name"] is False
    assert body["has_voiceprint"] is False
    assert body["shared_name"] is None


async def test_voice_sharing_requires_names_and_voiceprint(
    client, fake_voiceprint_store
):
    auth, _ = await _register(client)
    response = await client.post("/api/settings/voice-sharing", headers=auth)
    assert response.status_code == 409
    assert "first and last name" in response.json()["detail"]

    await client.patch(
        "/api/settings/identity",
        headers=auth,
        json={"first_name": "Mik", "last_name": "Wiseman"},
    )
    response = await client.post("/api/settings/voice-sharing", headers=auth)
    assert response.status_code == 409
    assert "Enroll your voice" in response.json()["detail"]


async def test_voice_sharing_publish_then_unpublish_round_trip(
    client, db_session, fake_voiceprint_store
):
    auth, email = await _register(client)
    await client.patch(
        "/api/settings/identity",
        headers=auth,
        json={"first_name": "Anna", "last_name": "Wise"},
    )
    await _enroll(client, auth, display_name="Anna")

    enabled = await client.post("/api/settings/voice-sharing", headers=auth)
    assert enabled.status_code == 200
    body = enabled.json()
    assert body["enabled"] is True
    assert body["can_enable"] is True
    assert body["shared_name"] == "Anna Wise"

    user = (
        await db_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    public = (
        await db_session.execute(
            select(PublicVoiceprint).where(PublicVoiceprint.user_id == user.id)
        )
    ).scalar_one()
    assert public.first_name == "Anna"
    assert public.last_name == "Wise"
    assert public.embedding_model == MODEL_NAME

    disabled = await client.delete("/api/settings/voice-sharing", headers=auth)
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    remaining = (
        await db_session.execute(
            select(PublicVoiceprint).where(PublicVoiceprint.user_id == user.id)
        )
    ).scalar_one_or_none()
    assert remaining is None


async def test_voice_sharing_publish_is_idempotent(
    client, db_session, fake_voiceprint_store
):
    auth, email = await _register(client)
    await client.patch(
        "/api/settings/identity",
        headers=auth,
        json={"first_name": "Bob", "last_name": "Builder"},
    )
    await _enroll(client, auth, display_name="Bob")

    await client.post("/api/settings/voice-sharing", headers=auth)
    await client.post("/api/settings/voice-sharing", headers=auth)

    user = (
        await db_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    public_rows = (
        await db_session.execute(
            select(PublicVoiceprint).where(PublicVoiceprint.user_id == user.id)
        )
    ).scalars().all()
    assert len(public_rows) == 1


async def test_voice_sharing_rejects_reserved_directory_name(
    client, fake_voiceprint_store
):
    auth, _ = await _register(client)
    await client.patch(
        "/api/settings/identity",
        headers=auth,
        json={"first_name": "Wai", "last_name": "Computer"},
    )
    await _enroll(client, auth, display_name="Self")

    response = await client.post("/api/settings/voice-sharing", headers=auth)

    assert response.status_code == 409
    assert "reserved" in response.json()["detail"]


async def test_refresh_published_voiceprint_swallows_prerequisite_failure(db_session):
    unit_embedding = [0.0] * 192
    unit_embedding[9] = 1.0
    publisher = await _seed_published_user(
        db_session=db_session,
        email="publisher-refresh-failure@example.com",
        first_name="Mik",
        last_name="Wiseman",
        embedding=unit_embedding,
    )
    publisher.first_name = ""
    await db_session.flush()

    await refresh_published_voiceprint_if_any(db=db_session, user=publisher)

    public = (
        await db_session.execute(
            select(PublicVoiceprint).where(PublicVoiceprint.user_id == publisher.id)
        )
    ).scalar_one()
    assert public.first_name == "Mik"


async def test_voice_sharing_endpoints_require_auth(client):
    assert (await client.get("/api/settings/voice-sharing")).status_code == 401
    assert (await client.post("/api/settings/voice-sharing")).status_code == 401
    assert (await client.delete("/api/settings/voice-sharing")).status_code == 401


async def _seed_published_user(
    *,
    db_session,
    email: str,
    first_name: str,
    last_name: str,
    embedding: list[float],
) -> User:
    """Insert a User + one publishable Voiceprint + one PublicVoiceprint."""
    from datetime import datetime, timezone

    user = User(email=email, first_name=first_name, last_name=last_name)
    db_session.add(user)
    await db_session.flush()

    person = Person(user_id=user.id, display_name=f"{first_name}")
    db_session.add(person)
    await db_session.flush()

    user.self_person_id = person.id

    voiceprint = Voiceprint(
        user_id=user.id,
        person_id=person.id,
        embedding=embedding,
        model=MODEL_NAME,
        source_recording_id=None,
        duration_s=6.0,
    )
    db_session.add(voiceprint)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    db_session.add(
        PublicVoiceprint(
            user_id=user.id,
            voiceprint_id=voiceprint.id,
            embedding=embedding,
            embedding_model=MODEL_NAME,
            first_name=first_name,
            last_name=last_name,
            published_at=now,
            updated_at=now,
        )
    )
    await db_session.flush()
    return user


async def test_cross_user_match_creates_directory_person(client, db_session):
    """A published voiceprint matches against the receiver and yields a fresh
    Person tagged with directory_user_id pointing back at the publisher."""
    unit_embedding = [0.0] * 192
    unit_embedding[0] = 1.0
    publisher = await _seed_published_user(
        db_session=db_session,
        email="publisher@example.com",
        first_name="Mik",
        last_name="Wiseman",
        embedding=unit_embedding,
    )
    receiver = User(email="receiver@example.com")
    db_session.add(receiver)
    await db_session.flush()

    match = await _best_public_directory_match(
        db=db_session,
        receiver_user_id=receiver.id,
        embedding=unit_embedding,
        threshold=0.65,
    )
    assert match is not None
    person_id, similarity = match
    assert similarity >= 0.99
    matched_person = (
        await db_session.execute(select(Person).where(Person.id == person_id))
    ).scalar_one()
    assert matched_person.user_id == receiver.id
    assert matched_person.directory_user_id == publisher.id
    assert matched_person.display_name == "Mik Wiseman"


async def test_cross_user_match_excludes_self(client, db_session):
    """A user must not match their own publish in their own recordings."""
    unit_embedding = [0.0] * 192
    unit_embedding[5] = 1.0
    user = await _seed_published_user(
        db_session=db_session,
        email="self-match@example.com",
        first_name="Solo",
        last_name="Person",
        embedding=unit_embedding,
    )

    match = await _best_public_directory_match(
        db=db_session,
        receiver_user_id=user.id,
        embedding=unit_embedding,
        threshold=0.65,
    )
    assert match is None


async def test_unpublish_voice_sharing_unlinks_directory_people_and_auto_segments(
    client, db_session
):
    unit_embedding = [0.0] * 192
    unit_embedding[12] = 1.0
    publisher = await _seed_published_user(
        db_session=db_session,
        email="publisher-unpublish@example.com",
        first_name="Mik",
        last_name="Wiseman",
        embedding=unit_embedding,
    )
    receiver = User(email="receiver-unpublish@example.com")
    db_session.add(receiver)
    await db_session.flush()

    directory_person = Person(
        user_id=receiver.id,
        directory_user_id=publisher.id,
        display_name="Mik Wiseman",
    )
    db_session.add(directory_person)
    await db_session.flush()
    recording = Recording(user_id=receiver.id, type="meeting", status="ready")
    db_session.add(recording)
    await db_session.flush()
    auto_segment = Segment(
        recording_id=recording.id,
        speaker="Speaker 0",
        raw_label="Speaker 0",
        person_id=directory_person.id,
        auto_assigned=True,
        match_confidence=0.94,
        content="auto directory match",
    )
    manual_segment = Segment(
        recording_id=recording.id,
        speaker="Speaker 1",
        raw_label="Speaker 1",
        person_id=directory_person.id,
        auto_assigned=False,
        match_confidence=None,
        content="manual assignment stays",
    )
    db_session.add_all([auto_segment, manual_segment])
    await db_session.flush()

    state = await unpublish_voice_sharing(db=db_session, user=publisher)

    assert state.enabled is False
    refreshed_person = (
        await db_session.execute(select(Person).where(Person.id == directory_person.id))
    ).scalar_one()
    assert refreshed_person.directory_user_id is None
    assert refreshed_person.display_name == "Removed from WaiComputer directory"
    refreshed_segments = (
        await db_session.execute(
            select(Segment)
            .where(Segment.recording_id == recording.id)
            .order_by(Segment.raw_label)
        )
    ).scalars().all()
    assert refreshed_segments[0].person_id is None
    assert refreshed_segments[0].auto_assigned is False
    assert refreshed_segments[0].match_confidence is None
    assert refreshed_segments[1].person_id == directory_person.id
    assert refreshed_segments[1].auto_assigned is False


async def test_cross_user_match_reuses_existing_directory_person(client, db_session):
    """Re-matching the same publisher reuses the previously-created Person row."""
    unit_embedding = [0.0] * 192
    unit_embedding[10] = 1.0
    publisher = await _seed_published_user(
        db_session=db_session,
        email="publisher-reuse@example.com",
        first_name="Anna",
        last_name="Smith",
        embedding=unit_embedding,
    )
    receiver = User(email="receiver-reuse@example.com")
    db_session.add(receiver)
    await db_session.flush()

    first = await _best_public_directory_match(
        db=db_session,
        receiver_user_id=receiver.id,
        embedding=unit_embedding,
        threshold=0.65,
    )
    assert first is not None
    second = await _best_public_directory_match(
        db=db_session,
        receiver_user_id=receiver.id,
        embedding=unit_embedding,
        threshold=0.65,
    )
    assert second is not None
    assert first[0] == second[0]

    people = (
        await db_session.execute(
            select(Person).where(
                Person.user_id == receiver.id,
                Person.directory_user_id == publisher.id,
            )
        )
    ).scalars().all()
    assert len(people) == 1
