"""Tests for the Brain knowledge-graph builder + GET /api/brain/graph (Phase 3)."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.brain_graph import build_brain_graph, build_entity_page
from app.core.entity_graph import record_mention, upsert_entity
from app.core.item_ingest import ingest_item
from app.models.brain_space import BrainReviewPack, BrainSpace
from app.models.item import ItemSummary
from app.models.recording import Recording, RecordingStatus, Summary
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


async def test_graph_overview_reports_source_coverage(db_session) -> None:
    user = await _make_user(db_session)
    organized_rec = Recording(
        user_id=user.id,
        title="Launch voice memo",
        type="note",
        status=RecordingStatus.READY.value,
    )
    unorganized_rec = Recording(
        user_id=user.id,
        title="Raw project voice memo",
        type="note",
        status=RecordingStatus.READY.value,
    )
    db_session.add_all([organized_rec, unorganized_rec])
    await db_session.flush()
    db_session.add(
        Summary(
            recording_id=organized_rec.id,
            summary="Launch memo summary",
            key_points=[],
            decisions=[],
            topics=[],
            people_mentioned=[],
        )
    )
    item, _ = await ingest_item(
        db_session,
        user.id,
        source="paste",
        title="Project material",
        body="Anna owns launch",
        embed=False,
    )
    db_session.add(
        ItemSummary(
            item_id=item.id,
            summary="Project material summary",
            key_points=[],
            decisions=[],
            action_items=[],
            topics=[],
            people_mentioned=[],
            highlights=[],
            key_moments=[],
        )
    )
    space = BrainSpace(
        owner_user_id=user.id,
        name="Personal",
        slug=f"personal-{uuid4().hex}",
        kind="personal",
        engine_profile="waibrain",
        visibility="private",
    )
    db_session.add(space)
    await db_session.flush()
    db_session.add(
        BrainReviewPack(
            space_id=space.id,
            title="Review launch claims",
            summary="Needs review",
            proposals=[],
            evidence=[],
            created_by_user_id=user.id,
        )
    )

    anna = await upsert_entity(db_session, user.id, type="person", name="Anna")
    launch = await upsert_entity(db_session, user.id, type="project", name="Launch")
    await record_mention(
        db_session,
        user_id=user.id,
        entity_id=anna.id,
        source_kind="recording",
        source_id=organized_rec.id,
    )
    await record_mention(
        db_session,
        user_id=user.id,
        entity_id=launch.id,
        source_kind="recording",
        source_id=organized_rec.id,
    )
    await record_mention(
        db_session,
        user_id=user.id,
        entity_id=anna.id,
        source_kind="item",
        source_id=item.id,
    )

    graph = await build_brain_graph(db_session, user.id, include_sources=True)

    assert graph.overview is not None
    assert graph.overview.recordings.total == 2
    assert graph.overview.recordings.summarized == 1
    assert graph.overview.recordings.organized == 1
    assert graph.overview.recordings.unorganized == 1
    assert graph.overview.materials.total == 1
    assert graph.overview.materials.summarized == 1
    assert graph.overview.materials.organized == 1
    assert graph.overview.materials.unorganized == 0
    assert graph.overview.pending_review_count == 1
    assert graph.overview.llm_requests == 0

    anna_overview = next(entity for entity in graph.overview.top_entities if entity.name == "Anna")
    assert anna_overview.source_count == 2
    assert anna_overview.recording_count == 1
    assert anna_overview.material_count == 1

    recent_by_id = {source.id: source for source in graph.overview.recent_sources}
    assert recent_by_id[f"recording:{organized_rec.id}"].entity_count == 2
    assert recent_by_id[f"recording:{organized_rec.id}"].organized_at is not None
    assert recent_by_id[f"recording:{unorganized_rec.id}"].entity_count == 0
    assert recent_by_id[f"recording:{unorganized_rec.id}"].organized_at is None
    assert recent_by_id[f"item:{item.id}"].title == "Project material"


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
    assert {"nodes", "edges", "stats", "overview"} <= set(data)
    assert data["stats"]["entities"] == 0  # fresh user -> honest empty graph
    assert data["overview"]["recordings"]["total"] == 0
    assert data["overview"]["materials"]["total"] == 0


async def test_brain_sync_route_backfills_existing_summary_entities(
    client, db_session
) -> None:
    email = f"brain-sync-{uuid4().hex}@example.com"
    registered = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "testpassword123",
            "accepted_legal_terms": True,
            "legal_terms_version": "2026-05-22",
            "legal_privacy_version": "2026-05-22",
        },
    )
    assert registered.status_code == 200, registered.text
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    user = (
        await db_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    recording = Recording(
        user_id=user.id,
        title="Legacy voice memo",
        type="note",
        status=RecordingStatus.READY.value,
    )
    db_session.add(recording)
    await db_session.flush()
    db_session.add(
        Summary(
            recording_id=recording.id,
            summary="Mik discussed the roadmap.",
            key_points=[],
            decisions=[],
            topics=["Roadmap"],
            people_mentioned=["Mik"],
        )
    )
    item, _ = await ingest_item(
        db_session,
        user.id,
        source="paste",
        title="Legacy material",
        body="Anna owns launch planning",
        embed=False,
    )
    db_session.add(
        ItemSummary(
            item_id=item.id,
            summary="Anna owns launch planning.",
            key_points=[],
            decisions=[],
            action_items=[],
            topics=["Launch"],
            people_mentioned=["Anna"],
            highlights=[],
            key_moments=[],
        )
    )
    await db_session.flush()

    synced = await client.post("/api/brain/sync", json={"limit": 20}, headers=headers)
    assert synced.status_code == 200, synced.text
    payload = synced.json()
    assert payload["recording_summaries_scanned"] == 1
    assert payload["item_summaries_scanned"] == 1
    assert payload["sources_with_entities"] == 2
    assert payload["created_mentions"] == 4
    assert payload["llm_requests"] == 0

    graph = await client.get("/api/brain/graph", headers=headers)
    assert graph.status_code == 200, graph.text
    overview = graph.json()["overview"]
    assert overview["recordings"]["organized"] == 1
    assert overview["recordings"]["unorganized"] == 0
    assert overview["materials"]["organized"] == 1
    assert overview["materials"]["unorganized"] == 0
    assert {entity["name"] for entity in overview["top_entities"]} >= {
        "Mik",
        "Anna",
        "Roadmap",
        "Launch",
    }


async def test_build_entity_page_sources_and_related(db_session) -> None:
    user = await _make_user(db_session)
    item1, _ = await ingest_item(
        db_session, user.id, source="paste", title="GPU note", body="x", embed=False
    )
    item2, _ = await ingest_item(
        db_session, user.id, source="paste", title="Second", body="y", embed=False
    )
    anna = await upsert_entity(db_session, user.id, type="person", name="Anna")
    gpu = await upsert_entity(db_session, user.id, type="topic", name="GPU")
    # Anna + GPU share item1 (co-occurrence); Anna is also in item2.
    await record_mention(
        db_session, user_id=user.id, entity_id=anna.id, source_kind="item",
        source_id=item1.id, context="Anna leads it",
    )
    await record_mention(
        db_session, user_id=user.id, entity_id=gpu.id, source_kind="item", source_id=item1.id
    )
    await record_mention(
        db_session, user_id=user.id, entity_id=anna.id, source_kind="item", source_id=item2.id
    )

    page = await build_entity_page(db_session, user.id, anna.id)
    assert page is not None
    assert page.name == "Anna" and page.mention_count == 2
    assert {s.title for s in page.sources} == {"GPU note", "Second"}
    assert "Anna leads it" in {s.context for s in page.sources}
    related = {r.name: r.shared for r in page.related}
    assert related.get("GPU") == 1  # shared item1
    assert "Anna" not in related  # never lists itself
    assert page.overview == "Anna appears in 2 sources."
    assert {c.title for c in page.citations} == {"GPU note", "Second"}
    assert page.related_explanations[0].name == "GPU"
    assert page.related_explanations[0].explanation == "Shares 1 source with Anna."
    assert page.facts == []
    assert page.timeline == []
    assert page.questions == []
    assert page.actions == []
    # Has sources but no compiled snapshot yet -> awaiting synthesis.
    assert page.cache_status == "stale"


async def test_build_entity_page_missing_returns_none(db_session) -> None:
    user = await _make_user(db_session)
    assert await build_entity_page(db_session, user.id, uuid4()) is None


async def test_entity_page_route_404_for_unknown(client, auth_headers) -> None:
    resp = await client.get(f"/api/entities/{uuid4()}/page", headers=auth_headers)
    assert resp.status_code == 404


async def test_entity_page_route_200_for_owned_entity(client, auth_headers) -> None:
    created = await client.post(
        "/api/entities", json={"type": "topic", "name": "Roadmaps"}, headers=auth_headers
    )
    assert created.status_code == 201, created.text
    eid = created.json()["id"]
    resp = await client.get(f"/api/entities/{eid}/page", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["name"] == "Roadmaps"
    assert data["mention_count"] == 0
    assert data["sources"] == [] and data["related"] == []
    assert data["overview"] == "Roadmaps has not appeared in any sources yet."
    assert data["facts"] == []
    assert data["citations"] == []
    assert data["timeline"] == []
    assert data["related_explanations"] == []
    assert data["questions"] == []
    assert data["actions"] == []
    # No sources at all -> honest skeleton, never an LLM call.
    assert data["cache_status"] == "skeleton"
