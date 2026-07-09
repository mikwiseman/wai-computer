"""Tests for queued canonical recording audio processing."""

import asyncio
import logging
import wave
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import recording_audio_processing
from app.core.media_audio import MediaAudioExtractionError
from app.core.recording_audio_processing import process_staged_recording_upload
from app.core.summary_generation import (
    WAITING_FOR_TRANSCRIPT_HASH,
    WAITING_FOR_TRANSCRIPT_STAGE,
)
from app.core.transcript_utils import FileTranscription, TranscriptResult
from app.models.billing import UsageWeek
from app.models.person import Person, RecordingSpeakerEmbedding
from app.models.recording import (
    Recording,
    RecordingStatus,
    Segment,
    SummaryGenerationJob,
    SummaryGenerationStatus,
)
from app.models.user import User


class _CompletedProbe:
    def __init__(self, *, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


@pytest.fixture(autouse=True)
def _stub_summary_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        recording_audio_processing,
        "_enqueue_recording_summary_generation",
        lambda job_id: "celery-recording-summary",
    )


def test_ffprobe_duration_seconds_parses_duration(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return _CompletedProbe(stdout="12.345\n")

    monkeypatch.setattr(recording_audio_processing.subprocess, "run", run)

    assert recording_audio_processing._ffprobe_duration_seconds(tmp_path / "clip.m4a") == 12.345
    args, kwargs = calls[0]
    assert args[0] == "ffprobe"
    assert kwargs["timeout"] == recording_audio_processing.AUDIO_DURATION_PROBE_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "probe_result",
    [
        _CompletedProbe(returncode=1, stdout=""),
        _CompletedProbe(returncode=0, stdout=""),
        _CompletedProbe(returncode=0, stdout="not-a-number\n"),
        _CompletedProbe(returncode=0, stdout="-1\n"),
    ],
)
def test_ffprobe_duration_seconds_rejects_bad_results(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    probe_result: _CompletedProbe,
) -> None:
    monkeypatch.setattr(
        recording_audio_processing.subprocess,
        "run",
        lambda *_args, **_kwargs: probe_result,
    )

    with pytest.raises(recording_audio_processing.AudioDurationProbeError):
        recording_audio_processing._ffprobe_duration_seconds(tmp_path / "clip.m4a")


def test_ffprobe_duration_seconds_maps_subprocess_errors(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run(*_args, **_kwargs):
        raise OSError("ffprobe missing")

    monkeypatch.setattr(recording_audio_processing.subprocess, "run", run)

    with pytest.raises(recording_audio_processing.AudioDurationProbeError):
        recording_audio_processing._ffprobe_duration_seconds(tmp_path / "clip.m4a")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content_type", "ext", "payload"),
    [
        ("audio/mp4; codecs=mp4a", "m4a", b"m4a-audio"),
        ("audio/m4a", "m4a", b"m4a-audio"),
        ("audio/x-m4a", "m4a", b"m4a-audio"),
        ("audio/wav", "wav", b"wav-audio"),
        ("audio/mpeg", "mp3", b"mp3-audio"),
    ],
)
async def test_extract_staged_media_audio_keeps_provider_ready_containers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    content_type: str,
    ext: str,
    payload: bytes,
) -> None:
    def run(*_args, **_kwargs):
        raise AssertionError("ffmpeg should not run for Deepgram-supported containers")

    monkeypatch.setattr(recording_audio_processing.subprocess, "run", run)
    staged = tmp_path / f"recording.{ext}"
    staged.write_bytes(payload)

    extracted = await recording_audio_processing._extract_staged_media_audio(
        staged,
        content_type=content_type,
    )

    assert extracted is None  # provider-ready audio passes through untouched
    assert staged.read_bytes() == payload


