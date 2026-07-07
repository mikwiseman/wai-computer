"""Tests for dictation persistent-history routes (entries + dictionary).

Covers create/list/delete for both resources, idempotency by client-generated
UUIDs, and cross-user isolation.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import UsageWeek
from app.models.dictation import DictationDictionaryWord, DictationEntry
from app.models.user import User
from tests.conftest import LEGAL_ACCEPTANCE


async def _register(client: AsyncClient, email: str, password: str = "password123") -> dict:
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password, **LEGAL_ACCEPTANCE},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _entry_payload(**overrides) -> dict:
    payload = {
        "client_entry_id": str(uuid4()),
        "raw_text": "hello world",
        "cleaned_text": "Hello, world.",
        "duration_seconds": 1.25,
        "word_count": 2,
        "occurred_at": datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc).isoformat(),
    }
    payload.update(overrides)
    return payload


def _word_payload(**overrides) -> dict:
    payload = {
        "client_word_id": str(uuid4()),
        "word": "kubernetes",
        "replacement": None,
        "occurred_at": datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc).isoformat(),
    }
    payload.update(overrides)
    return payload


# ---------- entries ----------


@pytest.mark.asyncio
async def test_post_entry_creates_and_list_returns_it(client: AsyncClient):
    headers = await _register(client, "entries.create@example.com")
    payload = _entry_payload()

    create = await client.post("/api/dictation/entries", headers=headers, json=payload)
    assert create.status_code == 201
    body = create.json()
    assert body["client_entry_id"] == payload["client_entry_id"]
    assert body["raw_text"] == "hello world"
    assert body["cleaned_text"] == "Hello, world."
    assert body["word_count"] == 2

    listed = await client.get("/api/dictation/entries", headers=headers)
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    assert items[0]["client_entry_id"] == payload["client_entry_id"]


@pytest.mark.asyncio
async def test_post_entry_counts_words_on_backend(client: AsyncClient, db_session: AsyncSession):
    headers = await _register(client, "entries.backend-count@example.com")
    payload = _entry_payload(
        raw_text="one two three",
        cleaned_text=None,
        word_count=1,
    )

    create = await client.post("/api/dictation/entries", headers=headers, json=payload)

    assert create.status_code == 201
    assert create.json()["word_count"] == 3
    user = (
        await db_session.execute(
            select(User).where(User.email == "entries.backend-count@example.com")
        )
    ).scalar_one()
    usage = (
        await db_session.execute(select(UsageWeek).where(UsageWeek.user_id == user.id))
    ).scalar_one()
    assert usage.words_used == 3


@pytest.mark.asyncio
async def test_post_entry_is_idempotent_by_client_entry_id(client: AsyncClient):
    headers = await _register(client, "entries.idempotent@example.com")
    payload = _entry_payload()

    first = await client.post("/api/dictation/entries", headers=headers, json=payload)
    assert first.status_code == 201

    # Second POST with same client_entry_id but different content: should be a
    # no-op returning the original row (200), not 409.
    payload_again = {**payload, "raw_text": "DIFFERENT TEXT"}
    second = await client.post("/api/dictation/entries", headers=headers, json=payload_again)
    assert second.status_code == 200
    body = second.json()
    assert body["client_entry_id"] == payload["client_entry_id"]
    assert body["raw_text"] == "hello world"  # original, not "DIFFERENT TEXT"

    listed = await client.get("/api/dictation/entries", headers=headers)
    assert len(listed.json()) == 1


@pytest.mark.asyncio
async def test_list_entries_newest_first(client: AsyncClient):
    headers = await _register(client, "entries.order@example.com")
    older = _entry_payload(
        raw_text="older",
        occurred_at=datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc).isoformat(),
    )
    newer = _entry_payload(
        raw_text="newer",
        occurred_at=datetime(2026, 5, 18, 15, 0, tzinfo=timezone.utc).isoformat(),
    )
    await client.post("/api/dictation/entries", headers=headers, json=older)
    await client.post("/api/dictation/entries", headers=headers, json=newer)

    listed = await client.get("/api/dictation/entries", headers=headers)
    assert [item["raw_text"] for item in listed.json()] == ["newer", "older"]


@pytest.mark.asyncio
async def test_delete_entry_returns_204_and_removes_row(client: AsyncClient):
    headers = await _register(client, "entries.delete@example.com")
    payload = _entry_payload()
    await client.post("/api/dictation/entries", headers=headers, json=payload)

    deleted = await client.delete(
        f"/api/dictation/entries/{payload['client_entry_id']}", headers=headers
    )
    assert deleted.status_code == 204

    listed = await client.get("/api/dictation/entries", headers=headers)
    assert listed.json() == []


@pytest.mark.asyncio
async def test_delete_unknown_entry_is_idempotent_204(client: AsyncClient):
    headers = await _register(client, "entries.delete_missing@example.com")
    deleted = await client.delete(
        f"/api/dictation/entries/{uuid4()}", headers=headers
    )
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_entries_isolated_per_user(client: AsyncClient):
    alice = await _register(client, "alice.entries@example.com")
    bob = await _register(client, "bob.entries@example.com")
    alice_payload = _entry_payload(raw_text="alice secret")
    await client.post("/api/dictation/entries", headers=alice, json=alice_payload)

    bob_view = await client.get("/api/dictation/entries", headers=bob)
    assert bob_view.json() == []

    # Bob cannot delete Alice's entry — still 204 (idempotent semantics), but
    # Alice's row is untouched.
    delete_attempt = await client.delete(
        f"/api/dictation/entries/{alice_payload['client_entry_id']}", headers=bob
    )
    assert delete_attempt.status_code == 204

    alice_view = await client.get("/api/dictation/entries", headers=alice)
    assert len(alice_view.json()) == 1


@pytest.mark.asyncio
async def test_user_delete_cascades_entries(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _register(client, "cascade.entries@example.com")
    payload = _entry_payload()
    await client.post("/api/dictation/entries", headers=headers, json=payload)

    user = (
        await db_session.execute(
            select(User).where(User.email == "cascade.entries@example.com")
        )
    ).scalar_one()
    await db_session.delete(user)
    await db_session.flush()

    remaining = (
        await db_session.execute(select(DictationEntry).where(DictationEntry.user_id == user.id))
    ).scalars().all()
    assert remaining == []


# ---------- dictionary ----------


@pytest.mark.asyncio
async def test_post_word_creates_and_list_returns_it(client: AsyncClient):
    headers = await _register(client, "dict.create@example.com")
    payload = _word_payload(word="MyWord", replacement="my-word")

    create = await client.post("/api/dictation/dictionary", headers=headers, json=payload)
    assert create.status_code == 201
    body = create.json()
    assert body["client_word_id"] == payload["client_word_id"]
    assert body["word"] == "MyWord"
    assert body["replacement"] == "my-word"

    listed = await client.get("/api/dictation/dictionary", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


@pytest.mark.asyncio
async def test_post_word_defaults_origin_to_manual(client: AsyncClient):
    """Origin defaults to ``manual`` when the client omits it (backward compat)."""
    headers = await _register(client, "dict.origin.default@example.com")
    payload = _word_payload(word="defaulted")
    assert "origin" not in payload

    create = await client.post("/api/dictation/dictionary", headers=headers, json=payload)
    assert create.status_code == 201
    assert create.json()["origin"] == "manual"

    listed = await client.get("/api/dictation/dictionary", headers=headers)
    assert listed.json()[0]["origin"] == "manual"


@pytest.mark.asyncio
async def test_post_word_round_trips_learned_origin(client: AsyncClient):
    """An explicit ``learned`` origin persists and round-trips through list."""
    headers = await _register(client, "dict.origin.learned@example.com")
    payload = _word_payload(word="autosuggested", origin="learned")

    create = await client.post("/api/dictation/dictionary", headers=headers, json=payload)
    assert create.status_code == 201
    assert create.json()["origin"] == "learned"

    listed = await client.get("/api/dictation/dictionary", headers=headers)
    assert listed.json()[0]["origin"] == "learned"


@pytest.mark.asyncio
async def test_post_word_is_idempotent_by_client_word_id(client: AsyncClient):
    headers = await _register(client, "dict.idempotent@example.com")
    payload = _word_payload(word="kubernetes")

    first = await client.post("/api/dictation/dictionary", headers=headers, json=payload)
    assert first.status_code == 201

    again = {**payload, "word": "should not overwrite"}
    second = await client.post("/api/dictation/dictionary", headers=headers, json=again)
    assert second.status_code == 200
    assert second.json()["word"] == "kubernetes"


@pytest.mark.asyncio
async def test_delete_word_removes_row(client: AsyncClient):
    headers = await _register(client, "dict.delete@example.com")
    payload = _word_payload()
    await client.post("/api/dictation/dictionary", headers=headers, json=payload)

    deleted = await client.delete(
        f"/api/dictation/dictionary/{payload['client_word_id']}", headers=headers
    )
    assert deleted.status_code == 204

    listed = await client.get("/api/dictation/dictionary", headers=headers)
    assert listed.json() == []


@pytest.mark.asyncio
async def test_words_isolated_per_user(client: AsyncClient):
    alice = await _register(client, "alice.dict@example.com")
    bob = await _register(client, "bob.dict@example.com")
    alice_payload = _word_payload(word="alice-private")
    await client.post("/api/dictation/dictionary", headers=alice, json=alice_payload)

    bob_view = await client.get("/api/dictation/dictionary", headers=bob)
    assert bob_view.json() == []


@pytest.mark.asyncio
async def test_word_delete_then_readd_with_new_client_id_succeeds(client: AsyncClient):
    """Drop word A, re-add same text with new client_word_id — must succeed.

    The server has NO (user_id, word) unique constraint by design; dedup-by-text
    happens client-side before the client_word_id is generated.
    """
    headers = await _register(client, "dict.readd@example.com")
    original = _word_payload(word="latency")
    await client.post("/api/dictation/dictionary", headers=headers, json=original)
    await client.delete(
        f"/api/dictation/dictionary/{original['client_word_id']}", headers=headers
    )

    fresh = _word_payload(word="latency")  # new client_word_id
    create = await client.post("/api/dictation/dictionary", headers=headers, json=fresh)
    assert create.status_code == 201


@pytest.mark.asyncio
async def test_user_delete_cascades_dictionary(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _register(client, "cascade.dict@example.com")
    await client.post("/api/dictation/dictionary", headers=headers, json=_word_payload())

    user = (
        await db_session.execute(
            select(User).where(User.email == "cascade.dict@example.com")
        )
    ).scalar_one()
    await db_session.delete(user)
    await db_session.flush()

    remaining = (
        await db_session.execute(
            select(DictationDictionaryWord).where(DictationDictionaryWord.user_id == user.id)
        )
    ).scalars().all()
    assert remaining == []


# ---------- snippets ----------


def _snippet_payload(**overrides) -> dict:
    payload = {
        "client_snippet_id": str(uuid4()),
        "trigger": "my email",
        "expansion": "hi@mikwiseman.com",
        "occurred_at": datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc).isoformat(),
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_post_snippet_creates_and_list_returns_it(client: AsyncClient):
    headers = await _register(client, "snippets.create@example.com")
    payload = _snippet_payload()

    create = await client.post("/api/dictation/snippets", headers=headers, json=payload)
    assert create.status_code == 201
    body = create.json()
    assert body["client_snippet_id"] == payload["client_snippet_id"]
    assert body["trigger"] == "my email"
    assert body["expansion"] == "hi@mikwiseman.com"

    listed = await client.get("/api/dictation/snippets", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


@pytest.mark.asyncio
async def test_post_snippet_is_idempotent_by_client_snippet_id(client: AsyncClient):
    headers = await _register(client, "snippets.idempotent@example.com")
    payload = _snippet_payload()

    first = await client.post("/api/dictation/snippets", headers=headers, json=payload)
    assert first.status_code == 201

    again = {**payload, "expansion": "should not overwrite"}
    second = await client.post("/api/dictation/snippets", headers=headers, json=again)
    assert second.status_code == 200
    assert second.json()["expansion"] == "hi@mikwiseman.com"


@pytest.mark.asyncio
async def test_delete_snippet_is_idempotent(client: AsyncClient):
    headers = await _register(client, "snippets.delete@example.com")
    payload = _snippet_payload()
    await client.post("/api/dictation/snippets", headers=headers, json=payload)

    first = await client.delete(
        f"/api/dictation/snippets/{payload['client_snippet_id']}", headers=headers
    )
    assert first.status_code == 204

    second = await client.delete(
        f"/api/dictation/snippets/{payload['client_snippet_id']}", headers=headers
    )
    assert second.status_code == 204

    listed = await client.get("/api/dictation/snippets", headers=headers)
    assert listed.json() == []


@pytest.mark.asyncio
async def test_snippets_are_isolated_per_user(client: AsyncClient):
    headers_a = await _register(client, "snippets.a@example.com")
    headers_b = await _register(client, "snippets.b@example.com")
    await client.post("/api/dictation/snippets", headers=headers_a, json=_snippet_payload())

    listed_b = await client.get("/api/dictation/snippets", headers=headers_b)
    assert listed_b.json() == []


@pytest.mark.asyncio
async def test_post_snippet_rejects_blank_trigger(client: AsyncClient):
    headers = await _register(client, "snippets.blank@example.com")
    payload = _snippet_payload(trigger="   ")

    response = await client.post("/api/dictation/snippets", headers=headers, json=payload)
    assert response.status_code == 422
