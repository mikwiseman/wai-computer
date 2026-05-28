"""Tests for LLM-driven speaker name extraction.

The LLM call itself is mocked everywhere. These tests pin the apply logic:
- Existing Person matched by display_name is reused.
- Existing Person matched by alias is reused.
- Cluster already voice-matched -> name added as alias on that Person.
- Cluster unmatched and no existing Person -> a new Person is created.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core import speaker_name_extraction as snx
from app.core.speaker_name_extraction import (
    _clean_name,
    _format_transcript,
    _NameAssignment,
    _NameExtractionSchema,
    apply_extracted_names,
    extract_speaker_names,
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


class _FakeResponses:
    def __init__(self, response: object | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class _FakeClient:
    def __init__(self, responses: _FakeResponses) -> None:
        self.responses = responses


def _patch_extract_runtime(monkeypatch: pytest.MonkeyPatch, responses: _FakeResponses) -> None:
    monkeypatch.setattr(
        snx,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="sk-test", openai_llm_model="gpt-test"),
    )
    monkeypatch.setattr(snx, "get_openai_client", lambda: _FakeClient(responses))
    monkeypatch.setattr(snx, "ensure_response_completed", lambda *_args, **_kwargs: None)


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


@pytest.mark.asyncio
async def test_extract_skips_empty_no_key_and_empty_transcript_inputs(
    monkeypatch: pytest.MonkeyPatch,
):
    responses = _FakeResponses()
    _patch_extract_runtime(monkeypatch, responses)

    assert await extract_speaker_names(transcript_results=[], raw_labels=[]) == {}

    monkeypatch.setattr(
        snx,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="", openai_llm_model="gpt-test"),
    )
    assert (
        await extract_speaker_names(
            transcript_results=[
                _FakeTranscriptResult("speaker_0", "I'm Alice."),
                _FakeTranscriptResult("speaker_1", "I'm Bob."),
            ],
            raw_labels=["speaker_0", "speaker_1"],
        )
        == {}
    )

    _patch_extract_runtime(monkeypatch, responses)
    assert (
        await extract_speaker_names(
            transcript_results=[
                _FakeTranscriptResult("speaker_0", "  "),
                _FakeTranscriptResult("speaker_1", ""),
            ],
            raw_labels=["speaker_0", "speaker_1"],
        )
        == {}
    )
    assert responses.calls == []


@pytest.mark.asyncio
async def test_extract_builds_guarded_prompt_and_filters_model_output(
    monkeypatch: pytest.MonkeyPatch,
):
    response = SimpleNamespace(
        output_parsed=_NameExtractionSchema(
            assignments=[
                _NameAssignment(
                    speaker="speaker_0",
                    name="Alice",
                    confidence="medium",
                    evidence="I'm Alice.",
                ),
                _assignment("speaker_99", "Ghost"),
                _assignment("speaker_1", "MissingName"),
                _assignment("speaker_2", "Alex"),
                _assignment("speaker_3", "Alex"),
                _assignment("speaker_1", "Bob"),
                _assignment("speaker_1", "Bob"),
                _assignment("speaker_0", "x" * 120),
            ]
        )
    )
    responses = _FakeResponses(response=response)
    _patch_extract_runtime(monkeypatch, responses)

    extracted = await extract_speaker_names(
        transcript_results=[
            _FakeTranscriptResult("speaker_0", "I'm Alice."),
            _FakeTranscriptResult("speaker_1", "Bob speaking."),
            _FakeTranscriptResult("speaker_2", "Alex here."),
            _FakeTranscriptResult("speaker_3", "Alex here too."),
        ],
        raw_labels=["speaker_0", "speaker_1", "speaker_2", "speaker_3"],
    )

    assert set(extracted) == {"speaker_1"}
    assert extracted["speaker_1"].name == "Bob"
    prompt = responses.calls[0]["input"]
    assert "<transcript>" in prompt
    assert "SECURITY:" in prompt
    assert "Bob speaking." in prompt
    assert responses.calls[0]["temperature"] == 0


@pytest.mark.asyncio
async def test_extract_handles_provider_failure_and_empty_parsed_response(
    monkeypatch: pytest.MonkeyPatch,
):
    failing_responses = _FakeResponses(error=RuntimeError("provider down"))
    _patch_extract_runtime(monkeypatch, failing_responses)

    assert (
        await extract_speaker_names(
            transcript_results=[
                _FakeTranscriptResult("speaker_0", "I'm Alice."),
                _FakeTranscriptResult("speaker_1", "I'm Bob."),
            ],
            raw_labels=["speaker_0", "speaker_1"],
        )
        == {}
    )

    empty_responses = _FakeResponses(response=SimpleNamespace(output_parsed=None))
    _patch_extract_runtime(monkeypatch, empty_responses)
    assert (
        await extract_speaker_names(
            transcript_results=[
                _FakeTranscriptResult("speaker_0", "I'm Alice."),
                _FakeTranscriptResult("speaker_1", "I'm Bob."),
            ],
            raw_labels=["speaker_0", "speaker_1"],
        )
        == {}
    )


def test_name_extraction_helpers_clean_and_format_edge_cases():
    assert _clean_name("  Alice, ") == "Alice"
    assert _clean_name("  ...  ") is None
    assert _clean_name("x" * 120) is None

    formatted = _format_transcript(
        [
            _FakeTranscriptResult(None, "  Hello  "),
            _FakeTranscriptResult("speaker_1", ""),
        ]
    )
    assert formatted == "[speaker_unknown] Hello"

    long_formatted = _format_transcript([_FakeTranscriptResult("speaker_0", "x" * 9000)])
    assert len(long_formatted) == 8000


# Extraction-side guards (no LLM call; we drive extract_speaker_names
# behaviour through monkeypatching the OpenAI Responses parse call).


@pytest.mark.asyncio
async def test_extract_skips_single_speaker_recordings(monkeypatch):
    from app.core import speaker_name_extraction

    parse_calls: list[int] = []

    async def _should_not_be_called(**_kwargs):
        parse_calls.append(1)
        raise AssertionError("LLM must not be called for single-speaker input")

    monkeypatch.setattr(
        "app.core.speaker_name_extraction.get_openai_client",
        lambda: type("X", (), {"responses": type("Y", (), {"parse": _should_not_be_called})()})(),
    )
    out = await speaker_name_extraction.extract_speaker_names(
        transcript_results=[
            _FakeTranscriptResult(speaker="speaker_0", text="Hi I'm Mik."),
        ],
        raw_labels=["speaker_0"],
    )
    assert out == {}
    assert parse_calls == []


@pytest.mark.asyncio
async def test_extract_drops_duplicate_names_across_clusters(monkeypatch):
    """Two clusters both labelled 'Alex' must collapse to NEITHER."""
    from app.core import speaker_name_extraction as snx

    class _Parsed:
        assignments = [
            snx._NameAssignment(
                speaker="speaker_0", name="Alex", confidence="high",
                evidence="I'm Alex",
            ),
            snx._NameAssignment(
                speaker="speaker_2", name="Alex", confidence="high",
                evidence="I'm Alex too",
            ),
        ]

    class _Response:
        output_parsed = _Parsed()

    async def _fake_parse(**_kwargs):
        return _Response()

    monkeypatch.setattr(
        "app.core.speaker_name_extraction.get_openai_client",
        lambda: type("X", (), {"responses": type("Y", (), {"parse": _fake_parse})()})(),
    )
    monkeypatch.setattr(
        "app.core.speaker_name_extraction.ensure_response_completed",
        lambda *_a, **_k: None,
    )
    # Need an OpenAI key to bypass the early-skip.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "app.core.speaker_name_extraction.get_settings",
        lambda: type("S", (), {
            "openai_api_key": "sk-test",
            "openai_llm_model": "gpt-5.5",
        })(),
    )

    out = await snx.extract_speaker_names(
        transcript_results=[
            _FakeTranscriptResult(speaker="speaker_0", text="Hi I'm Alex."),
            _FakeTranscriptResult(speaker="speaker_1", text="Cool."),
            _FakeTranscriptResult(speaker="speaker_2", text="I'm Alex too."),
        ],
        raw_labels=["speaker_0", "speaker_1", "speaker_2"],
    )
    assert out == {}, "Duplicate name across clusters must yield no high-confidence assignments"


@pytest.mark.asyncio
async def test_extract_rejects_name_not_in_transcript(monkeypatch):
    """Pure hallucination — model returns a name that never appears in the audio."""
    from app.core import speaker_name_extraction as snx

    class _Parsed:
        assignments = [
            snx._NameAssignment(
                speaker="speaker_0", name="Phantom Person", confidence="high",
                evidence="(no such phrase)",
            ),
        ]

    class _Response:
        output_parsed = _Parsed()

    async def _fake_parse(**_kwargs):
        return _Response()

    monkeypatch.setattr(
        "app.core.speaker_name_extraction.get_openai_client",
        lambda: type("X", (), {"responses": type("Y", (), {"parse": _fake_parse})()})(),
    )
    monkeypatch.setattr(
        "app.core.speaker_name_extraction.ensure_response_completed",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.core.speaker_name_extraction.get_settings",
        lambda: type("S", (), {
            "openai_api_key": "sk-test",
            "openai_llm_model": "gpt-5.5",
        })(),
    )

    out = await snx.extract_speaker_names(
        transcript_results=[
            _FakeTranscriptResult(speaker="speaker_0", text="Hello there."),
            _FakeTranscriptResult(speaker="speaker_1", text="General Kenobi."),
        ],
        raw_labels=["speaker_0", "speaker_1"],
    )
    assert out == {}
