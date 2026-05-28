"""Tests for /api/people CRUD + merge endpoint."""

from __future__ import annotations

from uuid import uuid4

from tests.conftest import LEGAL_ACCEPTANCE


async def _register(client) -> dict:
    email = f"people-{uuid4().hex}@example.com"
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "testpassword123", **LEGAL_ACCEPTANCE},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_create_list_and_update_person(client):
    auth = await _register(client)

    create = await client.post(
        "/api/people",
        json={"display_name": "Vasya", "color": "#4f46e5"},
        headers=auth,
    )
    assert create.status_code == 201
    person = create.json()
    assert person["display_name"] == "Vasya"
    assert person["color"] == "#4f46e5"
    assert person["voiceprint_count"] == 0

    listing = await client.get("/api/people", headers=auth)
    assert listing.status_code == 200
    assert [p["display_name"] for p in listing.json()] == ["Vasya"]

    patched = await client.patch(
        f"/api/people/{person['id']}",
        json={"display_name": "Vasily"},
        headers=auth,
    )
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "Vasily"


async def test_blank_display_name_rejected(client):
    auth = await _register(client)
    resp = await client.post(
        "/api/people",
        json={"display_name": "   "},
        headers=auth,
    )
    assert resp.status_code == 422


async def test_delete_person_removes_row(client):
    auth = await _register(client)
    create = await client.post(
        "/api/people", json={"display_name": "Masha"}, headers=auth
    )
    person_id = create.json()["id"]

    delete = await client.delete(f"/api/people/{person_id}", headers=auth)
    assert delete.status_code == 204

    listing = await client.get("/api/people", headers=auth)
    assert listing.json() == []


async def test_merge_moves_segments_and_deletes_source(client, db_session):
    """Merging A into B reassigns A's segments to B and removes A."""
    from sqlalchemy import select

    from app.models import Person, Recording, Segment

    auth = await _register(client)

    source = await client.post(
        "/api/people", json={"display_name": "Source"}, headers=auth
    )
    target = await client.post(
        "/api/people", json={"display_name": "Target"}, headers=auth
    )
    source_id = source.json()["id"]
    target_id = target.json()["id"]

    # Manually attach a segment to "Source" so we can observe the move.
    user_row = (await db_session.execute(select(Person).limit(1))).scalar_one()
    recording = Recording(user_id=user_row.user_id, type="meeting", status="ready")
    db_session.add(recording)
    await db_session.flush()
    segment = Segment(
        recording_id=recording.id,
        speaker="Speaker 0",
        raw_label="Speaker 0",
        person_id=source_id,
        content="hi",
    )
    db_session.add(segment)
    await db_session.commit()

    resp = await client.post(
        f"/api/people/{source_id}/merge",
        json={"into_person_id": target_id},
        headers=auth,
    )
    assert resp.status_code == 200

    await db_session.refresh(segment)
    assert str(segment.person_id) == target_id

    listing = await client.get("/api/people", headers=auth)
    assert [p["id"] for p in listing.json()] == [target_id]


async def test_assign_speaker_creates_person_and_remaps_segments(client, db_session):
    """assign-speaker with new_display_name creates a Person and marks segments."""
    from sqlalchemy import select

    from app.models import Recording, Segment, User

    auth = await _register(client)
    user = (await db_session.execute(select(User).limit(1))).scalar_one()

    recording = Recording(user_id=user.id, type="meeting", status="ready")
    db_session.add(recording)
    await db_session.flush()
    db_session.add_all(
        [
            Segment(
                recording_id=recording.id,
                speaker="Speaker 0",
                raw_label="Speaker 0",
                content="hello",
            ),
            Segment(
                recording_id=recording.id,
                speaker="Speaker 0",
                raw_label="Speaker 0",
                content="world",
            ),
            Segment(
                recording_id=recording.id,
                speaker="Speaker 1",
                raw_label="Speaker 1",
                content="hi back",
            ),
        ]
    )
    await db_session.commit()

    resp = await client.post(
        f"/api/recordings/{recording.id}/assign-speaker",
        json={"raw_label": "Speaker 0", "new_display_name": "Vasya"},
        headers=auth,
    )
    assert resp.status_code == 200
    detail = resp.json()
    by_label: dict[str, list[dict]] = {}
    for seg in detail["segments"]:
        by_label.setdefault(seg["raw_label"], []).append(seg)

    speaker_0_segs = by_label["Speaker 0"]
    assert len(speaker_0_segs) == 2
    assert {seg["display_name"] for seg in speaker_0_segs} == {"Vasya"}
    assert all(not seg["auto_assigned"] for seg in speaker_0_segs)

    speaker_1_segs = by_label["Speaker 1"]
    assert speaker_1_segs[0]["display_name"] is None
    assert speaker_1_segs[0]["person_id"] is None