@pytest.mark.asyncio
async def test_extract_staged_media_audio_reduces_video_to_flac(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    staged = tmp_path / "recording.mp4"
    staged.write_bytes(b"mp4-video")

    async def fake_extract(source, dest):
        assert source == staged
        dest.write_bytes(b"flac-audio")
        return dest

    monkeypatch.setattr(recording_audio_processing, "extract_audio_to_flac", fake_extract)

    extracted = await recording_audio_processing._extract_staged_media_audio(
        staged,
        content_type="video/mp4",
    )

    assert extracted is not None
    extracted_path, extracted_content_type, extracted_size = extracted
    assert extracted_path.name == "recording.stt.flac"
    assert extracted_content_type == "audio/flac"
    assert extracted_size == len(b"flac-audio")
    assert not staged.exists()  # the original video is dropped after extraction


def test_audio_processing_helper_edge_branches() -> None:
    existing = SimpleNamespace(title="Existing", language="en", failure_message="old")
    recording_audio_processing.apply_no_speech_result(existing)
    assert existing.title == "Existing"
    assert existing.failure_message is None

    untitled = SimpleNamespace(title=None, language="ru", failure_message=None)
    recording_audio_processing.apply_no_speech_result(untitled)
    assert untitled.title == "Без речи"
    assert untitled.failure_message == "Мы не обнаружили разборчивой речи в этой записи."

    assert (
        recording_audio_processing.recording_processing_slow_threshold_ms(None)
        == recording_audio_processing.PROCESSING_SLOW_MIN_THRESHOLD_MS
    )


def test_voice_identification_size_guard_does_not_emit_ops_anomaly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentry_anomalies: list[dict[str, object]] = []
    monkeypatch.setattr(
        recording_audio_processing,
        "settings",
        SimpleNamespace(
            voice_identification_enabled=True,
            voice_identification_max_audio_seconds=3600,
            voice_identification_max_audio_bytes=30 * 1024 * 1024,
        ),
    )
    monkeypatch.setattr(
        recording_audio_processing,
        "capture_sentry_anomaly",
        lambda *args, **kwargs: sentry_anomalies.append(
            {"args": args, "kwargs": kwargs}
        ),
    )

    enabled = recording_audio_processing.voice_identification_enabled_for_audio(
        recording_id=uuid4(),
        duration_seconds=4119.4,
        staged_size_bytes=131_820_844,
    )

    assert enabled is False
    assert sentry_anomalies == []


def test_provider_reported_audio_too_short_false_branches() -> None:
    assert not recording_audio_processing._provider_reported_audio_too_short(RuntimeError("x"))

    request = httpx.Request("POST", "https://api.deepgram.com/v1/listen")
    responses = [
        httpx.Response(
            500,
            json={"detail": {"status": "audio_too_short"}},
            request=request,
        ),
        httpx.Response(400, content=b"not-json", request=request),
        httpx.Response(400, json=[], request=request),
        httpx.Response(400, json={"detail": "audio_too_short"}, request=request),
    ]
    for response in responses:
        error = httpx.HTTPStatusError("provider error", request=request, response=response)
        assert not recording_audio_processing._provider_reported_audio_too_short(error)


def test_terminal_provider_failure_details_classifies_only_non_retryable_http_4xx() -> None:
    def error_for(status_code: int) -> httpx.HTTPStatusError:
        request = httpx.Request("POST", "https://api.deepgram.com/v1/listen")
        response = httpx.Response(status_code, json={"err_code": "provider_error"}, request=request)
        return httpx.HTTPStatusError("provider error", request=request, response=response)

    assert recording_audio_processing._terminal_provider_failure_details(RuntimeError("x")) is None
    assert recording_audio_processing._terminal_provider_failure_details(error_for(429)) is None
    assert recording_audio_processing._terminal_provider_failure_details(error_for(500)) is None
    assert recording_audio_processing._terminal_provider_failure_details(error_for(413)) == (
        "provider_audio_too_large",
        "The transcription provider rejected this audio because it is too large.",
    )
    assert recording_audio_processing._terminal_provider_failure_details(error_for(401)) == (
        "provider_auth_failed",
        "Transcription is temporarily unavailable. Please try again later.",
    )
    assert recording_audio_processing._terminal_provider_failure_details(error_for(422)) == (
        "provider_rejected_audio",
        "The transcription provider rejected this audio file.",
    )
    assert recording_audio_processing._terminal_provider_failure_details(error_for(404)) == (
        "provider_request_failed",
        "The transcription provider rejected this transcription request.",
    )


@pytest.mark.asyncio
async def test_mark_recording_processing_failed_missing_recording_noops(
    db_session: AsyncSession,
) -> None:
    await recording_audio_processing.mark_recording_processing_failed(
        db_session,
        recording_id=uuid4(),
        failure_code="missing",
        failure_message="Missing recording",
    )


@pytest.mark.asyncio
async def test_mark_recording_processing_failed_keeps_ready_recording_terminal(
    db_session: AsyncSession,
) -> None:
    user = User(email="ready-processing-terminal@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title="Already transcribed",
        type="meeting",
        status=RecordingStatus.READY.value,
        uploaded_at=datetime.now(timezone.utc),
        language="en",
    )
    db_session.add(recording)
    await db_session.commit()

    await recording_audio_processing.mark_recording_processing_failed(
        db_session,
        recording_id=recording.id,
        failure_code="processing_timeout",
        failure_message="Late timeout after processing completed.",
    )

    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.READY.value
    assert recording.title == "Already transcribed"
    assert recording.failure_code is None
    assert recording.failure_message is None


@pytest.mark.asyncio
async def test_mark_recording_processing_failed_fails_waiting_summary_job(
    db_session: AsyncSession,
) -> None:
    user = User(email="processing-summary-waiting@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title="Processing",
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=datetime.now(timezone.utc),
        language="en",
    )
    db_session.add(recording)
    await db_session.flush()
    job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.QUEUED.value,
        stage=WAITING_FOR_TRANSCRIPT_STAGE,
        progress_percent=5,
        transcript_hash=WAITING_FOR_TRANSCRIPT_HASH,
    )
    db_session.add(job)
    await db_session.commit()

    await recording_audio_processing.mark_recording_processing_failed(
        db_session,
        recording_id=recording.id,
        failure_code="provider_rejected_audio",
        failure_message="The transcription provider rejected this audio file.",
    )

    await db_session.refresh(recording)
    await db_session.refresh(job)
    assert recording.status == RecordingStatus.FAILED.value
    assert recording.failure_code == "provider_rejected_audio"
    assert job.status == SummaryGenerationStatus.FAILED.value
    assert job.stage == "failed"
    assert job.progress_percent == 100
    assert job.error_code == "recording_processing_failed"
    assert job.failed_at is not None


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

    transcribe = AsyncMock(return_value=FileTranscription(segments=transcript_results, words=[]))
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
    monkeypatch.setattr(
        "app.core.recording_audio_processing.extract_speaker_names",
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
    summary_job = (
        await db_session.execute(
            select(SummaryGenerationJob).where(
                SummaryGenerationJob.recording_id == recording.id
            )
        )
    ).scalar_one()
    assert usage.words_used == 4
    assert recording.billed_word_count == 4
    assert summary_job.status == SummaryGenerationStatus.QUEUED.value
    assert summary_job.task_id == "celery-recording-summary"
    assert not staged_path.exists()
    transcribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_staged_recording_upload_marks_failed_on_media_extraction_error(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="queued-extraction-failure@example.com",
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

    staged_path = tmp_path / "recording.mp4"
    staged_path.write_bytes(b"video")
    monkeypatch.setattr(
        "app.core.recording_audio_processing._extract_staged_media_audio",
        AsyncMock(side_effect=MediaAudioExtractionError("bad_media", "no audio track")),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.capture_sentry_anomaly",
        MagicMock(),
    )

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=staged_path,
        content_type="video/mp4",
        user_default_language="en",
    )

    await db_session.refresh(recording)
    segments = (
        (await db_session.execute(select(Segment).where(Segment.recording_id == recording.id)))
        .scalars()
        .all()
    )
    assert recording.status == RecordingStatus.FAILED.value
    assert recording.failure_code == "bad_media"
    assert segments == []


@pytest.mark.asyncio
async def test_process_staged_recording_upload_sends_m4a_container_to_provider(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="queued-m4a-processing@example.com",
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

    staged_path = tmp_path / "recording.m4a"
    staged_path.write_bytes(b"m4a-audio")
    transcript_results = [
        TranscriptResult(
            text="Hello from normalized audio.",
            speaker="speaker_0",
            is_final=True,
            start_ms=0,
            end_ms=1800,
            confidence=0.94,
        )
    ]

    stt_payloads: list[bytes] = []

    async def capture_transcribe(media_path, **kwargs):
        # The staged file is deleted after processing; capture at call time.
        stt_payloads.append(media_path.read_bytes())
        return FileTranscription(segments=transcript_results, words=[])

    transcribe = AsyncMock(side_effect=capture_transcribe)
    monkeypatch.setattr(
        "app.core.recording_audio_processing._ffprobe_duration_seconds",
        lambda *_args, **_kwargs: 12.0,
    )
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
        AsyncMock(return_value="Normalized Recording"),
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
        content_type="audio/mp4",
        user_default_language="en",
        client_duration_seconds=12,
        staged_size_bytes=staged_path.stat().st_size,
    )

    transcribe.assert_awaited_once()
    _, kwargs = transcribe.await_args
    assert kwargs["content_type"] == "audio/mp4"
    assert stt_payloads == [b"m4a-audio"]  # original container streamed by path
    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.READY.value
    assert not staged_path.exists()


@pytest.mark.asyncio
async def test_process_staged_recording_upload_skips_when_segments_already_exist(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Idempotency guard: a requeued/retried/duplicate task must NOT re-call
    Deepgram if the recording was already transcribed (2026-05-31 cost incident)."""
    user = User(email="idempotent@example.com", password_hash="x", default_language="en")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title="Existing",
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=datetime.now(timezone.utc),
        language="en",
    )
    db_session.add(recording)
    await db_session.flush()
    db_session.add(
        Segment(
            recording_id=recording.id,
            speaker="speaker_0",
            raw_label="speaker_0",
            content="already transcribed",
            start_ms=0,
            end_ms=1000,
            confidence=0.9,
        )
    )
    await db_session.commit()

    staged_path = tmp_path / "recording.wav"
    staged_path.write_bytes(b"audio")
    transcribe = AsyncMock()
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file", transcribe
    )

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=staged_path,
        content_type="audio/wav",
        user_default_language="en",
    )

    transcribe.assert_not_awaited()  # MUST NOT re-bill Deepgram
    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.READY.value
    assert not staged_path.exists()


@pytest.mark.asyncio
async def test_process_staged_recording_upload_marks_failed_on_guard_rejection(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cost/abuse guard rejection (kill-switch / breaker / budget / max-duration)
    must mark the recording FAILED with the guard code and NOT retry or re-bill."""
    from app.core.transcription_guard import TranscriptionGuardError

    user = User(email="guard-reject@example.com", password_hash="x", default_language="en")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title="Guarded",
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=datetime.now(timezone.utc),
        language="en",
    )
    db_session.add(recording)
    await db_session.commit()

    staged_path = tmp_path / "recording.wav"
    staged_path.write_bytes(b"audio")

    async def _raise_guard(*_args, **_kwargs):
        raise TranscriptionGuardError(
            "transcription_halted", "Transcription is temporarily disabled."
        )

    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file", _raise_guard
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
    assert recording.status == RecordingStatus.FAILED.value
    assert recording.failure_code == "transcription_halted"
    assert not staged_path.exists()


@pytest.mark.asyncio
async def test_process_staged_recording_upload_survives_title_and_embedding_failures(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recording still completes READY when the (best-effort) title generation
    and per-segment embedding steps fail — these are degraded-path branches, not
    hard failures. Exercises the title-gen + embedding degraded handlers."""
    user = User(email="degraded@example.com", password_hash="x", default_language="en")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title=None,  # force title generation to run (and fail)
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
            text="Degraded path still completes.",
            speaker="speaker_0",
            is_final=True,
            start_ms=0,
            end_ms=1500,
            confidence=0.9,
        )
    ]

    async def _fail_title(*_args, **_kwargs):
        raise RuntimeError("title model offline")

    async def _fail_embedding(*_args, **_kwargs):
        raise RuntimeError("embedding model offline")

    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        AsyncMock(return_value=FileTranscription(segments=transcript_results, words=[])),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_embedding", _fail_embedding
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_title", _fail_title
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
    # Completes READY despite both degraded paths; title left None on failure.
    assert recording.status == RecordingStatus.READY.value
    assert recording.title is None
    segments = (
        (await db_session.execute(select(Segment).where(Segment.recording_id == recording.id)))
        .scalars()
        .all()
    )
    assert [s.content for s in segments] == ["Degraded path still completes."]
    assert not staged_path.exists()


@pytest.mark.asyncio
async def test_process_staged_recording_upload_commits_transcript_before_embedding_tail(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transcript persistence must not depend on the long best-effort embedding tail."""
    user = User(email="durable-transcript@example.com", password_hash="x", default_language="en")
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

    staged_path = tmp_path / "durable-transcript.wav"
    staged_path.write_bytes(b"audio")
    transcript_results = [
        TranscriptResult(
            text="Durable transcript survives cancellation.",
            speaker="speaker_0",
            is_final=True,
            start_ms=0,
            end_ms=2400,
            confidence=0.93,
        )
    ]

    async def _cancel_embedding(*_args, **_kwargs):
        raise asyncio.CancelledError()

    transcribe = AsyncMock(return_value=FileTranscription(segments=transcript_results, words=[]))
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        transcribe,
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_embedding",
        _cancel_embedding,
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_title",
        AsyncMock(return_value="Durable Transcript"),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.identify_speakers_for_recording",
        AsyncMock(return_value={}),
    )

    with pytest.raises(asyncio.CancelledError):
        await process_staged_recording_upload(
            db_session,
            recording_id=recording.id,
            user_id=user.id,
            staged_path=staged_path,
            content_type="audio/wav",
            user_default_language="en",
        )

    await db_session.rollback()
    await db_session.refresh(recording)
    segments = (
        (await db_session.execute(select(Segment).where(Segment.recording_id == recording.id)))
        .scalars()
        .all()
    )
    summary_job = (
        await db_session.execute(
            select(SummaryGenerationJob).where(SummaryGenerationJob.recording_id == recording.id)
        )
    ).scalar_one()

    assert recording.status == RecordingStatus.READY.value
    assert [segment.content for segment in segments] == [
        "Durable transcript survives cancellation."
    ]
    assert summary_job.status == SummaryGenerationStatus.QUEUED.value
    assert not staged_path.exists()


@pytest.mark.asyncio
async def test_process_staged_recording_upload_commits_transcript_before_billing(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="billing-degraded@example.com", password_hash="x", default_language="en")
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

    staged_path = tmp_path / "billing-degraded.wav"
    staged_path.write_bytes(b"audio")
    retry_path = tmp_path / "retry.wav"
    retry_path.write_bytes(b"audio")
    transcript_results = [
        TranscriptResult(
            text="Transcript must survive billing ledger failures.",
            speaker="speaker_0",
            is_final=True,
            start_ms=0,
            end_ms=2600,
            confidence=0.93,
        )
    ]

    async def _fail_billing(*_args, **_kwargs):
        raise RuntimeError("billing ledger unavailable")

    transcribe = AsyncMock(return_value=FileTranscription(segments=transcript_results, words=[]))
    degraded: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        transcribe,
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.record_recording_transcript_words",
        _fail_billing,
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_title",
        AsyncMock(return_value="Billing Degraded"),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.identify_speakers_for_recording",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.capture_sentry_anomaly",
        lambda alert_code, message, *, category, extras, level="warning": degraded.append(
            {
                "alert_code": alert_code,
                "message": message,
                "category": category,
                "extras": extras,
                "level": level,
            }
        ),
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
    summary_job = (
        await db_session.execute(
            select(SummaryGenerationJob).where(SummaryGenerationJob.recording_id == recording.id)
        )
    ).scalar_one()

    assert recording.status == RecordingStatus.READY.value
    assert recording.failure_code is None
    assert [segment.content for segment in segments] == [
        "Transcript must survive billing ledger failures."
    ]
    assert summary_job.status == SummaryGenerationStatus.QUEUED.value
    assert not staged_path.exists()
    assert len(degraded) == 1
    degraded_extras = degraded[0]["extras"]
    assert isinstance(degraded_extras, dict)
    assert degraded == [
        {
            "alert_code": "recording.billing.degraded",
            "message": "Recording completed with degraded billing ledger",
            "category": "recording",
            "extras": {
                "recording_id": str(recording.id),
                "error_type": "RuntimeError",
                "error_fingerprint": degraded_extras["error_fingerprint"],
            },
            "level": "warning",
        }
    ]

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=retry_path,
        content_type="audio/wav",
        user_default_language="en",
    )

    transcribe.assert_awaited_once()
    assert not retry_path.exists()


