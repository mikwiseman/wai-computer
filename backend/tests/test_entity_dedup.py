"""Fuzzy entity-merge governance: near-duplicate detection + the destructive
merge (provenance re-point under the mention unique-constraint + relation
self-loop handling) + the routes."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.entity_dedup import find_duplicate_entity_candidates, merge_entities
from app.models.entity import Entity, EntityMention, EntityRelation
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _user(db) -> User:
    u = User(email=f"dedup-{uuid4().hex}@example.com", password_hash="x")
    db.add(u)
    await db.flush()
    return u


async def _entity(db, user, name, type_="person") -> Entity:
    e = Entity(user_id=user.id, type=type_, name=name)
    db.add(e)
    await db.flush()
    return e


async def _mention(db, user, entity, source_kind, source_id) -> None:
    db.add(
        EntityMention(
            user_id=user.id, entity_id=entity.id,
            source_kind=source_kind, source_id=source_id,
        )
    )
    await db.flush()


# --- detection ---------------------------------------------------------------


async def test_detects_near_spelling_duplicate(db_session) -> None:
    u = await _user(db_session)
    a = await _entity(db_session, u, "Petrova")
    b = await _entity(db_session, u, "Petrov")
    await _mention(db_session, u, a, "item", uuid4())  # a is more-mentioned -> keep

    cands = await find_duplicate_entity_candidates(db_session, u.id, threshold=0.85)
    assert len(cands) == 1
    c = cands[0]
    assert {c.keep_id, c.drop_id} == {str(a.id), str(b.id)}
    assert c.keep_id == str(a.id)  # more mentions wins the "keep" suggestion
    assert c.score >= 0.85


async def test_different_types_not_compared(db_session) -> None:
    u = await _user(db_session)
    await _entity(db_session, u, "Petrova", "person")
    await _entity(db_session, u, "Petrov", "topic")
    assert await find_duplicate_entity_candidates(db_session, u.id, threshold=0.85) == []


async def test_dissimilar_not_flagged(db_session) -> None:
    u = await _user(db_session)
    await _entity(db_session, u, "Apple")
    await _entity(db_session, u, "Google")
    assert await find_duplicate_entity_candidates(db_session, u.id) == []


# --- merge -------------------------------------------------------------------


async def test_merge_repoints_mentions_and_deletes_drop(db_session) -> None:
    u = await _user(db_session)
    keep = await _entity(db_session, u, "Petrova")
    drop = await _entity(db_session, u, "Petrov")
    await _mention(db_session, u, drop, "item", uuid4())
    await _mention(db_session, u, drop, "recording", uuid4())

    assert await merge_entities(db_session, user_id=u.id, keep_id=keep.id, drop_id=drop.id) is True
    assert (
        await db_session.execute(select(Entity).where(Entity.id == drop.id))
    ).scalar_one_or_none() is None
    keep_mentions = (
        await db_session.execute(
            select(EntityMention).where(EntityMention.entity_id == keep.id)
        )
    ).scalars().all()
    assert len(keep_mentions) == 2


async def test_merge_dedups_colliding_mention(db_session) -> None:
    # keep + drop mentioned by the SAME source -> re-point must not violate the
    # unique (entity_id, source_kind, source_id) constraint.
    u = await _user(db_session)
    keep = await _entity(db_session, u, "Petrova")
    drop = await _entity(db_session, u, "Petrov")
    shared = uuid4()
    await _mention(db_session, u, keep, "item", shared)
    await _mention(db_session, u, drop, "item", shared)  # collides with keep's
    await _mention(db_session, u, drop, "item", uuid4())  # unique to drop

    assert await merge_entities(db_session, user_id=u.id, keep_id=keep.id, drop_id=drop.id) is True
    keep_mentions = (
        await db_session.execute(
            select(EntityMention).where(EntityMention.entity_id == keep.id)
        )
    ).scalars().all()
    keys = {(m.source_kind, str(m.source_id)) for m in keep_mentions}
    assert len(keep_mentions) == 2 and len(keys) == 2  # collision dropped, no dup


async def test_merge_handles_relations_and_self_loops(db_session) -> None:
    u = await _user(db_session)
    keep = await _entity(db_session, u, "Petrova")
    drop = await _entity(db_session, u, "Petrov")
    other = await _entity(db_session, u, "Moscow", "topic")
    db_session.add(EntityRelation(source_id=drop.id, target_id=other.id))  # -> keep->other
    db_session.add(EntityRelation(source_id=other.id, target_id=drop.id))  # -> other->keep
    db_session.add(EntityRelation(source_id=drop.id, target_id=keep.id))   # -> self-loop, deleted
    await db_session.flush()

    assert await merge_entities(db_session, user_id=u.id, keep_id=keep.id, drop_id=drop.id) is True
    rels = (await db_session.execute(select(EntityRelation))).scalars().all()
    assert all(r.source_id != r.target_id for r in rels)  # no self-loops
    assert {(r.source_id, r.target_id) for r in rels} == {
        (keep.id, other.id),
        (other.id, keep.id),
    }


async def test_merge_same_id_returns_false(db_session) -> None:
    u = await _user(db_session)
    e = await _entity(db_session, u, "X")
    assert await merge_entities(db_session, user_id=u.id, keep_id=e.id, drop_id=e.id) is False


async def test_merge_unknown_returns_false(db_session) -> None:
    u = await _user(db_session)
    keep = await _entity(db_session, u, "X")
    assert await merge_entities(db_session, user_id=u.id, keep_id=keep.id, drop_id=uuid4()) is False


async def test_merge_cross_user_returns_false(db_session) -> None:
    u1 = await _user(db_session)
    u2 = await _user(db_session)
    keep = await _entity(db_session, u1, "X")
    drop = await _entity(db_session, u2, "Y")  # belongs to a different user
    assert (
        await merge_entities(db_session, user_id=u1.id, keep_id=keep.id, drop_id=drop.id)
        is False
    )


async def test_keep_suggestion_prefers_more_mentioned(db_session) -> None:
    # Alphabetically-first "Petrov" is the more-mentioned one -> kept.
    u = await _user(db_session)
    a = await _entity(db_session, u, "Petrov")
    await _entity(db_session, u, "Petrova")
    await _mention(db_session, u, a, "item", uuid4())
    cands = await find_duplicate_entity_candidates(db_session, u.id, threshold=0.85)
    assert cands[0].keep_id == str(a.id)


async def test_caps_comparison_per_type(db_session, monkeypatch) -> None:
    monkeypatch.setattr("app.core.entity_dedup._MAX_ENTITIES_PER_TYPE", 1)
    u = await _user(db_session)
    await _entity(db_session, u, "Petrov")
    await _entity(db_session, u, "Petrova")
    # Bucket capped to 1 -> no pairs -> no candidates (and no crash).
    assert await find_duplicate_entity_candidates(db_session, u.id, threshold=0.85) == []


# --- routes ------------------------------------------------------------------


async def _api_entity(client, auth_headers, name, type_="person") -> str:
    r = await client.post(
        "/api/entities", json={"type": type_, "name": name}, headers=auth_headers
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_merge_route_merges(client, auth_headers) -> None:
    keep = await _api_entity(client, auth_headers, "Petrova")
    drop = await _api_entity(client, auth_headers, "Petrov")
    r = await client.post(
        "/api/entities/merge", json={"keep_id": keep, "drop_id": drop}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert (await client.get(f"/api/entities/{drop}", headers=auth_headers)).status_code == 404
    assert (await client.get(f"/api/entities/{keep}", headers=auth_headers)).status_code == 200


async def test_merge_route_same_id_422(client, auth_headers) -> None:
    e = await _api_entity(client, auth_headers, "X")
    r = await client.post(
        "/api/entities/merge", json={"keep_id": e, "drop_id": e}, headers=auth_headers
    )
    assert r.status_code == 422


async def test_merge_route_unknown_404(client, auth_headers) -> None:
    keep = await _api_entity(client, auth_headers, "X")
    r = await client.post(
        "/api/entities/merge",
        json={"keep_id": keep, "drop_id": str(uuid4())},
        headers=auth_headers,
    )
    assert r.status_code == 404


async def test_merge_candidates_route_not_shadowed(client, auth_headers) -> None:
    # The literal path must resolve, not get captured by GET /{entity_id} (UUID).
    await _api_entity(client, auth_headers, "Petrova")
    await _api_entity(client, auth_headers, "Petrov")
    r = await client.get(
        "/api/entities/merge-candidates?threshold=0.85", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert any(
        {c["keep_name"], c["drop_name"]} == {"Petrova", "Petrov"} for c in r.json()
    )
