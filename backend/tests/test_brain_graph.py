"""Tests for the Brain knowledge-graph builder + GET /api/brain/graph (Phase 3)."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core import memory_proposal as memory_proposal_core
from app.core.brain_graph import (
    _compile_overview,
    _compile_snapshot_payload,
    _snapshot_sections_to_dataclasses,
    _SourceMaterial,
    build_brain_graph,
    build_brain_overview,
    build_entity_page,
)
from app.core.entity_graph import (
    backfill_entity_mentions_from_existing_summaries,
    record_mention,
    upsert_entity,
)
from app.core.item_ingest import ingest_item
from app.models.entity import Entity, EntityPageSnapshot
from app.models.item import ItemSummary
from app.models.recording import ActionItem, Recording, RecordingStatus, Summary
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


async def test_backfill_entity_mentions_from_existing_summaries_is_zero_token_and_idempotent(
    db_session,
) -> None:
    user = await _make_user(db_session)
    recording = Recording(
        user_id=user.id,
        title="Launch sync",
        type="meeting",
        status=RecordingStatus.READY.value,
    )
    db_session.add(recording)
    item, _ = await ingest_item(
        db_session,
        user.id,
        source="paste",
        title="Launch memo",
        body="Anna owns the GPU launch.",
        embed=False,
    )
    await db_session.flush()
    db_session.add(
        Summary(
            recording_id=recording.id,
            summary="Anna discussed GPU launch work.",
            topics=["GPU launch"],
            people_mentioned=["Anna"],
        )
    )
    db_session.add(
        ItemSummary(
            item_id=item.id,
            summary="Anna owns GPU launch work.",
            topics=["GPU launch"],
            people_mentioned=["Anna"],
        )
    )
    await db_session.flush()

    first = await backfill_entity_mentions_from_existing_summaries(db_session, user.id)
    second = await backfill_entity_mentions_from_existing_summaries(db_session, user.id)

    assert first.recording_summaries_scanned == 1
    assert first.item_summaries_scanned == 1
    assert first.created_mentions == 4
    assert first.llm_requests == 0
    assert second.created_mentions == 0
    assert second.llm_requests == 0

    g = await build_brain_graph(db_session, user.id, include_sources=True)
    assert g.stats["recordings"] == 1
    assert g.stats["items"] == 1
    assert g.stats["mentions"] == 4


async def test_brain_overview_exposes_coverage_and_pending_review(db_session) -> None:
    user = await _make_user(db_session)
    organized = Recording(
        user_id=user.id,
        title="Organized sync",
        type="meeting",
        status=RecordingStatus.READY.value,
    )
    unorganized = Recording(
        user_id=user.id,
        title="Not summarized yet",
        type="meeting",
        status=RecordingStatus.READY.value,
    )
    db_session.add_all([organized, unorganized])
    item, _ = await ingest_item(
        db_session,
        user.id,
        source="paste",
        title="GPU memo",
        body="Anna owns GPU launch work.",
        embed=False,
    )
    await db_session.flush()
    db_session.add(
        Summary(
            recording_id=organized.id,
            summary="Anna discussed GPU launch work.",
            topics=["GPU launch"],
            people_mentioned=["Anna"],
        )
    )
    db_session.add(
        ItemSummary(
            item_id=item.id,
            summary="Anna owns GPU launch work.",
            topics=["GPU launch"],
            people_mentioned=["Anna"],
        )
    )
    await db_session.flush()
    await backfill_entity_mentions_from_existing_summaries(db_session, user.id)
    await memory_proposal_core.propose_block_update(
        db_session,
        user.id,
        block_label="human",
        operation="rewrite",
        content="Anna is the launch owner.",
        confidence=0.95,
        evidence=[{"source_kind": "recording", "source_id": str(organized.id)}],
    )

    overview = await build_brain_overview(db_session, user.id)

    assert overview.recordings.total == 2
    assert overview.recordings.summarized == 1
    assert overview.recordings.organized == 1
    assert overview.recordings.unorganized == 1
    assert overview.materials.total == 1
    assert overview.materials.summarized == 1
    assert overview.materials.organized == 1
    assert overview.materials.unorganized == 0
    assert overview.pending_review_count == 1
    assert overview.llm_requests == 0
    assert {entity.name for entity in overview.top_entities} >= {"Anna", "GPU launch"}


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
    assert data["overview"]["pending_review_count"] == 0


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


async def test_build_entity_page_compiles_structured_cached_wiki_page(db_session) -> None:
    user = await _make_user(db_session)
    item, _ = await ingest_item(
        db_session,
        user.id,
        source="paste",
        title="GPU launch note",
        body="Anna owns the GPU launch. What ships first?",
        embed=False,
    )
    db_session.add(
        ItemSummary(
            item_id=item.id,
            summary="Anna owns the GPU launch and needs to confirm the launch date.",
            key_points=["Anna owns the GPU launch."],
            action_items=[{"task": "Ask Anna for the launch date", "owner": "Mik"}],
            highlights=[
                {
                    "category": "question",
                    "title": "What GPU ships first?",
                    "description": "The launch SKU is still open.",
                }
            ],
            key_moments=[
                {
                    "title": "GPU launch ownership",
                    "summary": "Anna was assigned ownership of the launch.",
                }
            ],
        )
    )

    recording = Recording(
        user_id=user.id,
        title="Launch sync",
        type="meeting",
        status=RecordingStatus.READY.value,
    )
    db_session.add(recording)
    await db_session.flush()
    db_session.add(
        Summary(
            recording_id=recording.id,
            summary="The team reviewed GPU launch dependencies.",
            key_points=["Launch dependencies need a decision."],
            decisions=[{"decision": "Use Anna as the launch owner."}],
            topics=["GPU launch"],
            people_mentioned=["Anna"],
        )
    )
    db_session.add(
        ActionItem(
            recording_id=recording.id,
            task="Prepare Anna's launch checklist",
            owner="Mik",
            status="pending",
        )
    )

    anna = await upsert_entity(db_session, user.id, type="person", name="Anna")
    gpu = await upsert_entity(db_session, user.id, type="topic", name="GPU")
    await record_mention(
        db_session,
        user_id=user.id,
        entity_id=anna.id,
        source_kind="item",
        source_id=item.id,
        context="Anna owns the GPU launch.",
    )
    await record_mention(
        db_session,
        user_id=user.id,
        entity_id=gpu.id,
        source_kind="item",
        source_id=item.id,
        context="GPU launch planning.",
    )
    await record_mention(
        db_session,
        user_id=user.id,
        entity_id=anna.id,
        source_kind="recording",
        source_id=recording.id,
        context="Anna is the launch owner.",
    )

    page = await build_entity_page(db_session, user.id, anna.id)

    assert page is not None
    assert page.overview
    assert "Anna appears in 2 sources." in page.overview
    anna_fact = next(fact for fact in page.facts if fact.text == "Anna owns the GPU launch.")
    assert anna_fact.citation_ids
    assert {c.title for c in page.citations} == {"GPU launch note", "Launch sync"}
    assert any(event.title == "GPU launch ownership" for event in page.timeline)
    assert any(question.text == "What GPU ships first?" for question in page.questions)
    assert any(action.text == "Ask Anna for the launch date" for action in page.actions)
    assert any(action.text == "Prepare Anna's launch checklist" for action in page.actions)
    explanation = next(r for r in page.related_explanations if r.name == "GPU")
    assert "GPU launch note" in explanation.explanation
    assert page.cache_status == "rebuilt"

    snapshots = (
        await db_session.execute(
            select(EntityPageSnapshot).where(EntityPageSnapshot.entity_id == anna.id)
        )
    ).scalars().all()
    assert len(snapshots) == 1
    fingerprint = snapshots[0].source_fingerprint

    cached = await build_entity_page(db_session, user.id, anna.id)
    assert cached is not None
    assert cached.cache_status == "hit"
    snapshots_after = (
        await db_session.execute(
            select(EntityPageSnapshot).where(EntityPageSnapshot.entity_id == anna.id)
        )
    ).scalars().all()
    assert len(snapshots_after) == 1
    assert snapshots_after[0].source_fingerprint == fingerprint

    summary = (
        await db_session.execute(select(Summary).where(Summary.recording_id == recording.id))
    ).scalar_one()
    summary.key_points = [*summary.key_points, "Cache refreshes after source changes."]
    await db_session.flush()

    refreshed = await build_entity_page(db_session, user.id, anna.id)
    assert refreshed is not None
    assert refreshed.cache_status == "rebuilt"
    assert any(
        fact.text == "Cache refreshes after source changes." for fact in refreshed.facts
    )
    refreshed_snapshot = (
        await db_session.execute(
            select(EntityPageSnapshot).where(EntityPageSnapshot.entity_id == anna.id)
        )
    ).scalar_one()
    assert refreshed_snapshot.source_fingerprint != fingerprint


async def test_entity_page_snapshot_compiler_limits_and_deduplicates_sections() -> None:
    entity = Entity(id=uuid4(), user_id=uuid4(), type="topic", name="Launch")
    source = _SourceMaterial(
        source_kind="item",
        source_id=uuid4(),
        title="Planning note",
        context="What is the launch owner? What is the launch date?",
        occurred_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
        summary="Launch planning summary. Extra sentence.",
        key_points=[
            {"text": "Launch has an owner."},
            {"text": "Launch has an owner."},
            None,
        ],
        decisions=[{"decision": "Ship with the current launch owner."}],
        action_items=[
            {"task": f"Prepare launch checklist {index}", "owner": "Mik"}
            for index in range(13)
        ] + [123, {"task": ""}],
        highlights=[
            {"category": "question", "title": f"Question {index}?"}
            for index in range(10)
        ],
        key_moments=[
            {"title": f"Moment {index}", "summary": f"Moment {index} detail"}
            for index in range(12)
        ],
    )

    payload = _compile_snapshot_payload(entity, [source], [])

    assert payload["overview"].startswith("Launch appears in 1 source.")
    assert [fact["text"] for fact in payload["facts"]] == [
        "Launch has an owner.",
        "Ship with the current launch owner.",
    ]
    assert len(payload["timeline"]) == 10
    assert len(payload["questions"]) == 8
    assert len(payload["actions"]) == 12
    assert payload["actions"][0]["owner"] == "Mik"
    facts, citations, timeline, related, questions, actions = _snapshot_sections_to_dataclasses(
        payload
    )
    assert facts[0].text == "Launch has an owner."
    assert citations[0].title == "Planning note"
    assert timeline[0].title == "Moment 0"
    assert related == []
    assert questions[0].text == "Question 0?"
    assert actions[0].text == "Prepare launch checklist 0"


async def test_entity_page_snapshot_compiler_uses_context_fallbacks() -> None:
    entity = Entity(id=uuid4(), user_id=uuid4(), type="project", name="Archive")
    source = _SourceMaterial(
        source_kind="recording",
        source_id=uuid4(),
        title="Untitled recording",
        context="Archive context fact. Who owns archival review?",
        occurred_at=None,
        updated_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
        summary=None,
        key_points=[],
        decisions=[],
        action_items=[{"text": "Review archive"}, {"text": "Review archive"}, 123, {}],
        highlights=[],
        key_moments=[],
    )

    payload = _compile_snapshot_payload(entity, [source], [])

    assert _compile_overview(entity, []) == "Archive has no linked sources yet."
    assert payload["overview"].endswith("Who owns archival review?")
    assert payload["facts"][0]["text"] == "Archive context fact. Who owns archival review?"
    assert payload["timeline"][0]["title"] == "Mentioned in Untitled recording"
    assert payload["questions"][0]["text"] == (
        "Archive context fact. Who owns archival review?"
    )
    assert payload["actions"] == [
        {
            "id": "action-1",
            "text": "Review archive",
            "owner": None,
            "due_date": None,
            "status": None,
            "citation_ids": [source.citation_id],
        }
    ]


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
    assert data["facts"] == []
    assert data["citations"] == []
    assert data["timeline"] == []
    assert data["related_explanations"] == []
    assert data["questions"] == []
    assert data["actions"] == []