@pytest.mark.asyncio
async def test_process_staged_recording_upload_batches_segment_embeddings(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="batched-embeddings@example.com", password_hash="x")
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

    staged_path = tmp_path / "batched-embeddings.wav"
    staged_path.write_bytes(b"audio")
    transcript_results = [
        TranscriptResult(
            text="First segment.",
            speaker="speaker_0",
            is_final=True,
            start_ms=0,
            end_ms=1000,
            confidence=0.93,
        ),
        TranscriptResult(
            text="Second segment.",
            speaker="speaker_1",
            is_final=True,
            start_ms=1000,
            end_ms=2000,
            confidence=0.94,
        ),
    ]
    batched_calls: list[dict[str, object]] = []

    async def _generate_embeddings(texts: list[str], **kwargs: object) -> list[list[float]]:
        batched_calls.append({"texts": texts, "kwargs": kwargs})
        return [[0.2] * 1536, [0.3] * 1536]

    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        AsyncMock(return_value=FileTranscription(segments=transcript_results, words=[])),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_title",
        AsyncMock(return_value="Batch Title"),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.identify_speakers_for_recording",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.extract_speaker_names",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        recording_audio_processing,
        "generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        recording_audio_processing,
        "generate_embeddings",
        _generate_embeddings,
        raising=False,
    )

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=staged_path,
        content_type="audio/wav",
        user_default_language="en",
    )

    assert len(batched_calls) == 1
    assert batched_calls[0]["texts"] == [
        "Batch Title › First segment.",
        "Batch Title › Second segment.",
    ]
    kwargs = batched_calls[0]["kwargs"]
    assert kwargs["usage_user_id"] == user.id
    assert kwargs["usage_recording_id"] == recording.id
    assert kwargs["usage_feature"] == "recording"
    assert kwargs["usage_operation"] == "embedding.segment.batch"

    segments = (
        (
            await db_session.execute(
                select(Segment)
                .where(Segment.recording_id == recording.id)
                .order_by(Segment.start_ms)
            )
        )
        .scalars()
        .all()
    )
    assert [list(segment.embedding) for segment in segments] == [
        [0.2] * 1536,
        [0.3] * 1536,
    ]


