"""Tests for queued canonical recording audio processing."""

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.recording_audio_processing import process_staged_recording_upload
from app.core.transcript_utils import TranscriptResult
from app.models.billing import UsageWeek
from app.models.recording import Recording, RecordingStatus, Segment
from app.models.user import User


@pytest.mark.asyncio
async def test_process_staged_recording_upload_persists_canonical_segments(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="queued-processing@example.com",
        password_hash="x",
        default_language="en",
    )
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title=None,
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=datetime.now(timezone.utc),
        language="en",
    )
    db_session.add(recording)
    await db_session.commit()

    staged_path = tmp_path / "recording.wav"
    staged_path.write_bytes(b"audio")
    transcript_results = [
        TranscriptResult(
            text="Hello from queued processing.",
            speaker="speaker_0",
            is_final=True,
            start_ms=0,
            end_ms=1800,
            confidence=0.94,
        )
    ]

    transcribe = AsyncMock(return_value=transcript_results)
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        transcribe,
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_title",
        AsyncMock(return_value="Queued Recording"),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.identify_speakers_for_recording",
        AsyncMock(return_value={}),
    )

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=staged_path,
        content_type="audio/wav",
        user_default_language="en",
    )

    await db_session.refresh(recording)
    segments = (
        (await db_session.execute(select(Segment).where(Segment.recording_id == recording.id)))
        .scalars()
        .all()
    )
    assert recording.status == RecordingStatus.READY.value
    assert recording.title == "Queued Recording"
    assert recording.duration_seconds == 1
    assert [segment.content for segment in segments] == ["Hello from queued processing."]
    usage = (
        await db_session.execute(select(UsageWeek).where(UsageWeek.user_id == user.id))
    ).scalar_one()
    assert usage.words_used == 4
    assert recording.billed_word_count == 4
    assert not staged_path.exists()
    transcribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_staged_recording_upload_preserves_client_duration(
    db_session: AsyncSession,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="queued-processing-duration@example.com",
        password_hash="x",
        default_language="en",
    )
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title=None,
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=datetime.now(timezone.utc),
        language="en",
    )
    db_session.add(recording)
    await db_session.commit()

    staged_path = tmp_path / "truncated-provider.wav"
    staged_path.write_bytes(b"audio")
    transcript_results = [
        TranscriptResult(
            text="Provider only returned alice@example.com token eyJabc.def.ghi.",
            speaker="speaker_0",
            is_final=True,
            start_ms=0,
            end_ms=124_000,
            confidence=0.94,
        )
    ]

    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        AsyncMock(return_value=transcript_results),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_title",
        AsyncMock(return_value="Queued Recording"),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.identify_speakers_for_recording",
        AsyncMock(return_value={}),
    )
    sentry_breadcrumbs: list[dict[str, object]] = []

    def capture_breadcrumb(**kwargs) -> None:
        sentry_breadcrumbs.append(kwargs)

    sentry_messages: list[dict[str, object]] = []

    def capture_message(message: str, **kwargs) -> None:
        sentry_messages.append({"message": message, **kwargs})

    monkeypatch.setattr(
        "app.core.recording_audio_processing.add_sentry_breadcrumb",
        capture_breadcrumb,
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.capture_sentry_message",
        capture_message,
    )
    caplog.set_level(logging.WARNING, logger="app.core.recording_audio_processing")

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=staged_path,
        content_type="audio/wav",
        user_default_language="en",
        client_duration_seconds=1800,
        client_file_size_bytes=57_600_044,
        staged_size_bytes=57_600_044,
    )

    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.READY.value
    assert recording.duration_seconds == 1800
    assert not staged_path.exists()
    warning_messages = [record.getMessage() for record in caplog.records]
    assert any(
        "audio transcript coverage below threshold" in message
        for message in warning_messages
    )
    assert "alice@example.com" not in "\n".join(warning_messages).lower()
    assert "eyJabc" not in "\n".join(warning_messages)
    coverage_breadcrumbs = [
        item
        for item in sentry_breadcrumbs
        if item.get("message") == "Audio transcript coverage below threshold"
    ]
    assert coverage_breadcrumbs
    coverage_data = coverage_breadcrumbs[0]["data"]
    assert isinstance(coverage_data, dict)
    assert coverage_data["client_duration_seconds"] == 1800
    assert coverage_data["transcript_duration_seconds"] == 124
    assert coverage_data["coverage_ratio"] == round(124 / 1800, 4)
    assert "alice@example.com" not in repr(sentry_breadcrumbs).lower()
    assert "eyJabc" not in repr(sentry_breadcrumbs)
    assert sentry_messages == [
        {
            "message": "Audio transcript coverage below threshold",
            "level": "warning",
            "extras": coverage_data,
        }
    ]


