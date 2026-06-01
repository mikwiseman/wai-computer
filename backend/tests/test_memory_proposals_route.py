"""Tests for the memory-proposal review queue API."""

import uuid

from app.core import memory_proposal as gov
from app.core import user_memory as user_memory_module


async def _authed_user_id(client, auth_headers) -> uuid.UUID:
    resp = await client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return uuid.UUID(resp.json()["id"])


async def _seed_pending(db, user_id, content="Curated bio."):
    outcome = await gov.propose_block_update(
        db, user_id, block_label="human", operation="rewrite",
        content=content, confidence=0.99,  # high risk → queued
    )
    return outcome.proposal


async def _seed_accepted(db, user_id, content="Auto fact."):
    outcome = await gov.propose_block_update(
        db, user_id, block_label="human", operation="append",
        content=content, confidence=0.95,  # additive + confident → auto-accepted
    )
    return outcome.proposal


async def test_list_proposals_empty(client, auth_headers) -> None:
    resp = await client.get("/api/memory/proposals", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["proposals"] == []
    assert data["pending_count"] == 0


async def test_list_returns_pending_and_count(client, auth_headers, db_session) -> None:
    user_id = await _authed_user_id(client, auth_headers)
    await _seed_pending(db_session, user_id, content="Pending rewrite.")
    await _seed_accepted(db_session, user_id, content="Already accepted.")

    resp = await client.get("/api/memory/proposals", headers=auth_headers)
    data = resp.json()
    # Default filter is pending — the accepted one is excluded.
    contents = {p["content"] for p in data["proposals"]}
    assert contents == {"Pending rewrite."}
    assert data["pending_count"] == 1
    assert data["proposals"][0]["status"] == "pending"
    assert data["proposals"][0]["risk"] == "high"


async def test_list_all_status(client, auth_headers, db_session) -> None:
    user_id = await _authed_user_id(client, auth_headers)
    await _seed_pending(db_session, user_id, content="Pending rewrite.")
    await _seed_accepted(db_session, user_id, content="Already accepted.")
    resp = await client.get("/api/memory/proposals?status=all", headers=auth_headers)
    data = resp.json()
    assert len(data["proposals"]) == 2
    assert data["pending_count"] == 1


async def test_accept_promotes_into_memory(client, auth_headers, db_session) -> None:
    user_id = await _authed_user_id(client, auth_headers)
    proposal = await _seed_pending(db_session, user_id, content="Reviewed bio fact.")

    resp = await client.post(
        f"/api/memory/proposals/{proposal.id}/accept", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "accepted"

    blocks = await user_memory_module.get_or_seed_blocks(db_session, user_id)
    assert "Reviewed bio fact." in blocks["human"].body


async def test_reject_marks_rejected(client, auth_headers, db_session) -> None:
    user_id = await _authed_user_id(client, auth_headers)
    proposal = await _seed_pending(db_session, user_id, content="Unwanted fact.")

    resp = await client.post(
        f"/api/memory/proposals/{proposal.id}/reject",
        headers=auth_headers, json={"reason": "not relevant"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["decision_reason"] == "not relevant"

    blocks = await user_memory_module.get_or_seed_blocks(db_session, user_id)
    assert "Unwanted fact." not in blocks["human"].body


async def test_accept_missing_returns_404(client, auth_headers) -> None:
    resp = await client.post(
        f"/api/memory/proposals/{uuid.uuid4()}/accept", headers=auth_headers
    )
    assert resp.status_code == 404


async def test_accept_already_decided_returns_409(client, auth_headers, db_session) -> None:
    user_id = await _authed_user_id(client, auth_headers)
    accepted = await _seed_accepted(db_session, user_id, content="Auto fact.")
    resp = await client.post(
        f"/api/memory/proposals/{accepted.id}/accept", headers=auth_headers
    )
    assert resp.status_code == 409


async def test_proposals_scoped_to_user(client, auth_headers, db_session) -> None:
    # A proposal owned by someone else must not be visible or actionable.
    from app.models.user import User

    other = User(email=f"other-{uuid.uuid4().hex}@example.com", password_hash="x")
    db_session.add(other)
    await db_session.flush()
    others = await _seed_pending(db_session, other.id, content="Other user's secret.")

    listed = await client.get("/api/memory/proposals", headers=auth_headers)
    assert all(
        p["content"] != "Other user's secret." for p in listed.json()["proposals"]
    )
    # And cannot be accepted across the user boundary.
    resp = await client.post(
        f"/api/memory/proposals/{others.id}/accept", headers=auth_headers
    )
    assert resp.status_code == 404


async def test_proposals_require_auth(client) -> None:
    resp = await client.get("/api/memory/proposals")
    assert resp.status_code == 401
