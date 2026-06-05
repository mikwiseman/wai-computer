"""Tests for the living-dossier synthesis: citation discipline, caching, and
the deterministic action-item join."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.brain_graph import build_entity_page
from app.core.entity_graph import record_mention, upsert_entity
from app.core.entity_page_synthesis import ensure_entity_page, synthesize_entity_page
from app.core.item_ingest import ingest_item
from app.models.entity import EntityPageSnapshot
from app.models.recording import ActionItem, Recording, RecordingStatus
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"eps-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


def _fake_cerebras(json_payload: dict) -> SimpleNamespace:
    """A stand-in Cerebras client whose chat completion returns fixed JSON."""
    text = json.dumps(json_payload)
    state = {"calls": 0}

    async def _create(**_kwargs):
        state["calls"] += 1
        message = SimpleNamespace(content=text)
        choice = SimpleNamespace(finish_reason="stop", message=message)
        return SimpleNamespace(choices=[choice], model="gpt-oss-120b")

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create)),
        _state=state,
    )
    return client


async def _anna_with_two_items(db):
    user = await _make_user(db)
    item1, _ = await ingest_item(
        db, user.id, source="paste", title="GPU plan", body="x", embed=False
    )
    item2, _ = await ingest_item(
        db, user.id, source="paste", title="Budget memo", body="y", embed=False
    )
    anna = await upsert_entity(db, user.id, type="person", name="Anna")
    await record_mention(
        db, user_id=user.id, entity_id=anna.id, source_kind="item",
        source_id=item1.id, context="Anna owns the GPU plan",
    )
    await record_mention(
        db, user_id=user.id, entity_id=anna.id, source_kind="item",
        source_id=item2.id, context="Anna flagged the budget",
    )
    return user, anna


async def test_synthesis_drops_fabricated_citations_and_caches(db_session) -> None:
    user, anna = await _anna_with_two_items(db_session)
    fake = _fake_cerebras(
        {
            "overview": "Anna leads the GPU plan and owns the budget question.",
            "facts": [
                {"text": "Anna owns the GPU plan", "sources": [1]},
                {"text": "FABRICATED claim", "sources": [99]},  # invalid -> dropped
                {"text": "No citation", "sources": []},  # uncited -> dropped
            ],
            "timeline": [
                {"title": "Kickoff", "description": "", "occurred_at": "2026-03-01", "sources": [1]}
            ],
            "questions": [{"text": "Is the budget approved?", "sources": [2]}],
        }
    )

    snapshot = await synthesize_entity_page(
        db_session, user.id, anna.id, cerebras_client=fake
    )
    assert snapshot is not None
    assert fake._state["calls"] == 1
    # Only the well-cited fact survives; fabricated + uncited are dropped.
    assert [f["text"] for f in snapshot.facts] == ["Anna owns the GPU plan"]
    assert len(snapshot.timeline) == 1 and len(snapshot.questions) == 1

    # The page now reads the cache: ready, populated, every citation real.
    page = await build_entity_page(db_session, user.id, anna.id)
    assert page is not None
    assert page.cache_status == "ready"
    assert page.overview == "Anna leads the GPU plan and owns the budget question."
    assert len(page.facts) == 1
    real_ids = {c.id for c in page.citations}
    assert all(cid in real_ids for f in page.facts for cid in f.citation_ids)


async def test_cache_hit_skips_second_llm_call(db_session) -> None:
    user, anna = await _anna_with_two_items(db_session)
    fake = _fake_cerebras(
        {
            "overview": "Anna leads the GPU plan.",
            "facts": [{"text": "Anna owns the GPU plan", "sources": [1]}],
            "timeline": [],
            "questions": [],
        }
    )
    await synthesize_entity_page(db_session, user.id, anna.id, cerebras_client=fake)
    assert fake._state["calls"] == 1

    # build_entity_page is a pure cache read — no second model call.
    page = await build_entity_page(db_session, user.id, anna.id)
    assert page.cache_status == "ready"
    assert fake._state["calls"] == 1


async def test_ensure_skeleton_for_sourceless_entity_makes_no_llm_call(db_session) -> None:
    user = await _make_user(db_session)
    lonely = await upsert_entity(db_session, user.id, type="topic", name="Roadmaps")
    page = await ensure_entity_page(db_session, user.id, lonely.id)
    assert page is not None
    assert page.cache_status == "skeleton"
    assert page.facts == [] and page.timeline == [] and page.questions == []
    # No snapshot was written for a sourceless entity.
    snap = (
        await db_session.execute(
            select(EntityPageSnapshot).where(EntityPageSnapshot.entity_id == lonely.id)
        )
    ).scalar_one_or_none()
    assert snap is None


async def test_ensure_synthesizes_on_stale(db_session, monkeypatch) -> None:
    user, anna = await _anna_with_two_items(db_session)
    fake = _fake_cerebras(
        {
            "overview": "Anna leads the GPU plan.",
            "facts": [{"text": "Anna owns the GPU plan", "sources": [1]}],
            "timeline": [],
            "questions": [],
        }
    )
    monkeypatch.setattr(
        "app.core.entity_page_synthesis.get_cerebras_client", lambda: fake
    )
    page = await ensure_entity_page(db_session, user.id, anna.id)
    assert page is not None
    assert page.cache_status == "ready"
    assert page.overview == "Anna leads the GPU plan."
    assert fake._state["calls"] == 1


async def test_actions_join_keeps_only_entity_relevant_items(db_session) -> None:
    user = await _make_user(db_session)
    rec = Recording(user_id=user.id, type="note", status=RecordingStatus.READY.value)
    db_session.add(rec)
    await db_session.flush()
    anna = await upsert_entity(db_session, user.id, type="person", name="Anna")
    await record_mention(
        db_session, user_id=user.id, entity_id=anna.id,
        source_kind="recording", source_id=rec.id,
    )
    db_session.add_all(
        [
            ActionItem(recording_id=rec.id, task="Send Anna the GPU deck", status="pending"),
            ActionItem(recording_id=rec.id, task="Buy more coffee", status="pending"),
        ]
    )
    await db_session.flush()

    page = await build_entity_page(db_session, user.id, anna.id)
    assert page is not None
    assert [a.text for a in page.actions] == ["Send Anna the GPU deck"]
    assert page.actions[0].citation_ids == [f"recording:{rec.id}"]
