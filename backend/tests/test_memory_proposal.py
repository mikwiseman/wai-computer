"""Tests for the memory-proposal governance lifecycle (auto + cherry-pick)."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core import memory_proposal as gov
from app.core import user_memory as user_memory_module
from app.models.memory_proposal import MemoryProposal
from app.models.user import User


async def _make_user(db) -> User:
    user = User(email=f"gov-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def _block_body(db, user_id, label) -> str:
    blocks = await user_memory_module.get_or_seed_blocks(db, user_id)
    return blocks[label].body


# --- pure helpers ---------------------------------------------------------


def test_dedup_key_is_stable_and_normalises() -> None:
    a = gov.stable_dedup_key("human", "append", "Lives in Lisbon")
    b = gov.stable_dedup_key("human", "append", "  lives   in lisbon  ")
    c = gov.stable_dedup_key("human", "append", "Lives in Porto")
    assert a == b  # case + whitespace folded
    assert a != c
    assert len(a) == 64


def test_risk_for_operation() -> None:
    assert gov.risk_for_operation("append") == "low"
    assert gov.risk_for_operation("replace_line") == "high"
    assert gov.risk_for_operation("rewrite") == "high"


def test_auto_eligibility_gate() -> None:
    assert gov.is_auto_eligible(risk="low", confidence=0.9, authority="self")
    # destructive op never auto, even confident
    assert not gov.is_auto_eligible(risk="high", confidence=0.99, authority="self")
    # low confidence never auto
    assert not gov.is_auto_eligible(risk="low", confidence=0.5, authority="self")
    # pure model inference never auto
    assert not gov.is_auto_eligible(risk="low", confidence=0.95, authority="model")


# --- propose_block_update -------------------------------------------------


async def test_confident_additive_fact_auto_accepts(db_session) -> None:
    user = await _make_user(db_session)
    outcome = await gov.propose_block_update(
        db_session, user.id,
        block_label="human", operation="append",
        content="Building WaiComputer.", confidence=0.92,
    )
    assert outcome is not None
    assert outcome.decision == "auto_accepted"
    assert outcome.proposal.status == "accepted"
    assert outcome.proposal.decided_by == "auto"
    assert outcome.proposal.decided_at is not None
    # actually written into canonical memory
    assert "Building WaiComputer." in await _block_body(db_session, user.id, "human")


async def test_destructive_correction_queues_even_when_confident(db_session) -> None:
    user = await _make_user(db_session)
    outcome = await gov.propose_block_update(
        db_session, user.id,
        block_label="human", operation="rewrite",
        content="Entirely new bio.", confidence=0.99,
    )
    assert outcome.decision == "queued"
    assert outcome.proposal.status == "pending"
    assert outcome.proposal.risk == "high"
    # memory block untouched until a human accepts
    assert "Entirely new bio." not in await _block_body(db_session, user.id, "human")


async def test_low_confidence_additive_queues(db_session) -> None:
    user = await _make_user(db_session)
    outcome = await gov.propose_block_update(
        db_session, user.id,
        block_label="topics", operation="append",
        content="Maybe interested in sailing?", confidence=0.4,
    )
    assert outcome.decision == "queued"
    assert outcome.proposal.status == "pending"


async def test_model_authority_queues(db_session) -> None:
    user = await _make_user(db_session)
    outcome = await gov.propose_block_update(
        db_session, user.id,
        block_label="topics", operation="append",
        content="Inferred love of jazz.", confidence=0.95, authority="model",
    )
    assert outcome.decision == "queued"


async def test_proposing_same_fact_twice_is_idempotent(db_session) -> None:
    user = await _make_user(db_session)
    first = await gov.propose_block_update(
        db_session, user.id, block_label="human", operation="append",
        content="Lives in Lisbon.", confidence=0.3,  # queued
    )
    assert first is not None and first.decision == "queued"
    second = await gov.propose_block_update(
        db_session, user.id, block_label="human", operation="append",
        content="lives in lisbon.", confidence=0.3,
    )
    assert second is None  # already proposed — no duplicate
    count = await db_session.scalar(
        select(func.count()).select_from(MemoryProposal).where(
            MemoryProposal.user_id == user.id
        )
    )
    assert count == 1


async def test_empty_content_proposes_nothing(db_session) -> None:
    user = await _make_user(db_session)
    assert await gov.propose_block_update(
        db_session, user.id, block_label="human", operation="append",
        content="   ", confidence=0.99,
    ) is None


# --- review actions -------------------------------------------------------


async def test_accept_proposal_promotes_into_memory(db_session) -> None:
    user = await _make_user(db_session)
    outcome = await gov.propose_block_update(
        db_session, user.id, block_label="human", operation="rewrite",
        content="Curated bio.", confidence=0.99,  # queued (high risk)
    )
    accepted = await gov.accept_proposal(db_session, user.id, outcome.proposal.id)
    assert accepted.status == "accepted"
    assert accepted.decided_by == "user"
    assert "Curated bio." in await _block_body(db_session, user.id, "human")


async def test_reject_proposal_is_durable(db_session) -> None:
    user = await _make_user(db_session)
    outcome = await gov.propose_block_update(
        db_session, user.id, block_label="topics", operation="append",
        content="Sailing.", confidence=0.3,
    )
    rejected = await gov.reject_proposal(
        db_session, user.id, outcome.proposal.id, reason="not relevant"
    )
    assert rejected.status == "rejected"
    assert rejected.decision_reason == "not relevant"
    # not written to memory
    assert "Sailing." not in await _block_body(db_session, user.id, "topics")
    # and never re-proposed (a "no" sticks)
    again = await gov.propose_block_update(
        db_session, user.id, block_label="topics", operation="append",
        content="Sailing.", confidence=0.3,
    )
    assert again is None


async def test_accept_already_decided_raises(db_session) -> None:
    user = await _make_user(db_session)
    outcome = await gov.propose_block_update(
        db_session, user.id, block_label="human", operation="append",
        content="Confident fact.", confidence=0.95,  # auto-accepted
    )
    with pytest.raises(ValueError):
        await gov.accept_proposal(db_session, user.id, outcome.proposal.id)


async def test_accept_missing_raises(db_session) -> None:
    user = await _make_user(db_session)
    with pytest.raises(LookupError):
        await gov.accept_proposal(db_session, user.id, uuid4())


async def test_cannot_act_on_another_users_proposal(db_session) -> None:
    owner = await _make_user(db_session)
    intruder = await _make_user(db_session)
    outcome = await gov.propose_block_update(
        db_session, owner.id, block_label="human", operation="rewrite",
        content="Owner only.", confidence=0.99,
    )
    with pytest.raises(LookupError):
        await gov.accept_proposal(db_session, intruder.id, outcome.proposal.id)


async def test_failed_auto_apply_stays_pending_with_reason(db_session) -> None:
    # An additive fact that blows the char limit can't auto-apply; it must
    # stay pending with the reason recorded — never silently dropped.
    user = await _make_user(db_session)
    blocks = await user_memory_module.get_or_seed_blocks(db_session, user.id)
    limit = blocks["preferences"].char_limit
    outcome = await gov.propose_block_update(
        db_session, user.id, block_label="preferences", operation="append",
        content="x" * (limit + 50), confidence=0.95,
    )
    assert outcome.decision == "queued"
    assert outcome.proposal.status == "pending"
    assert "auto-apply failed" in (outcome.proposal.decision_reason or "")


async def test_list_proposals_filters_by_status(db_session) -> None:
    user = await _make_user(db_session)
    await gov.propose_block_update(
        db_session, user.id, block_label="human", operation="append",
        content="Auto fact.", confidence=0.95,
    )  # accepted
    await gov.propose_block_update(
        db_session, user.id, block_label="topics", operation="append",
        content="Pending fact.", confidence=0.3,
    )  # pending
    pending = await gov.list_proposals(db_session, user.id, status="pending")
    assert {p.content for p in pending} == {"Pending fact."}
    all_props = await gov.list_proposals(db_session, user.id)
    assert len(all_props) == 2
