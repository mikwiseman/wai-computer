"""Tests for Ask your Brain: citation validation, honest gaps, freshness, and
the no-evidence path that never calls the model."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.core.brain_ask as brain_ask
from app.core.brain_ask import ask_brain
from app.core.unified_search import UnifiedHit
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"ask-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


def _fake_cerebras(payload: dict) -> SimpleNamespace:
    text = json.dumps(payload)
    state = {"calls": 0}

    async def _create(**_kwargs):
        state["calls"] += 1
        message = SimpleNamespace(content=text)
        choice = SimpleNamespace(finish_reason="stop", message=message)
        return SimpleNamespace(choices=[choice], model="gpt-oss-120b")

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create)),
        _state=state,
    )


def _hit(
    *,
    source_kind: str = "recording",
    parent_id=None,
    title: str = "Q3 sync",
    snippet: str = "Alice wants legal review before pricing sign-off",
    start_ms: int | None = 1000,
    created_at: str | None = "2026-06-05T10:00:00+00:00",
) -> UnifiedHit:
    return UnifiedHit(
        source_kind=source_kind,
        parent_id=str(parent_id or uuid4()),
        chunk_id=str(uuid4()),
        title=title,
        kind="meeting" if source_kind == "recording" else "note",
        snippet=snippet,
        score=0.5,
        created_at=created_at,
        start_ms=start_ms,
        end_ms=2000 if start_ms is not None else None,
    )


async def test_answer_cites_recordings_and_items_and_drops_out_of_range(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    rec_id = uuid4()
    item_id = uuid4()

    async def fake_unified_search(*_a, **_k):
        return [
            _hit(parent_id=rec_id),
            _hit(
                source_kind="item",
                parent_id=item_id,
                title="Launch memo",
                snippet="The launch memo says budget approval is still pending.",
                start_ms=None,
            ),
        ]

    monkeypatch.setattr(brain_ask, "unified_search", fake_unified_search)
    fake = _fake_cerebras(
        {
            "answer": "Pricing needs legal sign-off [1] and budget approval [2].",
            "citations": [1, 2, 99],  # 99 is out of range -> dropped
            "gaps": ["No deadline was mentioned."],
        }
    )

    answer = await ask_brain(
        db_session,
        user.id,
        "what's open with Alice?",
        cerebras_client=fake,
        now=brain_ask.datetime.fromisoformat("2026-06-06T10:00:00+00:00"),
    )
    assert answer.answer == "Pricing needs legal sign-off [1] and budget approval [2]."
    assert [c.source_id for c in answer.citations] == [str(rec_id), str(item_id)]
    assert [c.source_kind for c in answer.citations] == ["recording", "item"]
    assert answer.citations[0].start_ms == 1000
    assert answer.citations[1].start_ms is None
    assert answer.gaps == ["No deadline was mentioned."]
    # Sources are recent -> not stale.
    assert answer.freshness.stale is False
    assert answer.freshness.weeks_since == 0


async def test_no_evidence_returns_honest_gap_without_calling_model(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)

    async def empty_unified_search(*_a, **_k):
        return []

    monkeypatch.setattr(brain_ask, "unified_search", empty_unified_search)
    fake = _fake_cerebras({"answer": "should not be used", "citations": [], "gaps": []})

    answer = await ask_brain(db_session, user.id, "anything?", cerebras_client=fake)
    assert answer.answer == ""
    assert answer.gaps and "doesn't contain" in answer.gaps[0]
    assert fake._state["calls"] == 0  # never paid for an LLM call


async def test_ask_brain_uses_wider_pool_and_prefers_distinct_sources(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    first_recording_id = uuid4()
    second_recording_id = uuid4()
    item_id = uuid4()
    calls: list[int] = []

    async def fake_unified_search(_db, _user_id, _question, *, limit):
        calls.append(limit)
        return [
            _hit(
                parent_id=first_recording_id,
                title="Long voice memo",
                snippet=f"Repeated project detail {index}",
            )
            for index in range(5)
        ] + [
            _hit(
                parent_id=second_recording_id,
                title="Second voice memo",
                snippet="A separate roadmap risk.",
            ),
            _hit(
                source_kind="item",
                parent_id=item_id,
                title="Planning note",
                snippet="A saved material about the same project.",
                start_ms=None,
            ),
        ]

    monkeypatch.setattr(brain_ask, "unified_search", fake_unified_search)
    fake = _fake_cerebras(
        {
            "answer": "The project appears in three sources [1][2][3].",
            "citations": [1, 2, 3],
            "gaps": [],
        }
    )

    answer = await ask_brain(
        db_session,
        user.id,
        "what is happening with active projects?",
        cerebras_client=fake,
        limit=3,
    )

    assert calls == [3 * brain_ask.ASK_SEARCH_POOL_MULTIPLIER]
    assert [citation.source_id for citation in answer.citations] == [
        str(first_recording_id),
        str(second_recording_id),
        str(item_id),
    ]


async def test_blank_question_short_circuits(db_session) -> None:
    user = await _make_user(db_session)
    answer = await ask_brain(db_session, user.id, "   ")
    assert answer.answer == "" and answer.gaps


async def test_ask_route_smoke(client, auth_headers, monkeypatch) -> None:
    async def fake_unified_search(*_a, **_k):
        return [_hit(snippet="We agreed to ship the beta on Friday")]

    fake = _fake_cerebras(
        {"answer": "Beta ships Friday [1].", "citations": [1], "gaps": []}
    )
    monkeypatch.setattr(brain_ask, "unified_search", fake_unified_search)
    monkeypatch.setattr(brain_ask, "get_cerebras_client", lambda: fake)

    resp = await client.post(
        "/api/brain/ask", json={"question": "when does beta ship?"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["answer"] == "Beta ships Friday [1]."
    assert len(data["citations"]) == 1
    assert {"answer", "citations", "gaps", "freshness"} <= set(data)
    assert {"newest_source_at", "weeks_since", "stale"} <= set(data["freshness"])