@pytest.mark.asyncio
async def test_process_staged_recording_upload_marks_failed_on_non_retryable_error(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-retryable transcription error marks the recording FAILED with
    processing_failed, deletes the staged file, and re-raises (final handler)."""
    user = User(email="hardfail@example.com", password_hash="x", default_language="en")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title="X",
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=datetime.now(timezone.utc),
        language="en",
    )
    db_session.add(recording)
    await db_session.commit()

    staged_path = tmp_path / "recording.wav"
    staged_path.write_bytes(b"audio")

    async def _hard_fail(*_args, **_kwargs):
        raise ValueError("unrecoverable provider response")  # non-retryable

    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file", _hard_fail
    )

    with pytest.raises(ValueError):
        await process_staged_recording_upload(
            db_session,
            recording_id=recording.id,
            user_id=user.id,
            staged_path=staged_path,
            content_type="audio/wav",
            user_default_language="en",
        )

    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.FAILED.value
    assert recording.failure_code == "processing_failed"
    assert not staged_path.exists()


@pytest.mark.asyncio
async def test_process_staged_recording_upload_marks_deepgram_400_terminal(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="terminal-provider-400@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title="Provider rejected audio",
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=datetime.now(timezone.utc),
        language="multi",
    )
    db_session.add(recording)
    await db_session.commit()

    staged_path = tmp_path / "provider-rejected.m4a"
    staged_path.write_bytes(b"bad-media")
    request = httpx.Request("POST", "https://api.deepgram.com/v1/listen")
    response = httpx.Response(
        400,
        json={
            "err_code": "Bad Request",
            "err_msg": "Bad Request: failed to process audio: corrupt or unsupported data",
            "request_id": "dg-request-123",
        },
        request=request,
    )
    error = httpx.HTTPStatusError(
        "Client error '400 Bad Request'",
        request=request,
        response=response,
    )
    sentry_anomalies: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app.core.recording_audio_processing._ffprobe_duration_seconds",
        lambda *_args, **_kwargs: 12.0,
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        AsyncMock(side_effect=error),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing._extract_staged_media_audio",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.capture_sentry_anomaly",
        lambda alert_code, message, *, category, extras, level="warning": sentry_anomalies.append(
            {
                "alert_code": alert_code,
                "message": message,
                "category": category,
                "extras": extras,
                "level": level,
            }
        ),
    )

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=staged_path,
        content_type="audio/mp4",
        user_default_language="en",
        client_duration_seconds=12,
        staged_size_bytes=staged_path.stat().st_size,
    )

    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.FAILED.value
    assert recording.failure_code == "provider_rejected_audio"
    assert recording.failure_message == "The transcription provider rejected this audio file."
    assert not staged_path.exists()
    assert len(sentry_anomalies) == 1
    anomaly = sentry_anomalies[0]
    assert anomaly["alert_code"] == "recording.processing.provider_rejected"
    assert anomaly["message"] == "Recording provider rejected uploaded audio"
    assert anomaly["category"] == "recording"
    assert anomaly["level"] == "warning"
    extras = anomaly["extras"]
    assert isinstance(extras["provider_error_fingerprint"], str)
    assert len(extras["provider_error_fingerprint"]) == 12
    assert extras == {
        "recording_id": str(recording.id),
        "provider_status_code": 400,
        "provider_error_code": "Bad Request",
        "provider_error_fingerprint": extras["provider_error_fingerprint"],
        "content_type": "audio/mp4",
        "staged_size_bytes": 9,
        "audio_duration_seconds": 12.0,
        "client_duration_seconds": 12,
    }


@pytest.mark.asyncio
async def test_process_staged_recording_upload_applies_extracted_speaker_names(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When name-introduction parsing yields names, they are applied to the
    speaker clusters (covers the apply_extracted_names branch)."""
    user = User(email="names@example.com", password_hash="x", default_language="en")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title="X",
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
            text="Hi, I'm Mik.",
            speaker="speaker_0",
            is_final=True,
            start_ms=0,
            end_ms=1500,
            confidence=0.95,
        )
    ]

    apply_mock = AsyncMock(return_value={"speaker_0": "Mik"})
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        AsyncMock(return_value=FileTranscription(segments=transcript_results, words=[])),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_title",
        AsyncMock(return_value="Intro"),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.identify_speakers_for_recording",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.extract_speaker_names",
        AsyncMock(return_value={"speaker_0": "Mik"}),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.apply_extracted_names", apply_mock
    )

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=staged_path,
        content_type="audio/wav",
        user_default_language="en",
    )

    apply_mock.assert_awaited_once()
    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.READY.value


