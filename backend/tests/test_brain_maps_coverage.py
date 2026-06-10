"""Coverage push for app/core/brain_maps.py — helpers, CRUD, and projection edges.

Targets the uncovered blocks: list/update/load CRUD (1497-1518, 1576-1600),
related_to edges (1114-1134), scenario-signal projection edges (901/906/947),
scoped snippet helpers (500, 514-532, 553-556), recent hits (619/645), and the
pure prompt/freshness helpers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.core.brain_maps as brain_maps
from app.core.brain_maps import (
    BrainMapNotFoundError,
    BrainMapValidationError,
    create_brain_map,
    list_brain_map_revisions,
    list_brain_maps,
    load_brain_map,
    refresh_brain_map,
    update_brain_map,
)
from app.core.entity_graph import record_mention, upsert_entity
from app.core.item_ingest import ingest_item
from app.models.companion import ChatMessage, Conversation
from app.models.recording import Recording, Segment, Summary
from app.models.user import User


async def _make_user(db) -> User:
    user = User(email=f"bm-cov-{uuid4().hex}@example.com", password_hash="x")
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


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_shorten_truncates_long_text():
    out = brain_maps._shorten("word " * 100, 20)
    assert len(out) <= 20
    assert out.endswith("...")


def test_uuid_or_none_paths():
    value = uuid4()
    assert brain_maps._uuid_or_none(None) is None
    assert brain_maps._uuid_or_none(value) is value
    assert brain_maps._uuid_or_none(str(value)) == value
    assert brain_maps._uuid_or_none("not-a-uuid") is None


def test_choose_map_type_explicit_and_keywords():
    assert brain_maps._choose_map_type("anything", explicit="timeline") == "timeline"
    with pytest.raises(BrainMapValidationError):
        brain_maps._choose_map_type("anything", explicit="bogus-type")
    assert brain_maps._choose_map_type("compare these options") == "comparison"
    assert brain_maps._choose_map_type("what gaps are unknown here") == "open_questions"


def test_title_from_prompt_fallbacks():
    assert brain_maps._title_from_prompt("", "live_mirror") == "Live Mirror"
    assert brain_maps._title_from_prompt("", "project_state") == "Brain Map"
    assert brain_maps._title_from_prompt("map my work", "decision") == "Map my work"


def test_entity_lane_topics_fallback():
    assert brain_maps._entity_lane("project") == "projects"
    assert brain_maps._entity_lane("person") == "people"
    assert brain_maps._entity_lane("topic") == "topics"


def test_sentence_candidates_empty():
    assert brain_maps._sentence_candidates("   ") == []


def test_scenario_signals_for_hit_without_rules():
    hit = _hit(kind="item", parent_id=uuid4(), title="x", snippet="Approved the plan.")
    assert brain_maps._scenario_signals_for_hit("comparison", hit) == []


def test_chat_message_text_shapes():
    assert brain_maps._chat_message_text("  hello   world ") == "hello world"
    assert brain_maps._chat_message_text({"text": "from dict"}) == "from dict"
    assert brain_maps._chat_message_text(["plain string", {"text": "block"}]) == (
        "plain string block"
    )
    assert brain_maps._chat_message_text(42) == ""


def test_freshness_skips_unparseable_dates():
    citations = [
        {"created_at": None},
        {"created_at": "not-a-date"},
        {"created_at": "2026-06-01T00:00:00"},  # naive -> coerced to UTC
    ]
    freshness = brain_maps._freshness(citations)
    assert freshness["newest_source_at"] is not None
    assert freshness["weeks_since"] >= 0


def test_freshness_empty_when_no_dates():
    freshness = brain_maps._freshness([{"created_at": "garbage"}])
    assert freshness == {"newest_source_at": None, "weeks_since": None, "stale": False}


def test_suggested_questions_per_map_type():
    assert brain_maps._suggested_questions("comparison")
    assert brain_maps._suggested_questions("open_questions")
    assert brain_maps._suggested_questions("relationship")
    assert brain_maps._suggested_questions("timeline")
    assert brain_maps._suggested_questions("project_state")


def test_freshness_note_stale():
    note = brain_maps._freshness_note(
        {"newest_source_at": "2026-01-01T00:00:00+00:00", "weeks_since": 5}
    )
    assert note == "Newest evidence is 5 week(s) old."
    assert brain_maps._freshness_note({"newest_source_at": None}) == "No dated source yet."


# ---------------------------------------------------------------------------
# Scenario signal projection edges (direct calls)
# ---------------------------------------------------------------------------


def _signal_inputs(snippets: dict[uuid.UUID, str | None]):
    source_items = []
    hit_by_source = {}
    for source_id, snippet in snippets.items():
        key = ("item", source_id)
        source_items.append((key, {"id": f"item:{source_id}"}))
        if snippet is not None:
            hit_by_source[key] = _hit(
                kind="item", parent_id=source_id, title="src", snippet=snippet
            )
    return source_items, hit_by_source


def test_scenario_projection_skips_sources_without_hits():
    source_items, hit_by_source = _signal_inputs({uuid4(): None})
    nodes, edges = brain_maps._scenario_signal_projection(
        map_type="decision",
        source_items=source_items,
        hit_by_source=hit_by_source,
        layout=None,
        lens_id="lens:test",
        visible_source_node_ids=set(),
    )
    assert nodes == []
    assert edges == []


def test_scenario_projection_deduplicates_same_signal_body():
    first, second = uuid4(), uuid4()
    source_items, hit_by_source = _signal_inputs(
        {first: "Budget risk remains.", second: "Budget risk remains."}
    )
    nodes, _edges = brain_maps._scenario_signal_projection(
        map_type="open_questions",
        source_items=source_items,
        hit_by_source=hit_by_source,
        layout=None,
        lens_id="lens:test",
        visible_source_node_ids=set(),
    )
    assert len(nodes) == 1
    assert nodes[0]["kind"] == "risk"


def test_scenario_projection_caps_total_signal_nodes():
    first, second = uuid4(), uuid4()
    five_signals = (
        "We approved the launch. There is a tradeoff with cost. "
        "Budget risk remains. Next step is hiring. Open question about timing."
    )
    more_signals = (
        "They decided to ship early. An alternative is leasing. "
        "Vendor risk grows. Next step is auditing. Open question about scope."
    )
    source_items, hit_by_source = _signal_inputs(
        {first: five_signals, second: more_signals}
    )
    visible = {brain_maps._source_node_id("item", first)}
    nodes, edges = brain_maps._scenario_signal_projection(
        map_type="decision",
        source_items=source_items,
        hit_by_source=hit_by_source,
        layout=None,
        lens_id="lens:test",
        visible_source_node_ids=visible,
    )
    assert len(nodes) == brain_maps.MAX_SCENARIO_SIGNAL_NODES
    assert any(e["kind"] == "supports" for e in edges)


# ---------------------------------------------------------------------------
# Scoped snippets + recent hits (DB-backed)
# ---------------------------------------------------------------------------


async def test_scoped_recording_snippets_stop_after_char_budget(db_session):
    user = await _make_user(db_session)
    recording = Recording(user_id=user.id, title="Long memo", type="note", status="ready")
    db_session.add(recording)
    await db_session.flush()
    db_session.add_all(
        [
            Summary(
                recording_id=recording.id,
                summary="s" * (brain_maps.SCOPED_RECORDING_SNIPPET_CHARS + 50),
                key_points=None,
                decisions=None,
                topics=None,
                people_mentioned=None,
                sentiment=None,
            ),
            Segment(
                recording_id=recording.id,
                content="this segment is skipped because budget is exhausted",
                speaker=None,
                raw_label=None,
                start_ms=0,
                end_ms=1000,
                confidence=None,
            ),
        ]
    )
    await db_session.flush()

    snippets = await brain_maps._scoped_recording_snippets(db_session, {recording.id})
    assert "skipped" not in snippets[recording.id]
    assert len(snippets[recording.id]) <= brain_maps.SCOPED_RECORDING_SNIPPET_CHARS


async def test_scoped_chat_snippets_skip_empty_and_stop_at_budget(db_session):
    user = await _make_user(db_session)
    chat = Conversation(user_id=user.id, title="Thread")
    db_session.add(chat)
    await db_session.flush()
    base = datetime.now(timezone.utc)
    messages = [
        ChatMessage(
            conversation_id=chat.id,
            role="user",
            content="   ",
            created_at=base,
        )
    ]
    # Each message snippet is capped at 500 chars; three long ones exhaust the
    # 1200-char budget so the final message is skipped by the budget guard.
    for index in range(3):
        messages.append(
            ChatMessage(
                conversation_id=chat.id,
                role="user",
                content=f"filler {index} " + "x" * 600,
                created_at=base + timedelta(seconds=index + 1),
            )
        )
    messages.append(
        ChatMessage(
            conversation_id=chat.id,
            role="assistant",
            content="late reply",
            created_at=base + timedelta(seconds=10),
        )
    )
    db_session.add_all(messages)
    await db_session.flush()

    snippets = await brain_maps._scoped_chat_snippets(db_session, {chat.id})
    assert "late reply" not in snippets[chat.id]
    assert snippets[chat.id].startswith("User:")


async def test_recent_hits_include_items_recordings_and_chats(db_session):
    user = await _make_user(db_session)
    item, _ = await ingest_item(
        db_session,
        user.id,
        source="paste",
        title="Inbox note",
        body="Note body for recent hits.",
        embed=False,
    )
    recording = Recording(user_id=user.id, title="Memo", type="note", status="ready")
    chat = Conversation(user_id=user.id, title="Wai thread")
    db_session.add_all([recording, chat])
    await db_session.flush()
    db_session.add(
        ChatMessage(conversation_id=chat.id, role="assistant", content="chat snippet here")
    )
    await db_session.flush()

    hits = await brain_maps._recent_hits(db_session, user.id, limit=9)
    kinds = {hit.source_kind for hit in hits}
    assert kinds == {"item", "recording", "chat"}
    item_hit = next(h for h in hits if h.source_kind == "item")
    assert item_hit.parent_id == str(item.id)
    chat_hit = next(h for h in hits if h.source_kind == "chat")
    assert "chat snippet here" in chat_hit.snippet


# ---------------------------------------------------------------------------
# Related edges between entities sharing a source (1114-1134)
# ---------------------------------------------------------------------------


async def test_projection_links_entities_sharing_a_source(db_session, monkeypatch):
    user = await _make_user(db_session)
    item, _ = await ingest_item(
        db_session,
        user.id,
        source="paste",
        title="Team sync",
        body="Seven entities share this source.",
        embed=False,
    )
    for index in range(7):
        entity = await upsert_entity(
            db_session, user.id, type="topic", name=f"Shared Topic {index}"
        )
        await record_mention(
            db_session,
            user_id=user.id,
            entity_id=entity.id,
            source_kind="item",
            source_id=item.id,
            context="Seven entities share this source.",
        )

    async def fake_search(*_args, **_kwargs):
        return [
            _hit(
                kind="item",
                parent_id=item.id,
                title="Team sync",
                snippet="Seven entities share this source.",
            )
        ]

    monkeypatch.setattr(brain_maps, "unified_search", fake_search)

    _brain_map, revision = await create_brain_map(
        db_session, user.id, prompt="Map the team sync"
    )
    related = [e for e in revision.projection["edges"] if e["kind"] == "related_to"]
    assert len(related) == brain_maps.MAX_RELATED_EDGES
    assert revision.projection["stats"]["related_edges_capped"] == 1
    assert all(e["label"] == "shared source" for e in related)


# ---------------------------------------------------------------------------
# CRUD: list / update / revisions / not-found / unchanged refresh
# ---------------------------------------------------------------------------


async def test_list_brain_maps_filters_status_and_attaches_revisions(
    db_session, monkeypatch
):
    user = await _make_user(db_session)

    async def fake_search(*_args, **_kwargs):
        return []

    monkeypatch.setattr(brain_maps, "unified_search", fake_search)

    map_a, rev_a = await create_brain_map(db_session, user.id, prompt="Map A")
    map_b, _rev_b = await create_brain_map(db_session, user.id, prompt="Map B")
    await update_brain_map(db_session, user.id, map_b.id, status="saved")

    rows = await list_brain_maps(db_session, user.id)
    assert {m.id for m, _ in rows} == {map_a.id, map_b.id}
    revision_by_map = {m.id: rev for m, rev in rows}
    assert revision_by_map[map_a.id].id == rev_a.id

    drafts = await list_brain_maps(db_session, user.id, status="draft")
    assert [m.id for m, _ in drafts] == [map_a.id]


async def test_update_brain_map_title_layout_and_archive(db_session, monkeypatch):
    user = await _make_user(db_session)

    async def fake_search(*_args, **_kwargs):
        return []

    monkeypatch.setattr(brain_maps, "unified_search", fake_search)
    brain_map, _ = await create_brain_map(db_session, user.id, prompt="Editable map")

    updated, _rev = await update_brain_map(
        db_session,
        user.id,
        brain_map.id,
        title="  Renamed   map  ",
        layout={"node": {"x": 1, "y": 2}},
    )
    assert updated.title == "Renamed map"
    assert updated.layout == {"node": {"x": 1, "y": 2}}

    archived, _rev = await update_brain_map(
        db_session, user.id, brain_map.id, status="archived"
    )
    assert archived.status == "archived"
    assert archived.archived_at is not None


async def test_update_brain_map_validation_errors(db_session, monkeypatch):
    user = await _make_user(db_session)

    async def fake_search(*_args, **_kwargs):
        return []

    monkeypatch.setattr(brain_maps, "unified_search", fake_search)
    brain_map, _ = await create_brain_map(db_session, user.id, prompt="Strict map")

    with pytest.raises(BrainMapValidationError):
        await update_brain_map(db_session, user.id, brain_map.id, title="   ")
    with pytest.raises(BrainMapValidationError):
        await update_brain_map(db_session, user.id, brain_map.id, status="exploded")
    with pytest.raises(BrainMapValidationError):
        await update_brain_map(
            db_session, user.id, brain_map.id, layout=["not", "a", "dict"]
        )


async def test_load_brain_map_not_found(db_session):
    user = await _make_user(db_session)
    with pytest.raises(BrainMapNotFoundError):
        await load_brain_map(db_session, user.id, uuid4())


async def test_create_brain_map_input_validation(db_session):
    user = await _make_user(db_session)
    with pytest.raises(BrainMapValidationError):
        await create_brain_map(db_session, user.id, prompt="   ")
    with pytest.raises(BrainMapValidationError):
        await create_brain_map(db_session, user.id, prompt="Map", origin="mars")
    with pytest.raises(BrainMapValidationError):
        await create_brain_map(db_session, user.id, prompt="Map", status="exploded")


async def test_current_revision_none_without_pointer(db_session, monkeypatch):
    user = await _make_user(db_session)

    async def fake_search(*_args, **_kwargs):
        return []

    monkeypatch.setattr(brain_maps, "unified_search", fake_search)
    brain_map, _ = await create_brain_map(db_session, user.id, prompt="Pointerless")
    brain_map.current_revision_id = None
    await db_session.flush()

    _loaded, revision = await load_brain_map(db_session, user.id, brain_map.id)
    assert revision is None


async def test_list_brain_map_revisions_ordered(db_session, monkeypatch):
    user = await _make_user(db_session)

    async def fake_search(*_args, **_kwargs):
        return []

    monkeypatch.setattr(brain_maps, "unified_search", fake_search)
    brain_map, first = await create_brain_map(db_session, user.id, prompt="History map")

    revisions = await list_brain_map_revisions(db_session, user.id, brain_map.id)
    assert [r.id for r in revisions] == [first.id]


async def test_refresh_brain_map_returns_previous_when_unchanged(
    db_session, monkeypatch
):
    user = await _make_user(db_session)
    item, _ = await ingest_item(
        db_session,
        user.id,
        source="paste",
        title="Stable",
        body="Stable evidence.",
        embed=False,
    )

    async def fake_search(*_args, **_kwargs):
        return [
            _hit(kind="item", parent_id=item.id, title="Stable", snippet="Stable evidence.")
        ]

    monkeypatch.setattr(brain_maps, "unified_search", fake_search)

    brain_map, first = await create_brain_map(db_session, user.id, prompt="Stable map")
    again = await refresh_brain_map(db_session, user.id, brain_map.id)
    assert again.id == first.id


async def test_stale_freshness_marks_old_sources(db_session):
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    freshness = brain_maps._freshness([{"created_at": old}])
    assert freshness["stale"] is True
    assert brain_maps._freshness_note(freshness).startswith("Newest evidence is")
