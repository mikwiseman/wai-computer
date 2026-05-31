"""Focused tests for Celery task wrappers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from billiard.exceptions import SoftTimeLimitExceeded

from app.tasks import embedding_backfill as embedding_task_module
from app.tasks import recording_audio_processing as recording_task_module
from app.tasks.retry_policy import is_retryable_exception as task_is_retryable_exception


def test_recording_processing_task_runs_core(monkeypatch: pytest.MonkeyPatch) -> None:
    run_core = AsyncMock()
    monkeypatch.setattr(
        recording_task_module,
        "_process_staged_recording_upload",
        run_core,
    )

    recording_task_module.process_staged_recording_upload.run(
        recording_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        staged_path="/tmp/recording.wav",
        content_type="audio/wav",
        user_default_language="en",
        client_duration_seconds=30,
        client_file_size_bytes=100,
        staged_size_bytes=100,
    )

    run_core.assert_awaited_once()


def test_recording_processing_task_retries_retryable_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recording_task_module,
        "_process_staged_recording_upload",
        AsyncMock(side_effect=httpx.TimeoutException("provider timeout")),
    )

    def fake_retry(*, exc):
        raise RuntimeError(f"retry requested: {type(exc).__name__}")

    monkeypatch.setattr(recording_task_module.process_staged_recording_upload, "retry", fake_retry)

    with pytest.raises(RuntimeError, match="retry requested: TimeoutException"):
        recording_task_module.process_staged_recording_upload.run(
            recording_id="00000000-0000-0000-0000-000000000003",
            user_id="00000000-0000-0000-0000-000000000004",
            staged_path="/tmp/recording.wav",
            content_type="audio/wav",
            user_default_language="en",
        )


def test_recording_processing_task_marks_timeout_before_reraising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recording_task_module,
        "_process_staged_recording_upload",
        AsyncMock(side_effect=SoftTimeLimitExceeded()),
    )
    mark_timeout = AsyncMock()
    monkeypatch.setattr(recording_task_module, "_mark_processing_timeout", mark_timeout)

    with pytest.raises(SoftTimeLimitExceeded):
        recording_task_module.process_staged_recording_upload.run(
            recording_id="00000000-0000-0000-0000-000000000005",
            user_id="00000000-0000-0000-0000-000000000006",
            staged_path="/tmp/recording.wav",
            content_type="audio/wav",
            user_default_language="en",
        )

    mark_timeout.assert_awaited_once_with(
        recording_id="00000000-0000-0000-0000-000000000005"
    )


def test_recording_processing_task_alerts_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recording_task_module,
        "_process_staged_recording_upload",
        AsyncMock(side_effect=SoftTimeLimitExceeded()),
    )
    monkeypatch.setattr(
        recording_task_module,
        "_mark_processing_timeout",
        AsyncMock(),
    )
    sentry_anomalies: list[dict[str, object]] = []
    monkeypatch.setattr(
        recording_task_module,
        "capture_sentry_anomaly",
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

    with pytest.raises(SoftTimeLimitExceeded):
        recording_task_module.process_staged_recording_upload.run(
            recording_id="00000000-0000-0000-0000-000000000005",
            user_id="00000000-0000-0000-0000-000000000006",
            staged_path="/tmp/alice-private.wav",
            content_type="audio/wav",
            user_default_language="en",
        )

    assert sentry_anomalies == [
        {
            "alert_code": "recording.processing.timeout",
            "message": "Recording processing task timed out",
            "category": "recording",
            "extras": {
                "recording_id": "00000000-0000-0000-0000-000000000005",
                "task_id": None,
                "retries": 0,
                "content_type": "audio/wav",
            },
            "level": "error",
        }
    ]
    assert "alice-private.wav" not in repr(sentry_anomalies)


def test_recording_processing_task_marks_failed_after_retry_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recording_task_module,
        "_process_staged_recording_upload",
        AsyncMock(side_effect=httpx.TimeoutException("provider timeout")),
    )
    mark_failed = AsyncMock()
    deleted_paths: list[Path] = []
    monkeypatch.setattr(
        recording_task_module,
        "_mark_processing_failed_after_retries",
        mark_failed,
    )
    monkeypatch.setattr(recording_task_module, "delete_staged_file", deleted_paths.append)

    task = recording_task_module.process_staged_recording_upload
    previous_retries = task.request.retries
    task.request.retries = task.max_retries
    try:
        with pytest.raises(httpx.TimeoutException):
            task.run(
                recording_id="00000000-0000-0000-0000-000000000007",
                user_id="00000000-0000-0000-0000-000000000008",
                staged_path="/tmp/recording.wav",
                content_type="audio/wav",
                user_default_language="en",
            )
    finally:
        task.request.retries = previous_retries

    mark_failed.assert_awaited_once_with(
        recording_id="00000000-0000-0000-0000-000000000007"
    )
    assert deleted_paths == [Path("/tmp/recording.wav")]


def test_recording_processing_task_alerts_on_retry_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recording_task_module,
        "_process_staged_recording_upload",
        AsyncMock(side_effect=httpx.TimeoutException("provider timeout")),
    )
    monkeypatch.setattr(
        recording_task_module,
        "_mark_processing_failed_after_retries",
        AsyncMock(),
    )
    monkeypatch.setattr(recording_task_module, "delete_staged_file", lambda _path: None)
    sentry_anomalies: list[dict[str, object]] = []
    monkeypatch.setattr(
        recording_task_module,
        "capture_sentry_anomaly",
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

    task = recording_task_module.process_staged_recording_upload
    previous_retries = task.request.retries
    task.request.retries = task.max_retries
    try:
        with pytest.raises(httpx.TimeoutException):
            task.run(
                recording_id="00000000-0000-0000-0000-000000000007",
                user_id="00000000-0000-0000-0000-000000000008",
                staged_path="/tmp/private-meeting.wav",
                content_type="audio/wav",
                user_default_language="en",
            )
    finally:
        task.request.retries = previous_retries

    assert sentry_anomalies == [
        {
            "alert_code": "recording.processing.retry_exhausted",
            "message": "Recording processing retries exhausted",
            "category": "recording",
            "extras": {
                "recording_id": "00000000-0000-0000-0000-000000000007",
                "task_id": None,
                "retries": task.max_retries,
                "error_type": "TimeoutException",
                "error_fingerprint": recording_task_module.fingerprint_text("provider timeout"),
                "content_type": "audio/wav",
            },
            "level": "error",
        }
    ]
    assert "private-meeting.wav" not in repr(sentry_anomalies)


@pytest.mark.asyncio
async def test_recording_processing_async_wrappers_use_db_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = object()

    class SessionContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    process_core = AsyncMock()
    mark_failed = AsyncMock()
    monkeypatch.setattr(recording_task_module, "get_db_context", lambda: SessionContext())
    monkeypatch.setattr(
        recording_task_module,
        "process_staged_recording_upload_core",
        process_core,
    )
    monkeypatch.setattr(
        recording_task_module,
        "mark_recording_processing_failed",
        mark_failed,
    )

    await recording_task_module._process_staged_recording_upload(
        recording_id="00000000-0000-0000-0000-000000000009",
        user_id="00000000-0000-0000-0000-000000000010",
        staged_path="/tmp/recording.wav",
        content_type="audio/wav",
        user_default_language="ru",
        client_duration_seconds=30,
        client_file_size_bytes=100,
        staged_size_bytes=90,
    )
    await recording_task_module._mark_processing_timeout(
        recording_id="00000000-0000-0000-0000-000000000009"
    )
    await recording_task_module._mark_processing_failed_after_retries(
        recording_id="00000000-0000-0000-0000-000000000009"
    )

    process_core.assert_awaited_once_with(
        db,
        recording_id=UUID("00000000-0000-0000-0000-000000000009"),
        user_id=UUID("00000000-0000-0000-0000-000000000010"),
        staged_path=Path("/tmp/recording.wav"),
        content_type="audio/wav",
        user_default_language="ru",
        client_duration_seconds=30,
        client_file_size_bytes=100,
        staged_size_bytes=90,
    )
    assert mark_failed.await_count == 2


def test_embedding_backfill_task_runs_core(monkeypatch: pytest.MonkeyPatch) -> None:
    run_core = AsyncMock(
        return_value={
            "scanned": 1,
            "filled": 1,
            "failed": 0,
            "remaining": 0,
            "batches": 1,
            "isolated_failures": 0,
        }
    )
    monkeypatch.setattr(
        embedding_task_module,
        "_backfill_missing_segment_embeddings",
        run_core,
    )

    result = embedding_task_module.backfill_missing_segment_embeddings.run(
        user_id=None,
        batch_size=10,
        limit=10,
    )

    assert result["filled"] == 1
    run_core.assert_awaited_once_with(user_id=None, batch_size=10, limit=10)


@pytest.mark.asyncio
async def test_embedding_backfill_async_wrapper_uses_db_context_and_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = object()

    class SessionContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    backfill_core = AsyncMock(
        return_value=SimpleNamespace(as_dict=lambda: {"scanned": 3, "filled": 2})
    )
    monkeypatch.setattr(embedding_task_module, "get_db_context", lambda: SessionContext())
    monkeypatch.setattr(
        embedding_task_module,
        "get_settings",
        lambda: SimpleNamespace(
            embedding_backfill_batch_size=12,
            embedding_backfill_max_segments_per_run=34,
        ),
    )
    monkeypatch.setattr(embedding_task_module, "backfill_core", backfill_core)

    result = await embedding_task_module._backfill_missing_segment_embeddings(
        user_id="00000000-0000-0000-0000-000000000011"
    )

    assert result == {"scanned": 3, "filled": 2}
    backfill_core.assert_awaited_once_with(
        db,
        user_id=UUID("00000000-0000-0000-0000-000000000011"),
        batch_size=12,
        limit=34,
    )


def test_embedding_backfill_task_retries_retryable_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        embedding_task_module,
        "_backfill_missing_segment_embeddings",
        AsyncMock(side_effect=httpx.TimeoutException("provider timeout")),
    )

    def fake_retry(*, exc):
        raise RuntimeError(f"retry requested: {type(exc).__name__}")

    monkeypatch.setattr(
        embedding_task_module.backfill_missing_segment_embeddings,
        "retry",
        fake_retry,
    )

    with pytest.raises(RuntimeError, match="retry requested: TimeoutException"):
        embedding_task_module.backfill_missing_segment_embeddings.run()


def test_task_retry_policy_reexport_matches_core_policy() -> None:
    assert task_is_retryable_exception(httpx.TimeoutException("timeout"))
