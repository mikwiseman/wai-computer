"""Brain-wiki P1: entity-scoped companion chat + pages-index snippet."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes.companion import ConversationScope, _validated_scope_to_jsonb
from app.api.routes.entities import _overview_snippet
from app.core import companion as cc
from app.core.companion import (
    CompanionError,
    _format_scope_for_session,
    _render_entity_dossier_markdown,
    _scope_entity_uuid,
)
from app.core.entity_graph import upsert_entity
from app.models.user import User


async def _make_user(db) -> User:
    user = User(email=f"p1-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


# ---------------------------------------------------------------- pure helpers


def test_overview_snippet_trims_on_word_boundary() -> None:
    assert _overview_snippet(None) is None
    assert _overview_snippet("   ") is None
    assert _overview_snippet("short overview") == "short overview"
    long = "word " * 60  # 300 chars
    snip = _overview_snippet(long)
    assert snip is not None and snip.endswith("…") and len(snip) <= 161
    assert " word…" in snip or snip.endswith("word…")  # cut on a space, no mid-word


def test_render_entity_dossier_markdown() -> None:
    page = SimpleNamespace(
        name="Atlas",
        type="project",
        overview="The Q3 launch.",
        facts=[SimpleNamespace(text="Owned by Anna"), SimpleNamespace(text="")],
        timeline=[SimpleNamespace(title="Kickoff", description="in March")],
        questions=[SimpleNamespace(text="When does it ship?")],
    )
    md = _render_entity_dossier_markdown(page)
    assert md.startswith("# Atlas (project)")
    assert "The Q3 launch." in md
    assert "- Owned by Anna" in md
    assert "## Timeline" in md and "- Kickoff — in March" in md
    assert "## Open questions" in md and "- When does it ship?" in md


def test_format_scope_for_session_entity() -> None:
    assert _format_scope_for_session({"entity_id": str(uuid4())}) == "a Brain page"
    assert _format_scope_for_session(None) == "all of the user's recordings"


def test_scope_entity_uuid() -> None:
    eid = uuid4()
    assert _scope_entity_uuid({"entity_id": str(eid)}) == eid
    assert _scope_entity_uuid({}) is None
    assert _scope_entity_uuid(None) is None
    with pytest.raises(CompanionError):
        _scope_entity_uuid({"entity_id": "not-a-uuid"})


# ------------------------------------------------------------ scope validation


async def test_validated_scope_entity_owned_malformed_and_missing(db_session) -> None:
    user = await _make_user(db_session)
    entity = await upsert_entity(db_session, user.id, type="person", name="Anna")

    # owned entity → passes, body carries entity_id
    body = await _validated_scope_to_jsonb(
        db_session, user.id, ConversationScope(entity_id=str(entity.id))
    )
    assert body["entity_id"] == str(entity.id)

    # someone else's / nonexistent entity → 404
    with pytest.raises(HTTPException) as missing:
        await _validated_scope_to_jsonb(
            db_session, user.id, ConversationScope(entity_id=str(uuid4()))
        )
    assert missing.value.status_code == 404

    # malformed → 422
    with pytest.raises(HTTPException) as bad:
        await _validated_scope_to_jsonb(
            db_session, user.id, ConversationScope(entity_id="nope")
        )
    assert bad.value.status_code == 422


# --------------------------------------------------------- entity brain context


async def test_brain_context_for_entity_scope(db_session, monkeypatch) -> None:
    user = await _make_user(db_session)
    entity = await upsert_entity(db_session, user.id, type="project", name="Atlas")

    fake_page = SimpleNamespace(
        name="Atlas",
        type="project",
        overview="The Q3 launch.",
        facts=[SimpleNamespace(text="Owned by Anna")],
        timeline=[],
        questions=[],
    )

    async def fake_ensure(db, uid, eid):
        return fake_page

    monkeypatch.setattr(
        "app.core.entity_page_synthesis.ensure_entity_page", fake_ensure
    )
    ctx = await cc._brain_context_for_scope(
        db_session, user.id, {"entity_id": str(entity.id)}
    )
    assert ctx is not None
    assert ctx["space"].name == "Atlas"
    assert "The Q3 launch." in ctx["markdown"]
    assert "Owned by Anna" in ctx["markdown"]
    assert ctx["claim_count"] == 1

    # no scope → no context
    assert await cc._brain_context_for_scope(db_session, user.id, None) is None

    # entity page unavailable → invalid_scope
    async def fake_none(db, uid, eid):
        return None

    monkeypatch.setattr("app.core.entity_page_synthesis.ensure_entity_page", fake_none)
    with pytest.raises(CompanionError):
        await cc._brain_context_for_scope(
            db_session, user.id, {"entity_id": str(entity.id)}
        )
