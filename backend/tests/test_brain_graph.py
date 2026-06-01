"""Tests for the Brain knowledge-graph builder + GET /api/brain/graph (Phase 3)."""

from uuid import uuid4

import pytest

from app.core.brain_graph import build_brain_graph
from app.core.entity_graph import record_mention, upsert_entity
from app.core.item_ingest import ingest_item
from app.models.recording import Recording, RecordingStatus
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"bg-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


def _pair(a, b) -> tuple[str, str]:
    return tuple(sorted((str(a), str(b))))


async def test_empty_graph_is_honest(db_session) -> None:
    user = await _make_user(db_session)
    g = await build_brain_graph(db_session, user.id)
    assert g.nodes == []
    assert g.edges == []
    assert g.stats["entities"] == 0


async def test_cooccurrence_edges_from_shared_sources(db_session) -> None:
    user = await _make_user(db_session)
    a_src, b_src = uuid4(), uuid4()
    anna = await upsert_entity(db_session, user.id, type="person", name="Anna")
    gpu = await upsert_entity(db_session, user.id, type="topic", name="GPU")
    pricing = await upsert_entity(db_session, user.id, type="topic", name="Pricing")
    # Source A: Anna + GPU. Source B: Anna + Pricing.
    for ent, src in [(anna, a_src), (gpu, a_src), (anna, b_src), (pricing, b_src)]:
        await record_mention(
            db_session, user_id=user.id, entity_id=ent.id, source_kind="item", source_id=src
        )

    g = await build_brain_graph(db_session, user.id, include_sources=False)

    entity_ids = {n.id for n in g.nodes}
    assert {str(anna.id), str(gpu.id), str(pricing.id)} <= entity_ids
    cooc = {(e.source, e.target) for e in g.edges if e.type == "cooccurrence"}
    assert _pair(anna.id, gpu.id) in cooc
    assert _pair(anna.id, pricing.id) in cooc
    assert _pair(gpu.id, pricing.id) not in cooc  # never shared a source
    anna_node = next(n for n in g.nodes if n.id == str(anna.id))
    assert anna_node.degree == 2  # mentioned by two sources


async def test_graph_includes_item_and_recording_source_nodes(db_session) -> None:
    user = await _make_user(db_session)
    item, _ = await ingest_item(
        db_session, user.id, source="paste", title="Solar Note", body="about solar", embed=False
    )
    rec = Recording(user_id=user.id, type="note", status=RecordingStatus.READY.value)
    db_session.add(rec)
    await db_session.flush()

    anna = await upsert_entity(db_session, user.id, type="person", name="Anna")
    await record_mention(
        db_session, user_id=user.id, entity_id=anna.id, source_kind="item", source_id=item.id
    )
    await record_mention(
        db_session, user_id=user.id, entity_id=anna.id, source_kind="recording", source_id=rec.id
    )

    g = await build_brain_graph(db_session, user.id, include_sources=True)

    kinds = {n.kind for n in g.nodes}
    assert {"person", "item", "recording"} <= kinds
    item_node = next(n for n in g.nodes if n.kind == "item")
    assert item_node.id == f"item:{item.id}"
    assert item_node.label == "Solar Note"

    mention_edges = {(e.source, e.target) for e in g.edges if e.type == "mention"}
    assert (f"item:{item.id}", str(anna.id)) in mention_edges
    assert (f"recording:{rec.id}", str(anna.id)) in mention_edges
    assert g.stats["items"] == 1
    assert g.stats["recordings"] == 1


async def test_focus_returns_only_the_ego_graph(db_session) -> None:
    user = await _make_user(db_session)
    shared = uuid4()
    anna = await upsert_entity(db_session, user.id, type="person", name="Anna")
    gpu = await upsert_entity(db_session, user.id, type="topic", name="GPU")
    bob = await upsert_entity(db_session, user.id, type="person", name="Bob")
    await record_mention(
        db_session, user_id=user.id, entity_id=anna.id, source_kind="item", source_id=shared
    )
    await record_mention(
        db_session, user_id=user.id, entity_id=gpu.id, source_kind="item", source_id=shared
    )
    # Bob lives on a different source — not connected to Anna.
    await record_mention(
        db_session, user_id=user.id, entity_id=bob.id, source_kind="item", source_id=uuid4()
    )

    g = await build_brain_graph(db_session, user.id, focus=anna.id, include_sources=False)
    ids = {n.id for n in g.nodes}
    assert str(anna.id) in ids
    assert str(gpu.id) in ids  # neighbor via the shared source
    assert str(bob.id) not in ids  # unconnected -> excluded from the ego graph


async def test_brain_graph_route_smoke(client, auth_headers) -> None:
    resp = await client.get("/api/brain/graph", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert {"nodes", "edges", "stats"} <= set(data)
    assert data["stats"]["entities"] == 0  # fresh user -> honest empty graph
