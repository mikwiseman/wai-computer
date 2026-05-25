"""Focused tests for Celery task wrappers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

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
