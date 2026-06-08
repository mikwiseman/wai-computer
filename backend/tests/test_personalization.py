"""Tests for user personalization terminology and summary instructions."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.personalization import (
    CreatePersonalizationTermRequest,
    UpdatePersonalizationTermRequest,
    create_personalization_term,
    update_personalization_term,
)
from app.core.personalization import (
    extract_candidate_terms,
    load_user_entity_terms,
    load_user_keyterms,
    sanitize_keyterms,
    summary_personalization_instructions,
)
from app.models.dictation import DictationDictionaryWord
from app.models.entity import Entity
from app.models.personalization import PersonalizationImportJob, PersonalizationTerm
from app.models.user import User
from tests.conftest import LEGAL_ACCEPTANCE


def test_extract_candidate_terms_counts_domain_terms_without_common_words() -> None:
    candidates = extract_candidate_terms(
        "WaiComputer распознал больничный. Больничный надо оформить через WaiComputer.",
        limit=5,
    )

    assert candidates[0].term in {"WaiComputer", "больничный"}
    assert {candidate.term for candidate in candidates} >= {"WaiComputer", "больничный"}


def test_sanitize_keyterms_truncates_dedupes_and_respects_budget() -> None:
    terms = sanitize_keyterms(
        ["  " + "x" * 220, "Alpha Beta Gamma", "alpha beta gamma", "One Two Three"],
        max_terms=10,
        max_chars=200,
        max_words=4,
        token_budget=5,
    )

    assert terms == ["x" * 200, "Alpha Beta Gamma"]


def test_personalization_request_models_normalize_optional_fields() -> None:
    create_request = CreatePersonalizationTermRequest(term="Term", notes=None)
    update_request = UpdatePersonalizationTermRequest(
        replacement=None,
        notes="  updated note  ",
    )

    assert create_request.notes is None
    assert update_request.replacement is None
    assert update_request.notes == "updated note"


@pytest.mark.asyncio
async def test_personalization_import_creates_review_candidates(
    client: AsyncClient,
    auth_headers: dict,
):
    response = await client.post(
        "/api/personalization/imports",
        headers=auth_headers,
        data={
            "source_type": "text",
            "text": "WaiComputer больничный больничный транскрибация",
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "succeeded"
    assert payload["candidate_count"] >= 2

    terms_response = await client.get(
        "/api/personalization/terms",
        headers=auth_headers,
        params={"status": "candidate"},
    )
    assert terms_response.status_code == 200
    terms = terms_response.json()
    assert {term["term"] for term in terms} >= {"WaiComputer", "больничный"}


@pytest.mark.asyncio
async def test_personalization_import_file_and_validation_errors(
    client: AsyncClient,
    auth_headers: dict,
):
    file_response = await client.post(
        "/api/personalization/imports",
        headers=auth_headers,
        data={"source_type": "file"},
        files={"file": ("terms.md", b"AlphaTerm AlphaTerm BetaTerm", "text/markdown")},
    )
    assert file_response.status_code == 202
    assert file_response.json()["source_name"] == "terms.md"

    invalid_source = await client.post(
        "/api/personalization/imports",
        headers=auth_headers,
        data={"source_type": "url", "text": "AlphaTerm"},
    )
    assert invalid_source.status_code == 422

    missing_file = await client.post(
        "/api/personalization/imports",
        headers=auth_headers,
        data={"source_type": "file"},
    )
    assert missing_file.status_code == 422

    unsupported_file = await client.post(
        "/api/personalization/imports",
        headers=auth_headers,
        data={"source_type": "file"},
        files={"file": ("terms.pdf", b"AlphaTerm", "application/pdf")},
    )
    assert unsupported_file.status_code == 415

    empty_text = await client.post(
        "/api/personalization/imports",
        headers=auth_headers,
        data={"source_type": "text", "text": "   "},
    )
    assert empty_text.status_code == 422

    too_large = await client.post(
        "/api/personalization/imports",
        headers=auth_headers,
        data={"source_type": "text", "text": "x" * 500_001},
    )
    assert too_large.status_code == 413


@pytest.mark.asyncio
async def test_personalization_confirmed_terms_feed_keyterm_selection(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    create_response = await client.post(
        "/api/personalization/terms",
        headers=auth_headers,
        json={"term": "WaiComputer", "replacement": None, "notes": "brand spelling"},
    )
    assert create_response.status_code == 201
    term_id = create_response.json()["id"]

    update_response = await client.patch(
        f"/api/personalization/terms/{term_id}",
        headers=auth_headers,
        json={"status": "active"},
    )
    assert update_response.status_code == 200

    user_id = UUID(create_response.json()["user_id"])
    keyterms = await load_user_keyterms(db_session, user_id=user_id, purpose="recording")
    assert "WaiComputer" in keyterms


@pytest.mark.asyncio
async def test_personalization_term_lifecycle_updates_lists_and_deletes(
    client: AsyncClient,
    auth_headers: dict,
):
    create_response = await client.post(
        "/api/personalization/terms",
        headers=auth_headers,
        json={"term": "  LifecycleTerm  ", "notes": "  keep exact spelling  "},
    )
    assert create_response.status_code == 201
    term = create_response.json()
    assert term["term"] == "LifecycleTerm"
    assert term["notes"] == "keep exact spelling"

    update_response = await client.patch(
        f"/api/personalization/terms/{term['id']}",
        headers=auth_headers,
        json={"replacement": "  Lifecycle Term  ", "notes": None},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["replacement"] == "Lifecycle Term"
    assert updated["notes"] is None

    all_response = await client.get(
        "/api/personalization/terms",
        headers=auth_headers,
        params={"status": "all"},
    )
    assert any(item["id"] == term["id"] for item in all_response.json())

    delete_response = await client.delete(
        f"/api/personalization/terms/{term['id']}",
        headers=auth_headers,
    )
    assert delete_response.status_code == 204

    missing_update = await client.patch(
        f"/api/personalization/terms/{term['id']}",
        headers=auth_headers,
        json={"status": "active"},
    )
    assert missing_update.status_code == 404


@pytest.mark.asyncio
async def test_personalization_create_rejects_duplicate_term(
    client: AsyncClient,
    auth_headers: dict,
):
    first = await client.post(
        "/api/personalization/terms",
        headers=auth_headers,
        json={"term": "DuplicateTerm"},
    )
    assert first.status_code == 201

    duplicate = await client.post(
        "/api/personalization/terms",
        headers=auth_headers,
        json={"term": "duplicateterm"},
    )
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_personalization_create_rejects_empty_cleaned_term(
):
    request = CreatePersonalizationTermRequest.model_construct(term="...")

    with pytest.raises(HTTPException) as exc_info:
        await create_personalization_term(
            request,
            user=SimpleNamespace(id=uuid4()),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Term is empty"


@pytest.mark.asyncio
async def test_personalization_update_rejects_invalid_constructed_status(
    db_session: AsyncSession,
):
    user_id = uuid4()
    db_session.add(
        User(
            id=user_id,
            email=f"invalid-status-{user_id}@example.com",
            password_hash="hash",
            **{
                "legal_terms_version": LEGAL_ACCEPTANCE["legal_terms_version"],
                "legal_privacy_version": LEGAL_ACCEPTANCE["legal_privacy_version"],
            },
        )
    )
    term = PersonalizationTerm(
        user_id=user_id,
        term="InvalidStatusTerm",
        normalized_term="invalidstatusterm",
        status="active",
        source="manual",
        frequency=1,
    )
    db_session.add(term)
    await db_session.flush()
    request = UpdatePersonalizationTermRequest.model_construct(status="invalid")

    with pytest.raises(HTTPException) as exc_info:
        await update_personalization_term(
            term.id,
            request,
            user=SimpleNamespace(id=user_id),
            db=db_session,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Invalid status"


@pytest.mark.asyncio
async def test_personalization_rejects_imported_candidate(
    client: AsyncClient,
    auth_headers: dict,
):
    response = await client.post(
        "/api/personalization/imports",
        headers=auth_headers,
        data={"source_type": "text", "text": "FoobarTerm FoobarTerm"},
    )
    assert response.status_code == 202

    terms = (
        await client.get(
            "/api/personalization/terms",
            headers=auth_headers,
            params={"status": "candidate"},
        )
    ).json()
    candidate = next(term for term in terms if term["term"] == "FoobarTerm")
    update_response = await client.patch(
        f"/api/personalization/terms/{candidate['id']}",
        headers=auth_headers,
        json={"status": "rejected"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_personalization_reimport_updates_existing_candidate(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    first = await client.post(
        "/api/personalization/imports",
        headers=auth_headers,
        data={"source_type": "text", "text": "RepeatTerm RepeatTerm"},
    )
    assert first.status_code == 202

    second = await client.post(
        "/api/personalization/imports",
        headers=auth_headers,
        data={"source_type": "text", "text": "RepeatTerm RepeatTerm RepeatTerm"},
    )
    assert second.status_code == 202
    assert second.json()["candidate_count"] == 0

    result = await db_session.execute(
        select(PersonalizationTerm).where(PersonalizationTerm.normalized_term == "repeatterm")
    )
    term = result.scalar_one()
    assert term.frequency == 3
    assert str(term.import_job_id) == second.json()["id"]


@pytest.mark.asyncio
async def test_summary_personalization_instructions_include_active_terms(
    db_session: AsyncSession,
):
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    db_session.add(
        User(
            id=user_id,
            email="personalization-summary@example.com",
            password_hash="hash",
            **{
                "legal_terms_version": LEGAL_ACCEPTANCE["legal_terms_version"],
                "legal_privacy_version": LEGAL_ACCEPTANCE["legal_privacy_version"],
            },
        )
    )
    job = PersonalizationImportJob(
        user_id=user_id,
        source_type="text",
        source_name="paste",
        status="succeeded",
    )
    db_session.add(job)
    db_session.add(
        PersonalizationTerm(
            user_id=user_id,
            term="WaiComputer",
            normalized_term="waicomputer",
            status="active",
            source="manual",
            frequency=3,
        )
    )
    await db_session.flush()

    instructions = await summary_personalization_instructions(
        db_session,
        user_id=user_id,
    )

    assert "WaiComputer" in instructions
    # Canonicalization directive: fix close/misspelled matches to known spellings.
    assert "known spelling" in instructions
    assert "transcription error" in instructions


@pytest.mark.asyncio
async def test_summary_personalization_instructions_include_entity_names(
    db_session: AsyncSession,
):
    user_id = uuid4()
    db_session.add(
        User(
            id=user_id,
            email=f"entities-summary-{user_id}@example.com",
            password_hash="hash",
            **{
                "legal_terms_version": LEGAL_ACCEPTANCE["legal_terms_version"],
                "legal_privacy_version": LEGAL_ACCEPTANCE["legal_privacy_version"],
            },
        )
    )
    db_session.add_all(
        [
            Entity(user_id=user_id, type="organization", name="Meatful Cherity"),
            Entity(user_id=user_id, type="person", name="Андрей"),
            Entity(user_id=user_id, type="topic", name="generic topic"),  # excluded
        ]
    )
    await db_session.flush()

    entity_terms = await load_user_entity_terms(db_session, user_id=user_id)
    assert "Meatful Cherity" in entity_terms
    assert "Андрей" in entity_terms
    assert "generic topic" not in entity_terms  # topics are not canonicalized

    instructions = await summary_personalization_instructions(db_session, user_id=user_id)
    assert instructions is not None
    assert "Meatful Cherity" in instructions
    assert "Андрей" in instructions


@pytest.mark.asyncio
async def test_summary_personalization_instructions_return_none_without_terms(
    db_session: AsyncSession,
):
    user_id = uuid4()
    db_session.add(
        User(
            id=user_id,
            email=f"empty-summary-{user_id}@example.com",
            password_hash="hash",
            **{
                "legal_terms_version": LEGAL_ACCEPTANCE["legal_terms_version"],
                "legal_privacy_version": LEGAL_ACCEPTANCE["legal_privacy_version"],
            },
        )
    )
    await db_session.flush()

    instructions = await summary_personalization_instructions(
        db_session,
        user_id=user_id,
    )

    assert instructions is None


@pytest.mark.asyncio
async def test_load_user_keyterms_includes_replacements_and_dictation_dictionary(
    db_session: AsyncSession,
):
    user_id = uuid4()
    db_session.add(
        User(
            id=user_id,
            email=f"dictionary-keyterms-{user_id}@example.com",
            password_hash="hash",
            **{
                "legal_terms_version": LEGAL_ACCEPTANCE["legal_terms_version"],
                "legal_privacy_version": LEGAL_ACCEPTANCE["legal_privacy_version"],
            },
        )
    )
    db_session.add(
        PersonalizationTerm(
            user_id=user_id,
            term="WaiCompyuter",
            normalized_term="waicompyuter",
            replacement="WaiComputer",
            status="active",
            source="manual",
            frequency=3,
        )
    )
    db_session.add(
        DictationDictionaryWord(
            user_id=user_id,
            client_word_id=uuid4(),
            word="Bolnichny",
            replacement="больничный",
            occurred_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    keyterms = await load_user_keyterms(db_session, user_id=user_id, purpose="recording")

    assert {"WaiCompyuter", "WaiComputer", "Bolnichny", "больничный"} <= set(keyterms)


@pytest.mark.asyncio
async def test_personalization_import_job_clears_source_text(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    response = await client.post(
        "/api/personalization/imports",
        headers=auth_headers,
        data={"source_type": "text", "text": "TermOne TermOne TermTwo"},
    )
    assert response.status_code == 202
    job_id = UUID(response.json()["id"])

    job = await db_session.get(PersonalizationImportJob, job_id)
    assert job is not None
    assert job.source_text is None

    terms = (
        await db_session.execute(
            select(PersonalizationTerm).where(PersonalizationTerm.import_job_id == job_id)
        )
    ).scalars().all()
    assert terms
