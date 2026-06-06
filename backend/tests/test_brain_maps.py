"""Tests for live Brain Maps: cited projections, refresh diffs, and agent access."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.core.agent_runtime as agent_runtime
import app.core.brain_maps as brain_maps
from app.core.agent_runtime import execute_agent_step
from app.core.brain_maps import create_brain_map, refresh_brain_map
from app.core.entity_graph import record_mention, upsert_entity
from app.core.item_ingest import ingest_item
from app.models.agent import Agent, AgentRun
from app.models.recording import Recording, Segment, Summary
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"brain-map-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


def _hit(*, kind: str, parent_id, chunk_id=None, title: str, snippet: str):
    return SimpleNamespace(
        source_kind=kind,
        parent_id=str(parent_id),
        chunk_id=str(chunk_id or uuid4()),
        title=title,
        kind="note",
        snippet=snippet,
        score=0.9,
        created_at="2026-06-05T10:00:00Z",
    )


async def test_create_brain_map_creates_cited_draft_projection(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    item, _ = await ingest_item(
        db_session,
        user.id,
        source="paste",
        title="Launch notes",
        body="Product Radar launch needs pricing review.",
        embed=False,
    )
    product_radar = await upsert_entity(
        db_session, user.id, type="project", name="Product Radar"
    )
    await record_mention(
        db_session,
        user_id=user.id,
        entity_id=product_radar.id,
        source_kind="item",
        source_id=item.id,
        context="Product Radar launch needs pricing review.",
    )

    async def fake_search(*_args, **_kwargs):
        return [
            _hit(
                kind="item",
                parent_id=item.id,
                title="Launch notes",
                snippet="Product Radar launch needs pricing review.",
            )
        ]

    monkeypatch.setattr(brain_maps, "unified_search", fake_search)

    brain_map, revision = await create_brain_map(
        db_session,
        user.id,
        prompt="Map the Product Radar launch",
        origin="brain",
    )

    assert brain_map.status == "draft"
    assert brain_map.map_type == "project_state"
    assert brain_map.current_revision_id == revision.id
    projection = revision.projection
    assert projection["title"] == "Map the Product Radar launch"
    assert any(n["kind"] == "lens" for n in projection["nodes"])
    entity_node = next(n for n in projection["nodes"] if n["kind"] == "entity")
    assert entity_node["title"] == "Product Radar"
    assert entity_node["citation_ids"] == [f"item:{item.id}"]
    source_node = next(n for n in projection["nodes"] if n["kind"] == "source")
    assert source_node["source_kind"] == "item"
    assert source_node["source_id"] == str(item.id)
    assert any(e["kind"] == "mentions" for e in projection["edges"])
    assert revision.source_count == 1


@pytest.mark.parametrize(
    ("prompt", "expected_type"),
    [
        (
            "Map my active projects with owners, risks, decisions, and next steps",
            "project_state",
        ),
        (
            "Map recent decisions with options, tradeoffs, blockers, and open questions",
            "decision",
        ),
        (
            "Map people, projects, and relationships that matter right now",
            "relationship",
        ),
        (
            "Create a timeline of the important changes, commitments, and deadlines",
            "timeline",
        ),
    ],
)
async def test_scenario_template_prompts_create_expected_map_types(
    db_session,
    monkeypatch,
    prompt,
    expected_type,
) -> None:
    user = await _make_user(db_session)

    async def fake_search(*_args, **_kwargs):
        return []

    monkeypatch.setattr(brain_maps, "unified_search", fake_search)

    brain_map, revision = await create_brain_map(
        db_session,
        user.id,
        prompt=prompt,
        origin="brain",
    )

    assert brain_map.map_type == expected_type
    assert revision.projection["map_type"] == expected_type
    assert revision.projection["briefing"]["suggested_questions"]


async def test_refresh_brain_map_creates_revision_diff_and_preserves_layout(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    item1, _ = await ingest_item(
        db_session, user.id, source="paste", title="Alpha", body="Anna owns Alpha.", embed=False
    )
    item2, _ = await ingest_item(
        db_session, user.id, source="paste", title="Beta", body="Anna reviews Beta.", embed=False
    )
    anna = await upsert_entity(db_session, user.id, type="person", name="Anna")
    await record_mention(
        db_session,
        user_id=user.id,
        entity_id=anna.id,
        source_kind="item",
        source_id=item1.id,
        context="Anna owns Alpha.",
    )
    await record_mention(
        db_session,
        user_id=user.id,
        entity_id=anna.id,
        source_kind="item",
        source_id=item2.id,
        context="Anna reviews Beta.",
    )

    calls = {"n": 0}

    async def fake_search(*_args, **_kwargs):
        calls["n"] += 1
        hits = [_hit(kind="item", parent_id=item1.id, title="Alpha", snippet="Anna owns Alpha.")]
        if calls["n"] >= 2:
            hits.append(
                _hit(kind="item", parent_id=item2.id, title="Beta", snippet="Anna reviews Beta.")
            )
        return hits

    monkeypatch.setattr(brain_maps, "unified_search", fake_search)

    brain_map, first = await create_brain_map(db_session, user.id, prompt="Map Anna")
    brain_map.layout = {"entity:" + str(anna.id): {"x": 240, "y": 80}}
    await db_session.flush()

    second = await refresh_brain_map(db_session, user.id, brain_map.id)

    assert first.id != second.id
    assert second.revision_index == 2
    assert brain_map.layout == {"entity:" + str(anna.id): {"x": 240, "y": 80}}
    assert second.diff["sources_added"] == 1
    assert second.diff["nodes_added"] >= 1
    assert brain_map.current_revision_id == second.id


async def test_source_scope_seeds_map_from_selected_inbox_source(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    item, _ = await ingest_item(
        db_session,
        user.id,
        source="paste",
        title="Board decisions",
        body="Board approved the hiring plan.",
        embed=False,
    )

    async def fake_search(*_args, **_kwargs):
        return []

    monkeypatch.setattr(brain_maps, "unified_search", fake_search)

    brain_map, revision = await create_brain_map(
        db_session,
        user.id,
        prompt="Map this source",
        origin="inbox",
        source_scope={"sources": [{"source_kind": "item", "source_id": str(item.id)}]},
    )

    source_node = next(n for n in revision.projection["nodes"] if n["kind"] == "source")
    assert brain_map.origin == "inbox"
    assert source_node["title"] == "Board decisions"
    assert source_node["source_id"] == str(item.id)
    assert revision.source_count == 1


async def test_source_scope_seeds_map_from_selected_inbox_voice_memo(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    recording = Recording(
        user_id=user.id,
        title="Voice memo about active projects",
        type="note",
        status="ready",
    )
    db_session.add(recording)
    await db_session.flush()
    db_session.add_all(
        [
            Summary(
                recording_id=recording.id,
                summary="Project Atlas launch has a staffing risk.",
                key_points=None,
                decisions=None,
                topics=None,
                people_mentioned=None,
                sentiment=None,
            ),
            Segment(
                recording_id=recording.id,
                content="Decision: launch Project Atlas after the security review.",
                speaker=None,
                raw_label=None,
                start_ms=0,
                end_ms=3000,
                confidence=None,
            ),
            Segment(
                recording_id=recording.id,
                content="Next step: ask Anna to confirm the rollout owner.",
                speaker=None,
                raw_label=None,
                start_ms=3000,
                end_ms=6000,
                confidence=None,
            ),
        ]
    )
    await db_session.flush()

    async def fake_search(*_args, **_kwargs):
        return []

    monkeypatch.setattr(brain_maps, "unified_search", fake_search)

    brain_map, revision = await create_brain_map(
        db_session,
        user.id,
        prompt="Map this voice memo",
        origin="inbox",
        source_scope={"sources": [{"source_kind": "recording", "source_id": str(recording.id)}]},
    )

    source_node = next(n for n in revision.projection["nodes"] if n["kind"] == "source")
    assert brain_map.origin == "inbox"
    assert source_node["source_kind"] == "recording"
    assert source_node["source_id"] == str(recording.id)
    assert source_node["title"] == "Voice memo about active projects"
    assert "Project Atlas" in source_node["body"]
    assert "security review" in source_node["body"]
    assert revision.source_count == 1


async def test_map_search_uses_wider_chunk_pool_and_deduplicates_sources(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    first_recording_id = uuid4()
    second_recording_id = uuid4()
    item_id = uuid4()
    calls: list[int] = []

    async def fake_search(_db, _user_id, _prompt, *, limit):
        calls.append(limit)
        return [
            _hit(
                kind="recording",
                parent_id=first_recording_id,
                chunk_id=uuid4(),
                title="Long voice memo",
                snippet=f"Repeated project segment {index}",
            )
            for index in range(5)
        ] + [
            _hit(
                kind="recording",
                parent_id=second_recording_id,
                title="Second voice memo",
                snippet="Another project from voice.",
            ),
            _hit(
                kind="item",
                parent_id=item_id,
                title="Planning note",
                snippet="Project note from inbox.",
            ),
        ]

    monkeypatch.setattr(brain_maps, "unified_search", fake_search)

    hits = await brain_maps._search_hits(
        db_session,
        user.id,
        "active projects",
        source_scope=None,
        limit=3,
    )

    assert calls == [3 * brain_maps.MAP_SEARCH_CHUNK_POOL_MULTIPLIER]
    assert [(hit.source_kind, hit.parent_id) for hit in hits] == [
        ("recording", str(first_recording_id)),
        ("recording", str(second_recording_id)),
        ("item", str(item_id)),
    ]


async def test_decision_map_adds_cited_scenario_signal_cards(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    item, _ = await ingest_item(
        db_session,
        user.id,
        source="paste",
        title="Hiring decision",
        body=(
            "Board approved the hiring plan. Risk: budget approval is not final. "
            "Next step: send the candidate offer. Open question: who owns onboarding?"
        ),
        embed=False,
    )

    async def fake_search(*_args, **_kwargs):
        return [
            _hit(
                kind="item",
                parent_id=item.id,
                title="Hiring decision",
                snippet=(
                    "Board approved the hiring plan. Risk: budget approval is not final. "
                    "Next step: send the candidate offer. Open question: who owns onboarding?"
                ),
            )
        ]

    monkeypatch.setattr(brain_maps, "unified_search", fake_search)

    _brain_map, revision = await create_brain_map(
        db_session,
        user.id,
        prompt="Map recent decisions with options, tradeoffs, blockers, and open questions",
        origin="brain",
    )
    projection = revision.projection
    signal_nodes = [
        n
        for n in projection["nodes"]
        if n["kind"] in {"decision", "risk", "next_step", "open_question"}
    ]
    citation_id = f"item:{item.id}"

    assert {node["kind"] for node in signal_nodes} == {
        "decision",
        "risk",
        "next_step",
        "open_question",
    }
    assert all(node["citation_ids"] == [citation_id] for node in signal_nodes)
    assert any(node["title"] == "Decision" and "approved" in node["body"] for node in signal_nodes)
    assert any(node["title"] == "Risk" and "budget" in node["body"] for node in signal_nodes)
    assert any(
        node["title"] == "Next step" and "candidate offer" in node["body"]
        for node in signal_nodes
    )
    assert any(
        node["title"] == "Open question" and "onboarding" in node["body"]
        for node in signal_nodes
    )


async def test_timeline_map_adds_event_and_deadline_signal_cards(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    item, _ = await ingest_item(
        db_session,
        user.id,
        source="paste",
        title="Launch timeline",
        body=(
            "On May 1 pricing changed for the launch plan. "
            "Deadline: publish the release notes by June 30."
        ),
        embed=False,
    )

    async def fake_search(*_args, **_kwargs):
        return [
            _hit(
                kind="item",
                parent_id=item.id,
                title="Launch timeline",
                snippet=(
                    "On May 1 pricing changed for the launch plan. "
                    "Deadline: publish the release notes by June 30."
                ),
            )
        ]

    monkeypatch.setattr(brain_maps, "unified_search", fake_search)

    _brain_map, revision = await create_brain_map(
        db_session,
        user.id,
        prompt="Create a timeline of the important changes, commitments, and deadlines",
        origin="brain",
    )
    signal_nodes = [
        n
        for n in revision.projection["nodes"]
        if n["kind"] in {"timeline_event", "deadline"}
    ]

    assert {node["kind"] for node in signal_nodes} == {"timeline_event", "deadline"}
    assert all(node["citation_ids"] == [f"item:{item.id}"] for node in signal_nodes)
    assert any("pricing changed" in node["body"] for node in signal_nodes)
    assert any("June 30" in node["body"] for node in signal_nodes)


async def test_projection_caps_large_brain_to_focused_diagram(db_session, monkeypatch) -> None:
    user = await _make_user(db_session)
    hits = []
    for index in range(12):
        item, _ = await ingest_item(
            db_session,
            user.id,
            source="paste",
            title=f"Source {index:02d}",
            body=f"Project {index} mentions Topic {index}.",
            embed=False,
        )
        project = await upsert_entity(
            db_session, user.id, type="project", name=f"Project {index:02d}"
        )
        topic = await upsert_entity(
            db_session, user.id, type="topic", name=f"Topic {index:02d}"
        )
        await record_mention(
            db_session,
            user_id=user.id,
            entity_id=project.id,
            source_kind="item",
            source_id=item.id,
            context=f"Project {index} mentions Topic {index}.",
        )
        await record_mention(
            db_session,
            user_id=user.id,
            entity_id=topic.id,
            source_kind="item",
            source_id=item.id,
            context=f"Project {index} mentions Topic {index}.",
        )
        hits.append(
            _hit(
                kind="item",
                parent_id=item.id,
                title=f"Source {index:02d}",
                snippet=f"Project {index} mentions Topic {index}.",
            )
        )

    async def fake_search(*_args, **_kwargs):
        return hits

    monkeypatch.setattr(brain_maps, "unified_search", fake_search)

    _brain_map, revision = await create_brain_map(
        db_session,
        user.id,
        prompt="Map everything",
        origin="brain",
    )
    projection = revision.projection
    source_nodes = [n for n in projection["nodes"] if n["kind"] == "source"]
    entity_nodes = [n for n in projection["nodes"] if n["kind"] == "entity"]

    assert len(source_nodes) == brain_maps.MAX_VISIBLE_SOURCE_NODES
    assert len(entity_nodes) == brain_maps.MAX_VISIBLE_ENTITY_NODES
    assert any(n["id"] == "gap:focused-diagram" for n in projection["nodes"])
    assert projection["stats"]["hidden_source_count"] == 9
    assert projection["stats"]["hidden_entity_count"] == 16
    assert projection["briefing"]["mode"] == "focused"
    assert (
        projection["briefing"]["focus_note"]
        == "Showing 3 of 12 source(s) and 8 of 24 linked node(s)."
    )
    assert projection["briefing"]["coverage"] == {
        "visible_sources": 3,
        "total_sources": 12,
        "visible_entities": 8,
        "total_entities": 24,
    }
    assert len(projection["briefing"]["top_sources"]) == 12
    assert len(projection["briefing"]["top_entities"]) == 12
    assert projection["briefing"]["top_sources"][0]["title"] == "Source 00"
    assert projection["briefing"]["suggested_questions"]


async def test_agent_runtime_can_create_brain_map(db_session, monkeypatch) -> None:
    user = await _make_user(db_session)
    item, _ = await ingest_item(
        db_session,
        user.id,
        source="paste",
        title="Roadmap",
        body="Roadmap risk is hiring.",
        embed=False,
    )

    async def fake_search(*_args, **_kwargs):
        return [
            _hit(
                kind="item",
                parent_id=item.id,
                title="Roadmap",
                snippet="Roadmap risk is hiring.",
            )
        ]

    monkeypatch.setattr(brain_maps, "unified_search", fake_search)
    monkeypatch.setattr(agent_runtime, "create_brain_map", brain_maps.create_brain_map)

    agent = Agent(
        user_id=user.id,
        name="mapper",
        kind="manual",
        trigger_type="chat",
        config={},
    )
    db_session.add(agent)
    await db_session.flush()
    run = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{uuid4()}",
        trigger_kind="manual",
    )
    db_session.add(run)
    await db_session.flush()

    result = await execute_agent_step(
        db_session,
        agent,
        run,
        {"tool": "create_brain_map", "args": {"prompt": "Map the roadmap risk"}},
        tool_call_idx=0,
        idempotency_key=f"{run.id}:map",
    )

    assert result.status == "done"
    assert result.payload["map_id"]
    assert result.payload["revision_id"]
    assert result.payload["status"] == "draft"