@pytest.mark.asyncio
async def test_process_staged_recording_upload_stores_speaker_embeddings_and_assignments(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="queued-processing-voice-id@example.com",
        password_hash="x",
        default_language="en",
    )
    db_session.add(user)
    await db_session.flush()
    person = Person(user_id=user.id, display_name="Mik")
    db_session.add(person)
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

    staged_path = tmp_path / "voice-id.wav"
    staged_path.write_bytes(b"audio")
    transcript_results = [
        TranscriptResult(
            text="A long enough speaker sample.",
            speaker="speaker_0",
            is_final=True,
            start_ms=2_000,
            end_ms=9_500,
            confidence=0.94,
        )
    ]
    fake_embedding = [0.25] * 192

    monkeypatch.setattr(recording_audio_processing.settings, "voice_identification_enabled", True)
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        AsyncMock(return_value=FileTranscription(segments=transcript_results, words=[])),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_title",
        AsyncMock(return_value="Voice ID Recording"),
    )
    monkeypatch.setattr(
        "app.core.voice_identification.compute_voice_embedding_spans",
        lambda *_: fake_embedding,
    )
    monkeypatch.setattr(
        "app.core.voice_identification._best_voiceprint_match",
        AsyncMock(return_value=(person.id, 0.93)),
    )

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=staged_path,
        content_type="audio/wav",
        user_default_language="en",
    )

    segment = (
        await db_session.execute(select(Segment).where(Segment.recording_id == recording.id))
    ).scalar_one()
    assert segment.person_id == person.id
    assert segment.auto_assigned is True
    assert segment.match_confidence == 0.93

    sample = (
        await db_session.execute(
            select(RecordingSpeakerEmbedding).where(
                RecordingSpeakerEmbedding.recording_id == recording.id,
                RecordingSpeakerEmbedding.raw_label == "speaker_0",
            )
        )
    ).scalar_one()
    assert sample.user_id == user.id
    assert sample.start_ms == 2_000
    assert sample.end_ms == 9_500
    assert sample.duration_s == 7.5
    assert list(sample.embedding) == fake_embedding


