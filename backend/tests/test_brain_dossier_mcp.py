"""Dossier evidence packing for MCP-fed items (kind-aware + per-kind cap + stats)."""

from uuid import uuid4

import pytest

from app.core.entity_page_synthesis import _gather_evidence
from app.models.entity import Entity, EntityMention
from app.models.item import Item
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _user(db) -> User:
    u = User(email=f"dos-{uuid4().hex}@example.com", password_hash="x")
    db.add(u)
    await db.flush()
    return u


async def _entity(db, user) -> Entity:
    e = Entity(user_id=user.id, type="person", name="Alice")
    db.add(e)
    await db.flush()
    return e


async def _email_item(db, user, *, subject, body, frm, content_hash) -> Item:
    it = Item(
        user_id=user.id, source=f"mcp:{uuid4().hex}", kind="email", title=subject,
        body=body, content_hash=content_hash, privacy_level="internal",
        authority_score=0.8, state="raw",
        metadata_={"from": frm, "subject": subject, "date": "2026-05-03"},
    )
    db.add(it)
    await db.flush()
    return it


async def _mention(db, user, entity, item) -> None:
    db.add(EntityMention(
        user_id=user.id, entity_id=entity.id, source_kind="item", source_id=item.id,
        context="recipient",
    ))
    await db.flush()


async def test_email_evidence_is_kind_aware_with_stats(db_session):
    user = await _user(db_session)
    entity = await _entity(db_session, user)
    it = await _email_item(
        db_session, user, subject="Q3 launch", body="Let's ship the vendor contract Friday.",
        frm="Alice <alice@x.com>", content_hash=uuid4().hex,
    )
    await _mention(db_session, user, entity, it)

    evidence, num_to_cite, stats = await _gather_evidence(db_session, user.id, entity.id)
    assert len(evidence) == 1
    block = evidence[0]
    assert block["kind"] == "email"
    assert "vendor contract" in block["snippet"]  # body snippet, not just title
    assert "email" in block["meta"] and "alice@x.com" in block["meta"]  # provenance line
    assert stats["by_kind"] == {"item": 1}
    assert stats["total_sources"] == 1


async def test_per_kind_cap_limits_items(db_session):
    user = await _user(db_session)
    entity = await _entity(db_session, user)
    for i in range(20):
        it = await _email_item(
            db_session, user, subject=f"mail {i}", body=f"body {i}",
            frm=f"p{i}@x.com", content_hash=uuid4().hex,
        )
        await _mention(db_session, user, entity, it)

    evidence, _, stats = await _gather_evidence(db_session, user.id, entity.id)
    # 20 mentions exist, but the per-kind item cap (15) bounds the evidence pack
    # so a mailbox can't crowd out other source kinds.
    assert stats["total_sources"] == 20
    assert len([b for b in evidence if b["kind"] == "email"]) == 15
