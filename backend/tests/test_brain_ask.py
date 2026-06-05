"""Tests for Ask your Brain: citation validation, honest gaps, freshness, and
the no-evidence path that never calls the model."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.core.brain_ask as brain_ask
from app.core.brain_ask import ask_brain
from app.models.recording import Recording, RecordingStatus
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


def _segment(recording_id, content: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        recording_id=recording_id,
        recording_title="Q3 sync",
        speaker="Alice",
        content=content,
        start_ms=1000,
        end_ms=2000,
        rrf_score=0.5,
    )


async def test_answer_cites_real_sources_and_drops_out_of_range(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    rec = Recording(user_id=user.id, type="note", status=RecordingStatus.READY.value)
    db_session.add(rec)
    await db_session.flush()

    async def fake_retrieve(*_a, **_k):
        return [_segment(rec.id, "Alice wants legal review before pricing sign-off")]

    monkeypatch.setattr(brain_ask, "retrieve_context", fake_retrieve)
    fake = _fake_cerebras(
        {
            "answer": "Pricing needs legal sign-off [1].",
            "citations": [1, 99],  # 99 is out of range -> dropped
            "gaps": ["No deadline was mentioned."],
        }
    )

    answer = await ask_brain(
        db_session, user.id, "what's open with Alice?", cerebras_client=fake
    )
    assert answer.answer == "Pricing needs legal sign-off [1]."
    assert [c.source_id for c in answer.citations] == [str(rec.id)]  # [99] dropped
    assert answer.citations[0].source_kind == "recording"
    assert answer.gaps == ["No deadline was mentioned."]
    # Recording is brand new -> not stale.
    assert answer.freshness.stale is False
    assert answer.freshness.weeks_since == 0


async def test_no_evidence_returns_honest_gap_without_calling_model(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)

    async def empty_retrieve(*_a, **_k):
        return []

    monkeypatch.setattr(brain_ask, "retrieve_context", empty_retrieve)
    fake = _fake_cerebras({"answer": "should not be used", "citations": [], "gaps": []})

    answer = await ask_brain(db_session, user.id, "anything?", cerebras_client=fake)
    assert answer.answer == ""
    assert answer.gaps and "don't contain" in answer.gaps[0]
    assert fake._state["calls"] == 0  # never paid for an LLM call


async def test_blank_question_short_circuits(db_session) -> None:
    user = await _make_user(db_session)
    answer = await ask_brain(db_session, user.id, "   ")
    assert answer.answer == "" and answer.gaps


async def test_ask_route_smoke(client, auth_headers, monkeypatch) -> None:
    async def fake_retrieve(*_a, **_k):
        return [_segment(uuid4(), "We agreed to ship the beta on Friday")]

    fake = _fake_cerebras(
        {"answer": "Beta ships Friday [1].", "citations": [1], "gaps": []}
    )
    monkeypatch.setattr(brain_ask, "retrieve_context", fake_retrieve)
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