@pytest.mark.asyncio
async def test_process_staged_recording_upload_skips_ready_recording(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="queued-idempotent@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title="Already Ready",
        type="meeting",
        status=RecordingStatus.READY.value,
        uploaded_at=datetime.now(timezone.utc),
        language="en",
    )
    db_session.add(recording)
    await db_session.commit()

    transcribe = AsyncMock()
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        transcribe,
    )

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=tmp_path / "missing.wav",
        content_type="audio/wav",
        user_default_language="en",
    )

    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.READY.value
    assert recording.title == "Already Ready"
    transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_staged_recording_upload_marks_missing_staged_file_failed(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="queued-missing-staged@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title="Missing staged file",
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=datetime.now(timezone.utc),
        language="en",
    )
    db_session.add(recording)
    await db_session.commit()

    transcribe = AsyncMock()
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        transcribe,
    )

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=tmp_path / "missing.wav",
        content_type="audio/wav",
        user_default_language="en",
    )

    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.FAILED.value
    assert recording.failure_code == "staged_file_missing"
    assert recording.failure_message == "Uploaded audio file was missing before processing."
    transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_staged_recording_upload_keeps_retryable_failure_in_processing(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="queued-retryable@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title="Retryable staged file",
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=datetime.now(timezone.utc),
        language="en",
    )
    db_session.add(recording)
    await db_session.commit()

    staged_path = tmp_path / "retryable.wav"
    staged_path.write_bytes(b"audio")
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        AsyncMock(side_effect=httpx.TimeoutException("provider timed out")),
    )

    with pytest.raises(httpx.TimeoutException):
        await process_staged_recording_upload(
            db_session,
            recording_id=recording.id,
            user_id=user.id,
            staged_path=staged_path,
            content_type="audio/wav",
            user_default_language="en",
        )

    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.PROCESSING.value
    assert recording.failure_code is None
    assert staged_path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "recording_language",
        "user_default_language",
        "placeholder",
        "expected_title",
        "expected_message",
    ),
    [
        (
            "ru",
            "en",
            "[noise]",
            "Без речи",
            "Мы не обнаружили разборчивой речи в этой записи.",
        ),
        (
            "multi",
            "ru",
            "[typing]",
            "Без речи",
            "Мы не обнаружили разборчивой речи в этой записи.",
        ),
        (
            "en",
            "ru",
            "",
            "No speech detected",
            "We could not detect clear speech in this recording.",
        ),
    ],
)
async def test_process_staged_recording_upload_fails_empty_transcript_without_title_generation(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    recording_language: str,
    user_default_language: str,
    placeholder: str,
    expected_title: str,
    expected_message: str,
) -> None:
    user = User(
        email=f"nospeech-{recording_language}-{user_default_language}@example.com",
        password_hash="x",
        default_language=user_default_language,
    )
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title=None,
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=datetime.now(timezone.utc),
        language=recording_language,
    )
    db_session.add(recording)
    await db_session.commit()

    staged_path = tmp_path / f"nospeech-{recording.id}.wav"
    staged_path.write_bytes(b"noise")
    transcript_results = []
    if placeholder:
        transcript_results.append(
            TranscriptResult(
                text=placeholder,
                speaker=None,
                is_final=True,
                start_ms=0,
                end_ms=1200,
                confidence=0.1,
            )
        )

    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        AsyncMock(return_value=transcript_results),
    )
    title_mock = AsyncMock(return_value="Wrong Title")
    monkeypatch.setattr("app.core.recording_audio_processing.generate_title", title_mock)

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=staged_path,
        content_type="audio/wav",
        user_default_language=user_default_language,
    )

    await db_session.refresh(recording)
    segments = (
        (await db_session.execute(select(Segment).where(Segment.recording_id == recording.id)))
        .scalars()
        .all()
    )
    assert recording.status == RecordingStatus.FAILED.value
    assert recording.failure_code == "transcript_empty"
    assert recording.title == expected_title
    assert recording.failure_message == expected_message
    assert segments == []
    assert not staged_path.exists()
    title_mock.assert_not_awaited()