async def test_assign_speaker_promotes_stored_speaker_embedding_to_voiceprint(
    client, db_session
):
    """Manual speaker correction should teach future voice-ID matches."""
    from sqlalchemy import select

    from app.models import Recording, RecordingSpeakerEmbedding, Segment, User, Voiceprint

    auth = await _register(client)
    user = (await db_session.execute(select(User).limit(1))).scalar_one()

    recording = Recording(user_id=user.id, type="meeting", status="ready")
    db_session.add(recording)
    await db_session.flush()
    db_session.add(
        Segment(
            recording_id=recording.id,
            speaker="Speaker 0",
            raw_label="Speaker 0",
            content="hello",
            start_ms=1_000,
            end_ms=8_000,
        )
    )
    db_session.add(
        RecordingSpeakerEmbedding(
            user_id=user.id,
            recording_id=recording.id,
            raw_label="Speaker 0",
            embedding=[0.2] * 192,
            model="ecapa-tdnn-voxceleb-v1",
            start_ms=1_000,
            end_ms=8_000,
            duration_s=7.0,
        )
    )
    await db_session.commit()

    resp = await client.post(
        f"/api/recordings/{recording.id}/assign-speaker",
        json={"raw_label": "Speaker 0", "new_display_name": "Vasya"},
        headers=auth,
    )
    assert resp.status_code == 200
    person_id = resp.json()["segments"][0]["person_id"]

    voiceprint = (
        await db_session.execute(
            select(Voiceprint).where(
                Voiceprint.person_id == person_id,
                Voiceprint.source_recording_id == recording.id,
                Voiceprint.source_raw_label == "Speaker 0",
            )
        )
    ).scalar_one()
    assert voiceprint.user_id == user.id
    assert voiceprint.duration_s == 7.0
    assert list(voiceprint.embedding) == [0.2] * 192

    repeat = await client.post(
        f"/api/recordings/{recording.id}/assign-speaker",
        json={"raw_label": "Speaker 0", "person_id": person_id},
        headers=auth,
    )
    assert repeat.status_code == 200
    voiceprints = (
        await db_session.execute(
            select(Voiceprint).where(
                Voiceprint.person_id == person_id,
                Voiceprint.source_recording_id == recording.id,
                Voiceprint.source_raw_label == "Speaker 0",
            )
        )
    ).scalars().all()
    assert len(voiceprints) == 1


async def test_assign_speaker_rejects_both_options(client, db_session):
    from sqlalchemy import select

    from app.models import Recording, User

    auth = await _register(client)
    user = (await db_session.execute(select(User).limit(1))).scalar_one()
    recording = Recording(user_id=user.id, type="meeting", status="ready")
    db_session.add(recording)
    await db_session.commit()

    resp = await client.post(
        f"/api/recordings/{recording.id}/assign-speaker",
        json={
            "raw_label": "Speaker 0",
            "person_id": str(uuid4()),
            "new_display_name": "Vasya",
        },
        headers=auth,
    )
    assert resp.status_code == 400


async def test_rematch_uses_stored_speaker_embeddings_and_preserves_manual_assignments(
    client, db_session, monkeypatch
):
    from sqlalchemy import select

    from app.models import Person, Recording, RecordingSpeakerEmbedding, Segment, User

    auth = await _register(client)
    user = (await db_session.execute(select(User).limit(1))).scalar_one()
    matched_person = Person(user_id=user.id, display_name="Matched")
    manual_person = Person(user_id=user.id, display_name="Manual")
    db_session.add_all([matched_person, manual_person])
    await db_session.flush()
    recording = Recording(user_id=user.id, type="meeting", status="ready")
    db_session.add(recording)
    await db_session.flush()
    db_session.add_all(
        [
            Segment(
                recording_id=recording.id,
                speaker="Speaker 0",
                raw_label="Speaker 0",
                content="auto candidate",
                person_id=None,
                auto_assigned=False,
            ),
            Segment(
                recording_id=recording.id,
                speaker="Speaker 1",
                raw_label="Speaker 1",
                content="manual should stay",
                person_id=manual_person.id,
                auto_assigned=False,
            ),
        ]
    )
    db_session.add_all(
        [
            RecordingSpeakerEmbedding(
                user_id=user.id,
                recording_id=recording.id,
                raw_label="Speaker 0",
                embedding=[0.2] * 192,
                model="ecapa-tdnn-voxceleb-v1",
                start_ms=0,
                end_ms=7_000,
                duration_s=7.0,
            ),
            RecordingSpeakerEmbedding(
                user_id=user.id,
                recording_id=recording.id,
                raw_label="Speaker 1",
                embedding=[0.4] * 192,
                model="ecapa-tdnn-voxceleb-v1",
                start_ms=8_000,
                end_ms=15_000,
                duration_s=7.0,
            ),
        ]
    )
    await db_session.commit()

    async def fake_match(db, user_id, embedding, threshold):
        del db, user_id, threshold
        if list(embedding) == [0.2] * 192:
            return matched_person.id, 0.91
        return None

    monkeypatch.setattr(
        "app.core.voice_identification._best_voiceprint_match",
        fake_match,
    )

    resp = await client.post(
        f"/api/recordings/{recording.id}/rematch",
        headers=auth,
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "recording_id": str(recording.id),
        "updated_clusters": 1,
        "matched_clusters": 1,
    }

    refreshed = (
        await db_session.execute(
            select(Segment).where(Segment.recording_id == recording.id).order_by(Segment.raw_label)
        )
    ).scalars().all()
    assert refreshed[0].person_id == matched_person.id
    assert refreshed[0].auto_assigned is True
    assert refreshed[0].match_confidence == 0.91
    assert refreshed[1].person_id == manual_person.id
    assert refreshed[1].auto_assigned is False
    assert refreshed[1].match_confidence is None


async def test_rematch_returns_422_when_no_speaker_embeddings(client, db_session):
    from sqlalchemy import select

    from app.models import Recording, User

    auth = await _register(client)
    user = (await db_session.execute(select(User).limit(1))).scalar_one()
    recording = Recording(user_id=user.id, type="meeting", status="ready")
    db_session.add(recording)
    await db_session.commit()

    resp = await client.post(
        f"/api/recordings/{recording.id}/rematch",
        headers=auth,
    )
    assert resp.status_code == 422
    assert "speaker voice embeddings" in resp.json()["detail"]
