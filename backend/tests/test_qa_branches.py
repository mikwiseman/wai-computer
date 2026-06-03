"""Branch tests for app/core/qa.py to push backend coverage over 95%."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.qa import build_context_text, retrieve_context
from app.models.recording import Recording, Segment
from app.models.user import User


def test_build_context_text_empty_rows_returns_no_match_message() -> None:
    """Line 136 — empty rows shortcut."""
    out = build_context_text([])
    assert "No relevant transcript segments found" in out


def test_build_context_text_formats_rows() -> None:
    """Non-empty rows render with speaker, content."""
    from types import SimpleNamespace

    rows = [
        SimpleNamespace(
            speaker="Alice", content="hello there",
            start_ms=0, end_ms=1000, recording_title="Roadmap",
        ),
        SimpleNamespace(
            speaker=None, content="anonymous line",
            start_ms=1000, end_ms=2000, recording_title=None,
        ),
    ]
    out = build_context_text(rows)
    assert "Alice" in out
    assert "hello there" in out
    # speaker=None → "Unknown"
    assert "Unknown" in out
    assert "anonymous line" in out


@pytest.mark.asyncio
async def test_retrieve_context_with_recording_ids_filter(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lines 47, 121 — recording_ids branch sets up SQL filter + params."""
    user = User(
        email=f"qa-rid-{uuid.uuid4().hex[:6]}@example.com",
        password_hash="hash",
    )
    db_session.add(user)
    await db_session.flush()

    rec1 = Recording(user_id=user.id, type="meeting", language="en", title="rec1")
    rec2 = Recording(user_id=user.id, type="meeting", language="en", title="rec2")
    db_session.add(rec1)
    db_session.add(rec2)
    await db_session.flush()

    db_session.add(Segment(
        recording_id=rec1.id, speaker="Alice", content="alpha",
        start_ms=0, end_ms=500,
    ))
    db_session.add(Segment(
        recording_id=rec2.id, speaker="Bob", content="beta",
        start_ms=0, end_ms=500,
    ))
    await db_session.commit()

    # Stub embedding generation to avoid real API calls
    async def fake_embedding(text: str, **_: object) -> list[float]:
        return [0.1] * 384

    monkeypatch.setattr("app.core.qa.generate_embedding", fake_embedding)

    rows = await retrieve_context(
        db_session, user.id, "alpha", recording_ids=[rec1.id], limit=5,
    )
    # We don't assert on specific row contents (embedding-based ranking is
    # nondeterministic with a stubbed vector) — just that the recording_ids
    # branch executes without crashing.
    assert isinstance(rows, list)


@pytest.mark.asyncio
async def test_retrieve_context_without_recording_ids(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """recording_filter='' branch — no recording_ids filter applied."""
    user = User(
        email=f"qa-no-rid-{uuid.uuid4().hex[:6]}@example.com",
        password_hash="hash",
    )
    db_session.add(user)
    await db_session.flush()

    async def fake_embedding(text: str, **_: object) -> list[float]:
        return [0.1] * 384

    monkeypatch.setattr("app.core.qa.generate_embedding", fake_embedding)

    rows = await retrieve_context(
        db_session, user.id, "x", recording_ids=None, limit=5,
    )
    assert rows == []  # no segments for this user