@pytest.mark.asyncio
async def test_process_staged_recording_upload_skips_voice_identification_for_oversized_audio(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="queued-voice-id-skip@example.com",
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

    staged_path = tmp_path / "long-recording.m4a"
    staged_path.write_bytes(b"audio")
    transcript_results = [
        TranscriptResult(
            text="A long recording should still save its transcript.",
            speaker="speaker_0",
            is_final=True,
            start_ms=0,
            end_ms=5_000,
            confidence=0.94,
        )
    ]

    identify_mock = AsyncMock(return_value={"speaker_0": None})
    monkeypatch.setattr(recording_audio_processing.settings, "voice_identification_enabled", True)
    monkeypatch.setattr(
        recording_audio_processing.settings,
        "voice_identification_max_audio_seconds",
        3_600,
    )
    monkeypatch.setattr(
        recording_audio_processing.settings,
        "voice_identification_max_audio_bytes",
        30 * 1024 * 1024,
    )
    stt_payloads: list[bytes] = []

    async def capture_transcribe(media_path, **kwargs):
        stt_payloads.append(media_path.read_bytes())
        return FileTranscription(segments=transcript_results, words=[])

    transcribe = AsyncMock(side_effect=capture_transcribe)
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        transcribe,
    )

    def fail_ffprobe(*_args, **_kwargs):
        raise AssertionError("large non-WAV uploads should use client duration without ffprobe")

    monkeypatch.setattr(
        "app.core.recording_audio_processing._ffprobe_duration_seconds",
        fail_ffprobe,
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_title",
        AsyncMock(return_value="Long Recording"),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.identify_speakers_for_recording",
        identify_mock,
    )
    sentry_anomalies: list[dict[str, object]] = []

    def capture_anomaly(code: str, message: str, **kwargs: object) -> None:
        sentry_anomalies.append({"code": code, "message": message, **kwargs})

    monkeypatch.setattr(
        "app.core.recording_audio_processing.capture_sentry_anomaly",
        capture_anomaly,
    )

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=staged_path,
        content_type="audio/mp4",
        user_default_language="en",
        client_duration_seconds=9_236,
        staged_size_bytes=51_219_221,
    )

    transcribe.assert_awaited_once()
    assert stt_payloads == [b"audio"]  # original container streamed by path
    assert transcribe.await_args.kwargs["content_type"] == "audio/mp4"
    assert transcribe.await_args.kwargs["audio_duration_seconds"] == 9_236
    identify_mock.assert_awaited_once()
    assert identify_mock.await_args.kwargs["enabled"] is False
    segment = (
        await db_session.execute(select(Segment).where(Segment.recording_id == recording.id))
    ).scalar_one()
    assert segment.raw_label == "speaker_0"
    assert segment.person_id is None
    refreshed = await db_session.get(Recording, recording.id)
    assert refreshed is not None
    assert refreshed.status == RecordingStatus.READY.value
    assert refreshed.failure_code is None
    assert sentry_anomalies == []


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
        AsyncMock(return_value=FileTranscription(segments=transcript_results, words=[])),
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
async def test_process_staged_recording_upload_alerts_when_processing_is_slow(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="queued-processing-slow@example.com",
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

    staged_path = tmp_path / "slow-processing.wav"
    staged_path.write_bytes(b"audio")
    staged_size = staged_path.stat().st_size
    transcript_results = [
        TranscriptResult(
            text="Slow processing completed.",
            speaker="speaker_0",
            is_final=True,
            start_ms=0,
            end_ms=60_000,
            confidence=0.94,
        )
    ]
    tick = iter([0.0, 301.0])
    sentry_anomalies: list[dict[str, object]] = []
    sentry_breadcrumbs: list[dict[str, object]] = []

    monkeypatch.setattr(
        "app.core.recording_audio_processing.perf_counter",
        lambda: next(tick),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        AsyncMock(return_value=FileTranscription(segments=transcript_results, words=[])),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_title",
        AsyncMock(return_value="Slow Processing"),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.identify_speakers_for_recording",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.capture_sentry_anomaly",
        lambda alert_code, message, *, category, extras, level="warning": sentry_anomalies.append(
            {
                "alert_code": alert_code,
                "message": message,
                "category": category,
                "extras": extras,
                "level": level,
            }
        ),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.add_sentry_breadcrumb",
        lambda **kwargs: sentry_breadcrumbs.append(kwargs),
    )

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=staged_path,
        content_type="audio/wav",
        user_default_language="en",
        client_duration_seconds=60,
        staged_size_bytes=staged_size,
    )

    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.READY.value
    assert sentry_anomalies == [
        {
            "alert_code": "recording.processing.slow",
            "message": "Recording processing latency exceeded threshold",
            "category": "recording",
            "extras": {
                "recording_id": str(recording.id),
                "latency_ms": 301_000,
                "slow_threshold_ms": 300_000,
                "audio_duration_seconds": None,
                "client_duration_seconds": 60,
                "effective_duration_seconds": 60,
                "staged_size_bytes": staged_size,
                "segment_count": 1,
            },
            "level": "warning",
        }
    ]
    assert any(
        item.get("message") == "Recording processing completed"
        for item in sentry_breadcrumbs
    )
    assert "Slow processing completed" not in repr(sentry_anomalies)


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
async def test_process_staged_recording_upload_rejects_too_short_wav_before_provider(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="queued-too-short@example.com",
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

    staged_path = tmp_path / "too-short.wav"
    _write_wav(staged_path, frame_count=800)
    transcribe = AsyncMock()
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        transcribe,
    )

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=staged_path,
        content_type="audio/wav",
        user_default_language="en",
        staged_size_bytes=staged_path.stat().st_size,
    )

    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.FAILED.value
    assert recording.failure_code == "transcript_empty"
    assert recording.title == "No speech detected"
    assert recording.failure_message == "We could not detect clear speech in this recording."
    assert not staged_path.exists()
    transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_staged_recording_upload_rejects_too_short_m4a_before_provider(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="queued-too-short-m4a@example.com",
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

    staged_path = tmp_path / "too-short.m4a"
    staged_path.write_bytes(b"tiny-m4a")
    transcribe = AsyncMock(return_value=[
        TranscriptResult(
            text="Should not reach provider.",
            speaker="speaker_0",
            is_final=True,
            start_ms=0,
            end_ms=1000,
            confidence=0.9,
        )
    ])
    monkeypatch.setattr(
        "app.core.recording_audio_processing._ffprobe_duration_seconds",
        lambda *_args, **_kwargs: 0.05,
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        transcribe,
    )

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=staged_path,
        content_type="audio/mp4",
        user_default_language="en",
        staged_size_bytes=staged_path.stat().st_size,
    )

    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.FAILED.value
    assert recording.failure_code == "transcript_empty"
    assert recording.title == "No speech detected"
    assert recording.failure_message == "We could not detect clear speech in this recording."
    assert not staged_path.exists()
    transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_staged_recording_upload_continues_after_duration_probe_failure(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="queued-probe-failed@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title="Probe failed upload",
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=datetime.now(timezone.utc),
        language="en",
    )
    db_session.add(recording)
    await db_session.commit()

    staged_path = tmp_path / "probe-failed.m4a"
    staged_path.write_bytes(b"valid-provider-media")
    transcript_results = [
        TranscriptResult(
            text="Provider can still transcribe this audio.",
            speaker="speaker_0",
            is_final=True,
            start_ms=0,
            end_ms=2_000,
            confidence=0.9,
        )
    ]
    transcribe = AsyncMock(return_value=FileTranscription(segments=transcript_results, words=[]))
    capture = Mock()

    def _decode_failed(*_args, **_kwargs):
        raise recording_audio_processing.AudioDurationProbeError("probe failed")

    monkeypatch.setattr(
        "app.core.recording_audio_processing._ffprobe_duration_seconds",
        _decode_failed,
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        transcribe,
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing._extract_staged_media_audio",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.capture_sentry_anomaly",
        capture,
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
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
        content_type="audio/mp4",
        user_default_language="en",
        client_duration_seconds=42,
        staged_size_bytes=staged_path.stat().st_size,
    )

    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.READY.value
    assert recording.failure_code is None
    assert recording.failure_message is None
    assert recording.duration_seconds == 42
    assert not staged_path.exists()
    transcribe.assert_awaited_once()
    assert transcribe.await_args.kwargs["audio_duration_seconds"] == 42
    capture.assert_called_once()
    assert capture.call_args.args[:2] == (
        "recording.audio.duration_probe_failed",
        "Recording upload duration could not be probed before transcription",
    )


@pytest.mark.asyncio
async def test_process_staged_recording_upload_retries_after_previous_decode_failure(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="queued-previous-decode-failed@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title="Previous decode failure retry",
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=datetime.now(timezone.utc),
        language="en",
    )
    db_session.add(recording)
    await db_session.commit()

    staged_path = tmp_path / "probe-failed-retry.m4a"
    staged_path.write_bytes(b"valid-provider-media-again")
    transcript_results = [
        TranscriptResult(
            text="The retry reached transcription.",
            speaker="speaker_0",
            is_final=True,
            start_ms=0,
            end_ms=3_000,
            confidence=0.9,
        )
    ]
    transcribe = AsyncMock(return_value=FileTranscription(segments=transcript_results, words=[]))
    capture = Mock()

    def _decode_failed(*_args, **_kwargs):
        raise recording_audio_processing.AudioDurationProbeError("probe failed again")

    monkeypatch.setattr(
        "app.core.recording_audio_processing._ffprobe_duration_seconds",
        _decode_failed,
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        transcribe,
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing._extract_staged_media_audio",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.capture_sentry_anomaly",
        capture,
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
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
        content_type="audio/mp4",
        user_default_language="en",
        client_duration_seconds=44,
        staged_size_bytes=staged_path.stat().st_size,
        previous_failure_code="audio_decode_failed",
    )

    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.READY.value
    assert recording.failure_code is None
    assert recording.failure_message is None
    assert recording.duration_seconds == 44
    assert not staged_path.exists()
    transcribe.assert_awaited_once()
    assert transcribe.await_args.kwargs["audio_duration_seconds"] == 44
    capture.assert_called_once()
    assert capture.call_args.args[:2] == (
        "recording.audio.duration_probe_failed",
        "Recording upload duration could not be probed before transcription",
    )


