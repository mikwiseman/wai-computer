"""Tests for the capture sidecar parsing and owner-speaker attribution."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capture_metadata import (
    CaptureMetadataError,
    capture_metadata_from_stored,
    ensure_self_person,
    parse_capture_metadata,
    resolve_owner_raw_label,
)
from app.models.person import Person
from app.models.user import User
from tests.conftest import LEGAL_ACCEPTANCE


def _segment(speaker: str | None, start_ms: int, end_ms: int) -> SimpleNamespace:
    return SimpleNamespace(speaker=speaker, start_ms=start_ms, end_ms=end_ms)


def test_parse_capture_metadata_accepts_valid_sidecar() -> None:
    parsed = parse_capture_metadata(
        json.dumps(
            {
                "version": 1,
                "capture": "dual_mono_mix",
                "local_speech_ms": [[0, 4000], [9000, 12_000]],
                "aec": False,
            }
        )
    )
    assert parsed.capture == "dual_mono_mix"
    assert parsed.local_speech_ms == [(0, 4000), (9000, 12_000)]
    assert parsed.as_dict()["local_speech_ms"] == [[0, 4000], [9000, 12_000]]


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        json.dumps([1, 2]),
        json.dumps({"version": 2, "capture": "dual_mono_mix", "local_speech_ms": []}),
        json.dumps({"version": 1, "capture": "quantum", "local_speech_ms": []}),
        json.dumps({"version": 1, "capture": "mic_only", "local_speech_ms": [[5, 5]]}),
        json.dumps({"version": 1, "capture": "mic_only", "local_speech_ms": [[-1, 5]]}),
        json.dumps(
            {"version": 1, "capture": "mic_only", "local_speech_ms": [[0, 10], [5, 20]]}
        ),
        json.dumps(
            {"version": 1, "capture": "mic_only", "local_speech_ms": [[0, 10]], "aec": "yes"}
        ),
    ],
)
def test_parse_capture_metadata_rejects_invalid(payload: str) -> None:
    with pytest.raises(CaptureMetadataError):
        parse_capture_metadata(payload)


def test_parse_capture_metadata_rejects_oversized() -> None:
    intervals = [[i * 10, i * 10 + 5] for i in range(20_000)]
    payload = json.dumps(
        {"version": 1, "capture": "mic_only", "local_speech_ms": intervals}
    )
    with pytest.raises(CaptureMetadataError):
        parse_capture_metadata(payload)


def test_capture_metadata_from_stored_roundtrip_and_invalid() -> None:
    stored = {
        "version": 1,
        "capture": "dual_mono_mix",
        "local_speech_ms": [[0, 1000]],
        "aec": True,
    }
    parsed = capture_metadata_from_stored(stored)
    assert parsed is not None and parsed.aec is True
    assert capture_metadata_from_stored({"version": 99}) is None
    assert capture_metadata_from_stored(None) is None


def test_resolve_owner_picks_dominant_cluster() -> None:
    segments = [
        _segment("speaker_0", 0, 4000),
        _segment("speaker_1", 4000, 9000),
        _segment("speaker_0", 9000, 12_000),
    ]
    local = [(0, 3800), (9200, 12_000)]

    assert resolve_owner_raw_label(segments, local) == "speaker_0"


def test_resolve_owner_refuses_ambiguous_split() -> None:
    # Local speech spread evenly across both clusters -> no confident owner.
    segments = [
        _segment("speaker_0", 0, 4000),
        _segment("speaker_1", 4000, 8000),
    ]
    local = [(2000, 6000)]

    assert resolve_owner_raw_label(segments, local) is None


def test_resolve_owner_refuses_talkative_cluster_outside_local_speech() -> None:
    # speaker_0 talks constantly, but local mic speech is mostly speaker_1's
    # window; cluster_overlap for speaker_0 stays low -> owner must not be
    # assigned to the always-on cluster.
    segments = [
        _segment("speaker_0", 0, 60_000),
        _segment("speaker_1", 60_000, 66_000),
    ]
    local = [(60_500, 65_500)]

    assert resolve_owner_raw_label(segments, local) == "speaker_1"


def test_resolve_owner_handles_empty_inputs() -> None:
    assert resolve_owner_raw_label([], [(0, 1000)]) is None
    assert resolve_owner_raw_label([_segment("speaker_0", 0, 1000)], []) is None
    assert (
        resolve_owner_raw_label([_segment(None, 0, 1000)], [(0, 1000)]) is None
    )


@pytest.mark.asyncio
async def test_ensure_self_person_creates_once_and_reuses(db_session: AsyncSession) -> None:
    user = User(
        email=f"self-person-{uuid4()}@example.com",
        password_hash="hash",
        first_name="Мик",
        last_name="Вайзман",
        **{
            "legal_terms_version": LEGAL_ACCEPTANCE["legal_terms_version"],
            "legal_privacy_version": LEGAL_ACCEPTANCE["legal_privacy_version"],
        },
    )
    db_session.add(user)
    await db_session.flush()

    person_id = await ensure_self_person(db_session, user=user)
    assert user.self_person_id == person_id
    person = (
        await db_session.execute(select(Person).where(Person.id == person_id))
    ).scalar_one()
    assert person.display_name == "Мик Вайзман"

    again = await ensure_self_person(db_session, user=user)
    assert again == person_id


@pytest.mark.asyncio
async def test_ensure_self_person_defaults_to_you(db_session: AsyncSession) -> None:
    user = User(
        email=f"self-noname-{uuid4()}@example.com",
        password_hash="hash",
        **{
            "legal_terms_version": LEGAL_ACCEPTANCE["legal_terms_version"],
            "legal_privacy_version": LEGAL_ACCEPTANCE["legal_privacy_version"],
        },
    )
    db_session.add(user)
    await db_session.flush()

    person_id = await ensure_self_person(db_session, user=user)
    person = (
        await db_session.execute(select(Person).where(Person.id == person_id))
    ).scalar_one()
    assert person.display_name == "You"
