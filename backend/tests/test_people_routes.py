"""Tests for /api/people CRUD + merge endpoint."""

from __future__ import annotations

from uuid import uuid4


async def _register(client) -> dict:
    email = f"people-{uuid4().hex}@example.com"
    resp = await client.post(
        "/api/auth/register", json={"email": email, "password": "testpassword123"}
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


async def test_rematch_returns_422_until_audio_retention(client, db_session):
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
