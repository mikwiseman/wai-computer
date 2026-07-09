"""Decoupled transcription for intent routing: transcribe once, reuse on import."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.recording_import import (
    SEGMENT_EMBEDDING_BATCH_SIZE,
    TranscribedMedia,
    _generate_imported_segment_embeddings,
    _mark_failed,
    import_media_as_recording,
    transcribe_media_bytes,
)
from app.core.summarizer import SummaryResult
from app.core.transcript_utils import FileTranscription, TranscriptResult
from app.models.recording import Recording, RecordingStatus, Segment
from app.models.user import User


async def _user(db: AsyncSession, email: str = "routing@example.com") -> User:
    user = User(email=email, password_hash="hash", default_language="ru")
    db.add(user)
    await db.flush()
    return user


def _speech(text: str = "Привет из Telegram") -> TranscriptResult:
    return TranscriptResult(
        text=text, speaker="speaker_1", is_final=True, start_ms=0, end_ms=1200, confidence=0.95
    )


def test_transcribed_media_filters_no_speech_and_exposes_plain_text():
    media = TranscribedMedia(
        transcript_results=[_speech("один два три"), _speech("(no speech detected)"), _speech("")],
        media_path=Path("/tmp/x.wav"),
        media_content_type="audio/wav",
        media_ext="wav",
    )
    # The no-speech placeholder and the empty segment drop out.
    assert [tr.text for tr in media.speech_results] == ["один два три"]
    assert media.has_speech is True
    assert media.transcript_text == "один два три"


@pytest.mark.asyncio
async def test_transcribe_media_bytes_returns_transcript_without_persisting(
    db_session: AsyncSession, monkeypatch
):
    user = await _user(db_session)
    await db_session.commit()

    async def fake_transcribe(*_args, **_kwargs):
        return FileTranscription(words=[], segments=[_speech("сколько будет один плюс два")])

    monkeypatch.setattr("app.core.recording_import.transcribe_audio_file", fake_transcribe)

    result = await transcribe_media_bytes(
        db=db_session,
        user=user,
        data=b"fake wav",
        filename="voice.wav",
        content_type="audio/wav",
        language="ru",
    )

    assert isinstance(result, TranscribedMedia)
    assert result.transcript_text == "сколько будет один плюс два"
    assert result.media_ext == "wav"
    # Nothing was filed: no recording rows exist for this user.
    count = (
        await db_session.execute(
            select(func.count()).select_from(Recording).where(Recording.user_id == user.id)
        )
    ).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_import_with_precomputed_skips_second_transcription(
    db_session: AsyncSession, monkeypatch, tmp_path
):
    user = await _user(db_session, "routing-precomputed@example.com")
    await db_session.commit()
    monkeypatch.setattr("app.core.recording_import.settings.upload_staging_dir", str(tmp_path))

    transcribe_calls = {"n": 0}

    async def counting_transcribe(*_args, **_kwargs):
        transcribe_calls["n"] += 1
        return FileTranscription(words=[], segments=[_speech("полный текст записи")])

    async def fake_embedding(_text: str, **_: object):
        raise RuntimeError("embedding offline")

    async def fake_identify(**_kwargs):
        raise RuntimeError("voice id offline")

    async def fake_summary(_transcript: str, **_kwargs):
        return SummaryResult(
            title="Запись",
            summary="Саммари.",
            key_points=[],
            decisions=[],
            action_items=[],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
            highlights=[],
        )

    monkeypatch.setattr("app.core.recording_import.transcribe_audio_file", counting_transcribe)
    monkeypatch.setattr("app.core.recording_import.generate_embedding", fake_embedding)
    monkeypatch.setattr("app.core.recording_import.identify_speakers_for_recording", fake_identify)
    monkeypatch.setattr("app.core.recording_import.summarize_transcript", fake_summary)

    # First: transcribe for routing (1 STT call).
    precomputed = await transcribe_media_bytes(
        db=db_session,
        user=user,
        data=b"fake wav",
        filename="voice.wav",
        content_type="audio/wav",
        language="ru",
    )
    assert transcribe_calls["n"] == 1

    # Then: file it reusing the transcript — must NOT transcribe again.
    result = await import_media_as_recording(
        db=db_session,
        user=user,
        data=b"fake wav",
        filename="voice.wav",
        content_type="audio/wav",
        title=None,
        source_label="telegram",
        language="ru",
        precomputed=precomputed,
    )

    assert transcribe_calls["n"] == 1  # reused, not re-transcribed
    assert result.recording.status == RecordingStatus.READY.value
    assert result.transcript == "полный текст записи"
    segments = (
        (
            await db_session.execute(
                select(Segment).where(Segment.recording_id == result.recording.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(segments) == 1
    assert segments[0].content == "полный текст записи"


@pytest.mark.asyncio
async def test_mark_failed_keeps_ready_import_recording_terminal(db_session: AsyncSession):
    user = await _user(db_session, email="ready-import@example.com")
    recording = Recording(
        user_id=user.id,
        title="Ready import",
        type="note",
        status=RecordingStatus.READY.value,
        failure_code=None,
        failure_message=None,
    )
    db_session.add(recording)
    await db_session.commit()
    recording_id = recording.id

    marked = await _mark_failed(
        db=db_session,
        recording_id=recording_id,
        code="late_processing_failed",
        message="Late import failure after ready.",
    )

    assert marked is recording
    db_session.expire_all()
    refreshed = (
        await db_session.execute(select(Recording).where(Recording.id == recording_id))
    ).scalar_one()
    assert refreshed.status == RecordingStatus.READY.value
    assert refreshed.failure_code is None
    assert refreshed.failure_message is None


@pytest.mark.asyncio
async def test_import_batches_multi_segment_embeddings(
    db_session: AsyncSession, monkeypatch, tmp_path
):
    user = await _user(db_session, "routing-batch-embeddings@example.com")
    await db_session.commit()
    monkeypatch.setattr("app.core.recording_import.settings.upload_staging_dir", str(tmp_path))

    async def fake_transcribe(*_args, **_kwargs):
        return FileTranscription(
            words=[], segments=[_speech("один"), _speech("два"), _speech("три")]
        )

    async def fail_single_embedding(_text: str, **_: object):
        raise AssertionError("multi-segment imports must use batch embeddings")

    embedding_batches: list[list[str]] = []

    async def fake_embeddings(texts: list[str], **_: object):
        embedding_batches.append(list(texts))
        return [[0.1] * 1536, [0.2] * 1536, [0.3] * 1536]

    async def fake_identify(**_kwargs):
        return {}

    async def fake_summary(_transcript: str, **_kwargs):
        return SummaryResult(
            title="Запись",
            summary="Саммари.",
            key_points=[],
            decisions=[],
            action_items=[],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
            highlights=[],
        )

    monkeypatch.setattr("app.core.recording_import.transcribe_audio_file", fake_transcribe)
    monkeypatch.setattr("app.core.recording_import.generate_embedding", fail_single_embedding)
    monkeypatch.setattr(
        "app.core.recording_import.generate_embeddings",
        fake_embeddings,
        raising=False,
    )
    monkeypatch.setattr("app.core.recording_import.identify_speakers_for_recording", fake_identify)
    monkeypatch.setattr("app.core.recording_import.summarize_transcript", fake_summary)

    result = await import_media_as_recording(
        db=db_session,
        user=user,
        data=b"fake wav",
        filename="meeting.wav",
        content_type="audio/wav",
        title=None,
        source_label="upload",
        language="ru",
    )

    assert result.recording.status == RecordingStatus.READY.value
    assert result.transcript == "один два три"
    assert embedding_batches == [["один", "два", "три"]]


@pytest.mark.asyncio
async def test_import_embedding_batches_stop_after_systemic_provider_failure(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _user(db_session, "routing-embedding-timeout@example.com")
    recording = Recording(user_id=user.id, title="Provider down", type="note")
    db_session.add(recording)
    await db_session.flush()

    generate = AsyncMock(side_effect=httpx.TimeoutException("provider timeout"))
    monkeypatch.setattr("app.core.recording_import.generate_embeddings", generate)

    texts = ["segment"] * (SEGMENT_EMBEDDING_BATCH_SIZE + 1)
    embeddings = await _generate_imported_segment_embeddings(
        recording=recording,
        user_id=user.id,
        texts=texts,
    )

    assert embeddings == [None] * len(texts)
    generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_prefers_known_media_duration_over_provider_timestamp_drift(
    db_session: AsyncSession, monkeypatch, tmp_path
):
    user = await _user(db_session, "routing-duration@example.com")
    await db_session.commit()
    monkeypatch.setattr("app.core.recording_import.settings.upload_staging_dir", str(tmp_path))

    async def fake_transcribe(*_args, **_kwargs):
        return FileTranscription(
            words=[],
            segments=[
                TranscriptResult(
                    text="длинная встреча",
                    speaker="speaker_0",
                    is_final=True,
                    start_ms=0,
                    end_ms=(46 * 60 + 51) * 1000,
                    confidence=0.95,
                )
            ],
        )

    async def fake_embedding(_text: str, **_: object):
        return None

    async def fake_identify(**_kwargs):
        return {}

    async def fake_summary(_transcript: str, **_kwargs):
        return SummaryResult(
            title="Встреча",
            summary="Саммари.",
            key_points=[],
            decisions=[],
            action_items=[],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
            highlights=[],
        )

    monkeypatch.setattr("app.core.recording_import.transcribe_audio_file", fake_transcribe)
    monkeypatch.setattr("app.core.recording_import.generate_embedding", fake_embedding)
    monkeypatch.setattr("app.core.recording_import.identify_speakers_for_recording", fake_identify)
    monkeypatch.setattr("app.core.recording_import.summarize_transcript", fake_summary)

    result = await import_media_as_recording(
        db=db_session,
        user=user,
        data=b"fake wav",
        filename="meeting.wav",
        content_type="audio/wav",
        title=None,
        source_label="upload",
        language="ru",
        duration_seconds=35 * 60,
    )

    assert result.recording.status == RecordingStatus.READY.value
    assert result.recording.duration_seconds == 35 * 60