@pytest.mark.asyncio
async def test_process_staged_recording_upload_allows_provider_minimum_wav(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="queued-provider-minimum@example.com",
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

    staged_path = tmp_path / "minimum-provider-duration.wav"
    _write_wav(staged_path, frame_count=1600)
    transcribe = AsyncMock(
        return_value=FileTranscription(
            segments=[
                TranscriptResult(
                    text="Minimum audio accepted.",
                    speaker="speaker_0",
                    is_final=True,
                    start_ms=0,
                    end_ms=100,
                    confidence=0.9,
                )
            ],
            words=[],
        )
    )
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
        AsyncMock(return_value="Minimum Recording"),
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
        staged_size_bytes=staged_path.stat().st_size,
    )

    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.READY.value
    assert recording.title == "Minimum Recording"
    assert recording.duration_seconds == 1
    assert not staged_path.exists()
    transcribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_staged_recording_upload_maps_provider_audio_too_short_to_no_speech(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="queued-provider-too-short@example.com",
        password_hash="x",
        default_language="ru",
    )
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title=None,
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=datetime.now(timezone.utc),
        language="multi",
    )
    db_session.add(recording)
    await db_session.commit()

    staged_path = tmp_path / "provider-too-short.webm"
    staged_path.write_bytes(b"short-webm")
    error = httpx.HTTPStatusError(
        "Client error '400 Bad Request'",
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
        response=httpx.Response(
            400,
            json={"detail": {"status": "audio_too_short"}},
            request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
        ),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        AsyncMock(side_effect=error),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing._ffprobe_duration_seconds",
        lambda *_args, **_kwargs: 0.5,
    )

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=staged_path,
        content_type="audio/webm",
        user_default_language="ru",
        staged_size_bytes=staged_path.stat().st_size,
    )

    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.FAILED.value
    assert recording.failure_code == "transcript_empty"
    assert recording.title == "Без речи"
    assert recording.failure_message == "Мы не обнаружили разборчивой речи в этой записи."
    assert not staged_path.exists()


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
        AsyncMock(return_value=FileTranscription(segments=transcript_results, words=[])),
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


def _write_wav(path, *, frame_count: int, sample_rate: int = 16_000) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\0\0" * frame_count)


@pytest.mark.asyncio
async def test_process_staged_recording_upload_pins_detected_language(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="detected-language@example.com",
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
        language="multi",
    )
    db_session.add(recording)
    await db_session.commit()

    staged_path = tmp_path / "recording.wav"
    staged_path.write_bytes(b"audio")
    transcribe = AsyncMock(
        return_value=FileTranscription(
            segments=[
                TranscriptResult(
                    text="Привет из распознавания.",
                    speaker="speaker_0",
                    is_final=True,
                    start_ms=0,
                    end_ms=1500,
                    confidence=0.95,
                )
            ],
            words=[],
            detected_language="rus",
            language_probability=0.99,
        )
    )
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
        AsyncMock(return_value="Русская встреча"),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.identify_speakers_for_recording",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.extract_speaker_names",
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
    assert recording.status == RecordingStatus.READY.value
    assert recording.language == "ru"


@pytest.mark.asyncio
async def test_process_staged_recording_upload_keeps_user_pinned_language(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="pinned-language@example.com",
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
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        AsyncMock(
            return_value=FileTranscription(
                segments=[
                    TranscriptResult(
                        text="Hello.",
                        speaker="speaker_0",
                        is_final=True,
                        start_ms=0,
                        end_ms=900,
                        confidence=0.95,
                    )
                ],
                words=[],
                detected_language="rus",
                language_probability=0.99,
            )
        ),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_title",
        AsyncMock(return_value="Pinned"),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.identify_speakers_for_recording",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.extract_speaker_names",
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
    assert recording.language == "en"


@pytest.mark.asyncio
async def test_process_staged_recording_upload_attributes_owner_from_sidecar(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.person import Person

    user = User(
        email="sidecar-owner@example.com",
        password_hash="x",
        default_language="en",
        first_name="Mik",
    )
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title=None,
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=datetime.now(timezone.utc),
        language="multi",
        capture_metadata={
            "version": 1,
            "capture": "dual_mono_mix",
            "local_speech_ms": [[0, 4000], [9000, 12000]],
            "aec": False,
        },
    )
    db_session.add(recording)
    await db_session.commit()

    staged_path = tmp_path / "recording.wav"
    staged_path.write_bytes(b"audio")
    transcript_results = [
        TranscriptResult(
            text="Я расскажу про план.",
            speaker="speaker_0",
            is_final=True,
            start_ms=0,
            end_ms=4000,
            confidence=0.95,
        ),
        TranscriptResult(
            text="Отлично, слушаю.",
            speaker="speaker_1",
            is_final=True,
            start_ms=4200,
            end_ms=8800,
            confidence=0.94,
        ),
        TranscriptResult(
            text="Вот детали.",
            speaker="speaker_0",
            is_final=True,
            start_ms=9000,
            end_ms=12000,
            confidence=0.96,
        ),
    ]

    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        AsyncMock(
            return_value=FileTranscription(segments=transcript_results, words=[])
        ),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_title",
        AsyncMock(return_value="Sidecar Meeting"),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.identify_speakers_for_recording",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.extract_speaker_names",
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

    await db_session.refresh(user)
    assert user.self_person_id is not None
    self_person = (
        await db_session.execute(select(Person).where(Person.id == user.self_person_id))
    ).scalar_one()
    assert self_person.display_name == "Mik"

    segments = (
        (
            await db_session.execute(
                select(Segment)
                .where(Segment.recording_id == recording.id)
                .order_by(Segment.start_ms)
            )
        )
        .scalars()
        .all()
    )
    assert [seg.raw_label for seg in segments] == ["speaker_0", "speaker_1", "speaker_0"]
    assert segments[0].person_id == user.self_person_id
    assert segments[2].person_id == user.self_person_id
    assert segments[1].person_id is None
    assert segments[0].match_confidence == 1.0


@pytest.mark.asyncio
async def test_process_staged_recording_upload_sidecar_owner_overrides_voiceprint_conflict(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="sidecar-owner-conflict@example.com",
        password_hash="x",
        default_language="en",
        first_name="Mik",
    )
    db_session.add(user)
    await db_session.flush()
    other_person = Person(user_id=user.id, display_name="Other")
    db_session.add(other_person)
    recording = Recording(
        user_id=user.id,
        title=None,
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=datetime.now(timezone.utc),
        language="multi",
        capture_metadata={
            "version": 1,
            "capture": "dual_mono_mix",
            "local_speech_ms": [[0, 4000], [9000, 12000]],
            "aec": False,
        },
    )
    db_session.add(recording)
    await db_session.commit()

    staged_path = tmp_path / "recording.wav"
    staged_path.write_bytes(b"audio")
    transcript_results = [
        TranscriptResult(
            text="Я расскажу про план.",
            speaker="speaker_0",
            is_final=True,
            start_ms=0,
            end_ms=4000,
            confidence=0.95,
        ),
        TranscriptResult(
            text="Отлично, слушаю.",
            speaker="speaker_1",
            is_final=True,
            start_ms=4200,
            end_ms=8800,
            confidence=0.94,
        ),
        TranscriptResult(
            text="Вот детали.",
            speaker="speaker_0",
            is_final=True,
            start_ms=9000,
            end_ms=12000,
            confidence=0.96,
        ),
    ]

    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        AsyncMock(return_value=FileTranscription(segments=transcript_results, words=[])),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_title",
        AsyncMock(return_value="Sidecar Meeting"),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.identify_speakers_for_recording",
        AsyncMock(return_value={"speaker_0": (other_person.id, 0.8)}),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.extract_speaker_names",
        AsyncMock(return_value={}),
    )
    capture = MagicMock()
    monkeypatch.setattr(
        "app.core.recording_audio_processing.capture_sentry_anomaly",
        capture,
    )

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=staged_path,
        content_type="audio/wav",
        user_default_language="en",
    )

    await db_session.refresh(user)
    segments = (
        (
            await db_session.execute(
                select(Segment)
                .where(Segment.recording_id == recording.id)
                .order_by(Segment.start_ms)
            )
        )
        .scalars()
        .all()
    )
    assert "recording.owner_attribution.conflict" in [
        call.args[0] for call in capture.call_args_list
    ]
    assert segments[0].person_id == user.self_person_id
    assert segments[2].person_id == user.self_person_id
    assert segments[0].match_confidence == 1.0
    assert segments[2].match_confidence == 1.0


