"""Tests for LLM-driven speaker name extraction.

The LLM call itself is mocked everywhere. These tests pin the apply logic:
- Existing Person matched by display_name is reused.
- Existing Person matched by alias is reused.
- Cluster already voice-matched -> name added as alias on that Person.
- Cluster unmatched and no existing Person -> a new Person is created.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.speaker_name_extraction import (
    _NameAssignment,
    apply_extracted_names,
)
from app.models.person import Person
from app.models.user import User
from tests.conftest import LEGAL_ACCEPTANCE


@dataclass(frozen=True)
class _FakeTranscriptResult:
    speaker: str | None
    text: str
    start_ms: int = 0
    end_ms: int = 1_000
    confidence: float = 0.9


async def _make_user(client, db_session, email: str = "names@example.com") -> User:
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password-123", **LEGAL_ACCEPTANCE},
    )
    assert response.status_code == 200
    user = (
        await db_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    return user


def _assignment(speaker: str, name: str) -> _NameAssignment:
    return _NameAssignment(
        speaker=speaker, name=name, confidence="high", evidence=f"... I'm {name} ..."
    )


@pytest.mark.asyncio
async def test_apply_creates_person_for_unmatched_cluster(client, db_session):
    user = await _make_user(client, db_session, email="names.create@example.com")

    speaker_assignments: dict[str, tuple[UUID, float] | None] = {"speaker_0": None}
    extracted = {"speaker_0": _assignment("speaker_0", "John Smith")}

    applied = await apply_extracted_names(
        db=db_session,
        user_id=user.id,
        speaker_assignments=speaker_assignments,
        extracted=extracted,
    )

    assert len(applied) == 1
    assert applied[0].created_person is True
    new_person = (
        await db_session.execute(
            select(Person).where(Person.user_id == user.id)
        )
    ).scalar_one()
    assert new_person.display_name == "John Smith"
    assert speaker_assignments["speaker_0"] == (new_person.id, 1.0)


@pytest.mark.asyncio
async def test_apply_reuses_person_by_display_name_case_insensitive(client, db_session):
    user = await _make_user(client, db_session, email="names.reuse@example.com")
    existing = Person(user_id=user.id, display_name="Anna Sobol")
    db_session.add(existing)
    await db_session.flush()

    speaker_assignments: dict[str, tuple[UUID, float] | None] = {"speaker_1": None}
    extracted = {"speaker_1": _assignment("speaker_1", "anna sobol")}

    await apply_extracted_names(
        db=db_session,
        user_id=user.id,
        speaker_assignments=speaker_assignments,
        extracted=extracted,
    )

    assert speaker_assignments["speaker_1"] == (existing.id, 1.0)
    people_count = (
        await db_session.execute(
            select(Person).where(Person.user_id == user.id)
        )
    ).scalars().all()
    assert len(people_count) == 1


@pytest.mark.asyncio
async def test_apply_adds_alias_when_cluster_already_voice_matched(client, db_session):
    user = await _make_user(client, db_session, email="names.alias@example.com")
    voice_matched = Person(user_id=user.id, display_name="Mik")
    db_session.add(voice_matched)
    await db_session.flush()

    speaker_assignments: dict[str, tuple[UUID, float] | None] = {
        "speaker_0": (voice_matched.id, 0.82)
    }
    extracted = {"speaker_0": _assignment("speaker_0", "Mikhail Wiseman")}

    applied = await apply_extracted_names(
        db=db_session,
        user_id=user.id,
        speaker_assignments=speaker_assignments,
        extracted=extracted,
    )

    assert len(applied) == 1
    assert applied[0].aliased_existing is True
    # Voice match left intact.
    assert speaker_assignments["speaker_0"] == (voice_matched.id, 0.82)
    await db_session.refresh(voice_matched)
    assert voice_matched.aliases == ["Mikhail Wiseman"]


@pytest.mark.asyncio
async def test_apply_is_idempotent_for_existing_correct_match(client, db_session):
    """If voice ID already linked the cluster to the same Person, no Person changes."""
    user = await _make_user(client, db_session, email="names.idempotent@example.com")
    matched = Person(user_id=user.id, display_name="Alex")
    db_session.add(matched)
    await db_session.flush()

    speaker_assignments: dict[str, tuple[UUID, float] | None] = {
        "speaker_2": (matched.id, 0.9)
    }
    extracted = {"speaker_2": _assignment("speaker_2", "Alex")}

    applied = await apply_extracted_names(
        db=db_session,
        user_id=user.id,
        speaker_assignments=speaker_assignments,
        extracted=extracted,
    )

    assert applied == []
    assert speaker_assignments["speaker_2"] == (matched.id, 0.9)


@pytest.mark.asyncio
async def test_apply_resolves_via_alias_match(client, db_session):
    user = await _make_user(client, db_session, email="names.aliasmatch@example.com")
    aliased = Person(user_id=user.id, display_name="Сергей", aliases=["Sergey"])
    db_session.add(aliased)
    await db_session.flush()

    speaker_assignments: dict[str, tuple[UUID, float] | None] = {"speaker_3": None}
    extracted = {"speaker_3": _assignment("speaker_3", "Sergey")}

    await apply_extracted_names(
        db=db_session,
        user_id=user.id,
        speaker_assignments=speaker_assignments,
        extracted=extracted,
    )

    assert speaker_assignments["speaker_3"] == (aliased.id, 1.0)


@pytest.mark.asyncio
async def test_apply_with_no_extractions_is_noop(client, db_session):
    user = await _make_user(client, db_session, email="names.noop@example.com")
    speaker_assignments: dict[str, tuple[UUID, float] | None] = {"speaker_0": None}

    applied = await apply_extracted_names(
        db=db_session,
        user_id=user.id,
        speaker_assignments=speaker_assignments,
        extracted={},
    )

    assert applied == []
    assert speaker_assignments == {"speaker_0": None}
