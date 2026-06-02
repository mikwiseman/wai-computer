"""Branch-coverage tests for app.tasks.consolidate_user_memory that aren't
covered by test_consolidate_user_memory.py."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks import consolidate_user_memory as cum
from app.tasks.consolidate_user_memory import (
    CONSOLIDATOR_SYSTEM_PROMPT,
    _apply_updates,
    _consolidator_schema,
    _first_output_text,
)

# ---------------------------------------------------------------------------
# Schema + system prompt — pure structural assertions
# ---------------------------------------------------------------------------


def test_consolidator_schema_shape() -> None:
    schema = _consolidator_schema()
    assert schema["name"] == "wai_memory_updates"
    assert schema["strict"] is True
    inner = schema["schema"]
    assert inner["type"] == "object"
    assert "updates" in inner["properties"]
    updates = inner["properties"]["updates"]
    assert updates["type"] == "array"
    item = updates["items"]
    assert set(item["required"]) == {
        "block", "operation", "content", "target_line", "confidence"
    }
    assert item["properties"]["target_line"]["type"] == ["string", "null"]
    assert item["properties"]["confidence"]["type"] == "number"
    assert set(item["properties"]["block"]["enum"]) == {"human", "topics", "preferences"}
    assert set(item["properties"]["operation"]["enum"]) == {"append", "replace_line", "rewrite"}


def test_system_prompt_mentions_durable_facts_only() -> None:
    assert "durable" in CONSOLIDATOR_SYSTEM_PROMPT
    for word in ("updates", "human", "topics", "preferences"):
        assert word in CONSOLIDATOR_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# _first_output_text — exercises every branch
# ---------------------------------------------------------------------------


def test_first_output_text_uses_top_level_output_text() -> None:
    response = SimpleNamespace(output_text="hello")
    assert _first_output_text(response) == "hello"


def test_first_output_text_returns_empty_when_output_is_none() -> None:
    response = SimpleNamespace(output_text=None, output=None)
    assert _first_output_text(response) == ""


def test_first_output_text_returns_empty_when_output_empty_list() -> None:
    response = SimpleNamespace(output_text=None, output=[])
    assert _first_output_text(response) == ""


def test_first_output_text_falls_back_to_output_item_dict_content() -> None:
    response = SimpleNamespace(
        output_text=None,
        output=[
            SimpleNamespace(content=[{"type": "output_text", "text": "from dict"}]),
        ],
    )
    assert _first_output_text(response) == "from dict"


def test_first_output_text_handles_object_typed_content() -> None:
    response = SimpleNamespace(
        output_text=None,
        output=[
            SimpleNamespace(content=[
                SimpleNamespace(type="output_text", text="attr form"),
            ]),
        ],
    )
    assert _first_output_text(response) == "attr form"


def test_first_output_text_handles_dict_item() -> None:
    """`item` is a dict, not an object."""
    response = SimpleNamespace(
        output_text=None,
        output=[{"content": [{"type": "output_text", "text": "dict-item"}]}],
    )
    assert _first_output_text(response) == "dict-item"


def test_first_output_text_skips_non_output_text_blocks() -> None:
    """Items whose type != 'output_text' are skipped."""
    response = SimpleNamespace(
        output_text=None,
        output=[
            SimpleNamespace(content=[
                {"type": "tool_call", "text": "should be skipped"},
                {"type": "output_text", "text": "found me"},
            ]),
        ],
    )
    assert _first_output_text(response) == "found me"


def test_first_output_text_returns_empty_when_content_missing() -> None:
    """item.content is None and not dict → returns empty string."""
    response = SimpleNamespace(
        output_text=None,
        output=[SimpleNamespace(content=None)],
    )
    assert _first_output_text(response) == ""


# ---------------------------------------------------------------------------
# _apply_updates — empty + mixed reject path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_updates_empty_returns_zeros() -> None:
    db = MagicMock()
    result = await _apply_updates(db, uuid.uuid4(), [])
    assert result == {"auto_applied": 0, "queued": 0, "duplicates": 0}


# ---------------------------------------------------------------------------
# _consolidate_one_user — parse_error branch (line 230-232)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consolidate_one_user_parse_error(db_session) -> None:
    """When the LLM returns text that isn't valid JSON, we don't crash —
    we return parse_error=True."""
    from app.models.companion import ChatMessage, Conversation
    from app.models.user import User
    from app.tasks.consolidate_user_memory import _consolidate_one_user

    user = User(email=f"parse-err-{uuid.uuid4().hex}@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()
    conv = Conversation(user_id=user.id)
    db_session.add(conv)
    await db_session.flush()
    db_session.add(ChatMessage(conversation_id=conv.id, role="user", content="hi"))
    await db_session.commit()

    fake_response = SimpleNamespace(output_text="not valid json{", output=None)
    fake_client = SimpleNamespace(
        responses=SimpleNamespace(create=AsyncMock(return_value=fake_response))
    )

    with patch.object(
        cum.user_memory_module, "get_or_seed_blocks",
        new=AsyncMock(return_value={
            "human": SimpleNamespace(char_limit=2000, body=""),
            "topics": SimpleNamespace(char_limit=2000, body=""),
            "preferences": SimpleNamespace(char_limit=2000, body=""),
        }),
    ):
        result = await _consolidate_one_user(
            db_session, user.id, openai_client=fake_client,
        )

    assert result["parse_error"] is True
    assert result["auto_applied"] == 0


# ---------------------------------------------------------------------------
# _consolidate_all_active_users — exercises the batch loop branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consolidate_all_active_users_counts_processed_and_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stub out the per-user DB context manager and _consolidate_one_user so
    we can verify the summary counts without seeding a real DB batch."""
    from contextlib import asynccontextmanager

    fake_user_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]

    # First user: processed; second: skipped; third: processed; fourth: failure.
    per_user_results = iter([
        {"auto_applied": 2, "queued": 0, "considered": 2},  # processed
        {"auto_applied": 0, "queued": 0, "skipped": True},  # skipped
        {"auto_applied": 1, "queued": 1, "considered": 2},  # processed
        RuntimeError("boom"),                               # failure
    ])

    async def fake_consolidate_one_user(db, user_id, **kwargs):
        nxt = next(per_user_results)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    # Fake the user_id scan with a single scan_db, then per-user contexts.
    scan_db = MagicMock()
    scan_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=fake_user_ids)),
    )))

    @asynccontextmanager
    async def fake_ctx():
        yield scan_db

    monkeypatch.setattr(cum, "get_db_context", fake_ctx)
    monkeypatch.setattr(cum, "_consolidate_one_user", fake_consolidate_one_user)

    summary = await cum._consolidate_all_active_users()
    assert summary["users_processed"] == 2
    assert summary["users_skipped"] == 1
    assert summary["failures"] == 1


@pytest.mark.asyncio
async def test_consolidate_all_active_users_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import asynccontextmanager

    scan_db = MagicMock()
    scan_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[])),
    )))

    @asynccontextmanager
    async def fake_ctx():
        yield scan_db

    monkeypatch.setattr(cum, "get_db_context", fake_ctx)

    summary = await cum._consolidate_all_active_users()
    assert summary == {"users_processed": 0, "users_skipped": 0, "failures": 0}


# ---------------------------------------------------------------------------
# run() — Celery entrypoint
# ---------------------------------------------------------------------------


def test_run_celery_entrypoint_invokes_consolidate_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_consolidate_all():
        return {"users_processed": 1, "users_skipped": 0, "failures": 0}

    monkeypatch.setattr(cum, "_consolidate_all_active_users", fake_consolidate_all)
    out = cum.run()
    assert out == {"users_processed": 1, "users_skipped": 0, "failures": 0}