@pytest.mark.asyncio
async def test_process_staged_recording_upload_degrades_when_sidecar_owner_resolution_fails(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="sidecar-owner-degraded@example.com",
        password_hash="x",
        default_language="en",
        first_name="Mik",
    )
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title=None,
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=datetime.now(timezone.utc),
        language="multi",
        capture_metadata={
            "version": 1,
            "capture": "dual_mono_mix",
            "local_speech_ms": [[0, 4000]],
            "aec": False,
        },
    )
    db_session.add(recording)
    await db_session.commit()

    staged_path = tmp_path / "recording.wav"
    staged_path.write_bytes(b"audio")
    transcript_results = [
        TranscriptResult(
            text="Я расскажу про план.",
            speaker="speaker_0",
            is_final=True,
            start_ms=0,
            end_ms=4000,
            confidence=0.95,
        )
    ]

    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        AsyncMock(return_value=FileTranscription(segments=transcript_results, words=[])),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_title",
        AsyncMock(return_value="Sidecar Meeting"),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.identify_speakers_for_recording",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.extract_speaker_names",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.resolve_owner_raw_label",
        Mock(side_effect=RuntimeError("boom")),
    )
    capture = MagicMock()
    monkeypatch.setattr(
        "app.core.recording_audio_processing.capture_sentry_anomaly",
        capture,
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
    assert recording.status == RecordingStatus.READY.value
    assert "recording.owner_attribution.degraded" in [
        call.args[0] for call in capture.call_args_list
    ]


@pytest.mark.asyncio
async def test_process_staged_recording_survives_voice_id_and_name_extraction_failures(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="degraded-attribution@example.com",
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
    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        AsyncMock(
            return_value=FileTranscription(
                segments=[
                    TranscriptResult(
                        text="Speakers stay unassigned but the transcript survives.",
                        speaker="speaker_0",
                        is_final=True,
                        start_ms=0,
                        end_ms=2500,
                        confidence=0.9,
                    ),
                    TranscriptResult(
                        text="Second cluster keeps flowing.",
                        speaker="speaker_1",
                        is_final=True,
                        start_ms=2600,
                        end_ms=5000,
                        confidence=0.9,
                    ),
                ],
                words=[],
            )
        ),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_title",
        AsyncMock(return_value="Degraded Attribution"),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.identify_speakers_for_recording",
        AsyncMock(side_effect=RuntimeError("voice id offline")),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.extract_speaker_names",
        AsyncMock(side_effect=RuntimeError("llm offline")),
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
        (
            await db_session.execute(
                select(Segment).where(Segment.recording_id == recording.id)
            )
        )
        .scalars()
        .all()
    )
    assert recording.status == RecordingStatus.READY.value
    assert len(segments) == 2
    assert all(segment.person_id is None for segment in segments)


@pytest.mark.asyncio
async def test_segment_embedding_batch_failure_counts_all_segments() -> None:
    from app.core.recording_audio_processing import _embed_recording_segments

    recording_id = uuid4()
    recording = Recording(
        id=recording_id,
        user_id=uuid4(),
        title="Batch",
        type="meeting",
        status=RecordingStatus.READY.value,
    )
    segments = [
        Segment(
            recording_id=recording_id,
            speaker="speaker_0",
            content=f"segment {index}",
            start_ms=index * 1000,
            end_ms=index * 1000 + 900,
            confidence=0.9,
        )
        for index in range(3)
    ]

    with patch(
        "app.core.recording_audio_processing.generate_embeddings",
        AsyncMock(side_effect=RuntimeError("embedding offline")),
    ):
        failed = await _embed_recording_segments(
            recording=recording,
            segments=segments,
            user_id=recording.user_id,
            recording_id=recording_id,
        )

    assert failed == 3
    assert all(segment.embedding is None for segment in segments)


@pytest.mark.asyncio
async def test_process_staged_video_unpacks_extraction_and_probes_duration(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        email="video-extract@example.com",
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

    staged_path = tmp_path / "meeting.mp4"
    staged_path.write_bytes(b"fake-video")
    extracted_path = tmp_path / "meeting.flac"
    extracted_path.write_bytes(b"fake-flac")

    monkeypatch.setattr(
        "app.core.recording_audio_processing._extract_staged_media_audio",
        AsyncMock(return_value=(extracted_path, "audio/flac", 9)),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing._ffprobe_duration_seconds",
        lambda path: 42.0,
    )
    captured: dict[str, object] = {}

    async def fake_transcribe(path, **kwargs):
        captured["content_type"] = kwargs["content_type"]
        captured["duration"] = kwargs["audio_duration_seconds"]
        return FileTranscription(
            segments=[
                TranscriptResult(
                    text="Video audio extracted.",
                    speaker="speaker_0",
                    is_final=True,
                    start_ms=0,
                    end_ms=1500,
                    confidence=0.9,
                )
            ],
            words=[],
        )

    monkeypatch.setattr(
        "app.core.recording_audio_processing.transcribe_audio_file",
        fake_transcribe,
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_embedding",
        AsyncMock(return_value=[0.1] * 1536),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.generate_title",
        AsyncMock(return_value="Video Meeting"),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.identify_speakers_for_recording",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.core.recording_audio_processing.extract_speaker_names",
        AsyncMock(return_value={}),
    )

    await process_staged_recording_upload(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        staged_path=staged_path,
        content_type="video/mp4",
        user_default_language="en",
    )

    await db_session.refresh(recording)
    assert recording.status == RecordingStatus.READY.value
    # The compact FLAC (not the source container) reaches the provider, and the
    # duration comes from the post-extraction probe.
    assert captured["content_type"] == "audio/flac"
    assert captured["duration"] == 42.0
