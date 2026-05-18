"""Tests for app/core/voice_identification.py — pgvector matching + voiceprint store."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.transcript_utils import TranscriptResult
from app.core.voice_identification import (
    identify_speakers_for_recording,
    store_voiceprint,
)
from app.models import Person, User, Voiceprint


def _write_sine_wav(path: Path, *, duration_s: float, freq_hz: float, sr: int = 16_000) -> None:
    n_samples = int(duration_s * sr)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        for i in range(n_samples):
            value = int(0.5 * 32767 * math.sin(2 * math.pi * freq_hz * i / sr))
            wf.writeframesraw(struct.pack("<h", value))


def _tr(speaker: str | None, start_ms: int, end_ms: int) -> TranscriptResult:
    return TranscriptResult(
        text="",
        speaker=speaker,
        is_final=True,
        start_ms=start_ms,
        end_ms=end_ms,
        confidence=0.0,
    )


async def _seed_user(db_session) -> User:
    user = User(email=f"vt-{uuid4().hex}@example.com")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.mark.slow
async def test_store_then_identify_same_voice_matches(db_session, tmp_path):
    """Voiceprint stored from recording A is matched on recording B with the same source."""
    user = await _seed_user(db_session)
    person = Person(user_id=user.id, display_name="Vasya")
    db_session.add(person)
    await db_session.flush()

    wav = tmp_path / "voice.wav"
    _write_sine_wav(wav, duration_s=8.0, freq_hz=220.0)
    transcripts = [_tr("Speaker 0", 0, 8000)]

    voiceprint_id = await store_voiceprint(
        db=db_session,
        user_id=user.id,
        person_id=person.id,
        staged_audio_path=wav,
        transcript_results=transcripts,
        raw_label="Speaker 0",
        source_recording_id=None,
    )
    assert voiceprint_id is not None
    await db_session.commit()

    vp_row = (
        await db_session.execute(select(Voiceprint).where(Voiceprint.id == voiceprint_id))
    ).scalar_one()
    assert vp_row.person_id == person.id
    assert vp_row.duration_s == pytest.approx(8.0, abs=0.01)

    assignments = await identify_speakers_for_recording(
        db=db_session,
        user_id=user.id,
        staged_audio_path=wav,
        transcript_results=transcripts,
    )

    assert "Speaker 0" in assignments
    match = assignments["Speaker 0"]
    assert match is not None
    matched_person_id, confidence = match
    assert matched_person_id == person.id
    assert confidence >= 0.6


@pytest.mark.slow
async def test_identify_returns_none_when_voice_does_not_match(db_session, tmp_path):
    """Unknown voice with no stored voiceprint produces None assignment."""
    user = await _seed_user(db_session)
    person = Person(user_id=user.id, display_name="Vasya")
    db_session.add(person)
    await db_session.flush()

    enrolled = tmp_path / "enrolled.wav"
    _write_sine_wav(enrolled, duration_s=8.0, freq_hz=220.0)
    enrolled_transcripts = [_tr("Speaker 0", 0, 8000)]
    await store_voiceprint(
        db=db_session,
        user_id=user.id,
        person_id=person.id,
        staged_audio_path=enrolled,
        transcript_results=enrolled_transcripts,
        raw_label="Speaker 0",
        source_recording_id=None,
    )
    await db_session.commit()

    unknown = tmp_path / "unknown.wav"
    _write_sine_wav(unknown, duration_s=8.0, freq_hz=1760.0)
    unknown_transcripts = [_tr("Speaker 0", 0, 8000)]

    assignments = await identify_speakers_for_recording(
        db=db_session,
        user_id=user.id,
        staged_audio_path=unknown,
        transcript_results=unknown_transcripts,
        threshold=0.9,
    )

    assert assignments["Speaker 0"] is None


async def test_identify_returns_empty_when_no_speaker_labels(db_session, tmp_path):
    """No raw_label values in transcript → empty assignments."""
    user = await _seed_user(db_session)
    wav = tmp_path / "silence.wav"
    _write_sine_wav(wav, duration_s=8.0, freq_hz=220.0)

    transcripts = [_tr(None, 0, 8000)]
    assignments = await identify_speakers_for_recording(
        db=db_session,
        user_id=user.id,
        staged_audio_path=wav,
        transcript_results=transcripts,
    )
    assert assignments == {}


async def test_identify_marks_short_clusters_unassigned(db_session, tmp_path):
    """Cluster shorter than 5s gets assignments[label] = None without running encoder."""
    user = await _seed_user(db_session)
    wav = tmp_path / "short.wav"
    _write_sine_wav(wav, duration_s=10.0, freq_hz=220.0)

    transcripts = [_tr("Speaker 0", 0, 2000)]
    assignments = await identify_speakers_for_recording(
        db=db_session,
        user_id=user.id,
        staged_audio_path=wav,
        transcript_results=transcripts,
    )
    assert assignments == {"Speaker 0": None}
