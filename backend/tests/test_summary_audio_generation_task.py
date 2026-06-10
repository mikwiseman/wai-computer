"""Summary-audio Celery task orchestration tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from billiard.exceptions import SoftTimeLimitExceeded

from app.core.summary_audio import SummaryAudioError
from app.core.xai_tts import XaiTTSError

pytestmark = pytest.mark.asyncio


class _FakeDbContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


async def test_generate_summary_audio_task_orchestrates_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import summary_audio_generation as task

    artifact_id = uuid4()
    calls: list[str] = []

    monkeypatch.setattr(task, "get_db_context", lambda: _FakeDbContext())

    async def fake_prepare(db, *, artifact_id, task_id):
        calls.append(f"prepare:{task_id}")
        return {"artifact_id": artifact_id}

    async def fake_generate(payload):
        calls.append("generate")
        return {"audio": b"ID3"}

    async def fake_persist(db, *, artifact_id, result):
        calls.append(f"persist:{artifact_id}:{result['audio']!r}")

    monkeypatch.setattr(task, "prepare_summary_audio_generation_payload", fake_prepare)
    monkeypatch.setattr(task, "generate_summary_audio_for_payload", fake_generate)
    monkeypatch.setattr(task, "persist_summary_audio_generation_result", fake_persist)

    await task._generate_summary_audio(artifact_id=str(artifact_id), task_id="task-1")

    assert calls == [
        "prepare:task-1",
        "generate",
        f"persist:{artifact_id}:b'ID3'",
    ]


async def test_generate_summary_audio_task_marks_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import summary_audio_generation as task

    artifact_id = uuid4()
    failed: dict[str, str] = {}
    monkeypatch.setattr(task, "get_db_context", lambda: _FakeDbContext())
    monkeypatch.setattr(
        task,
        "prepare_summary_audio_generation_payload",
        lambda db, *, artifact_id, task_id: _async_return({"artifact_id": artifact_id}),
    )

    async def fake_generate(payload):
        raise XaiTTSError(code="xai_timeout", message="Timed out.")

    async def fake_fail(db, *, artifact_id, error_code, error_message):
        failed["artifact_id"] = str(artifact_id)
        failed["error_code"] = error_code
        failed["error_message"] = error_message

    monkeypatch.setattr(task, "generate_summary_audio_for_payload", fake_generate)
    monkeypatch.setattr(task, "fail_summary_audio_generation_job", fake_fail)

    with pytest.raises(XaiTTSError):
        await task._generate_summary_audio(artifact_id=str(artifact_id), task_id="task-1")

    assert failed == {
        "artifact_id": str(artifact_id),
        "error_code": "xai_timeout",
        "error_message": "Timed out.",
    }


async def _async_return(value):
    return value


async def test_generate_summary_audio_task_skips_when_payload_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import summary_audio_generation as task

    artifact_id = uuid4()
    generated: list[object] = []
    monkeypatch.setattr(task, "get_db_context", lambda: _FakeDbContext())

    async def fake_prepare(db, *, artifact_id, task_id):
        return None

    async def fake_generate(payload):
        generated.append(payload)
        return {"audio": b"ID3"}

    monkeypatch.setattr(task, "prepare_summary_audio_generation_payload", fake_prepare)
    monkeypatch.setattr(task, "generate_summary_audio_for_payload", fake_generate)

    await task._generate_summary_audio(artifact_id=str(artifact_id), task_id=None)

    assert generated == []


async def test_generate_summary_audio_task_marks_summary_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import summary_audio_generation as task

    artifact_id = uuid4()
    failed: dict[str, str] = {}
    monkeypatch.setattr(task, "get_db_context", lambda: _FakeDbContext())
    monkeypatch.setattr(
        task,
        "prepare_summary_audio_generation_payload",
        lambda db, *, artifact_id, task_id: _async_return({"artifact_id": artifact_id}),
    )

    async def fake_generate(payload):
        raise SummaryAudioError(code="summary_audio_empty", message="No summary text.")

    async def fake_fail(db, *, artifact_id, error_code, error_message):
        failed["artifact_id"] = str(artifact_id)
        failed["error_code"] = error_code
        failed["error_message"] = error_message

    monkeypatch.setattr(task, "generate_summary_audio_for_payload", fake_generate)
    monkeypatch.setattr(task, "fail_summary_audio_generation_job", fake_fail)

    with pytest.raises(SummaryAudioError):
        await task._generate_summary_audio(artifact_id=str(artifact_id), task_id="task-2")

    assert failed == {
        "artifact_id": str(artifact_id),
        "error_code": "summary_audio_empty",
        "error_message": "No summary text.",
    }


async def test_generate_summary_audio_task_masks_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import summary_audio_generation as task

    artifact_id = uuid4()
    failed: dict[str, str] = {}
    captured: list[Exception] = []
    monkeypatch.setattr(task, "get_db_context", lambda: _FakeDbContext())
    monkeypatch.setattr(
        task,
        "prepare_summary_audio_generation_payload",
        lambda db, *, artifact_id, task_id: _async_return({"artifact_id": artifact_id}),
    )
    monkeypatch.setattr(task, "capture_sentry_exception", lambda exc: captured.append(exc))

    async def fake_generate(payload):
        raise RuntimeError("disk full")

    async def fake_fail(db, *, artifact_id, error_code, error_message):
        failed["artifact_id"] = str(artifact_id)
        failed["error_code"] = error_code
        failed["error_message"] = error_message

    monkeypatch.setattr(task, "generate_summary_audio_for_payload", fake_generate)
    monkeypatch.setattr(task, "fail_summary_audio_generation_job", fake_fail)

    with pytest.raises(RuntimeError, match="disk full"):
        await task._generate_summary_audio(artifact_id=str(artifact_id), task_id="task-3")

    assert len(captured) == 1
    assert failed == {
        "artifact_id": str(artifact_id),
        "error_code": "summary_audio_generation_failed",
        "error_message": "We couldn't create summary audio right now. Please try again.",
    }


async def test_mark_summary_audio_timeout_records_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import summary_audio_generation as task

    artifact_id = uuid4()
    failed: dict[str, str] = {}
    monkeypatch.setattr(task, "get_db_context", lambda: _FakeDbContext())

    async def fake_fail(db, *, artifact_id, error_code, error_message):
        failed["artifact_id"] = str(artifact_id)
        failed["error_code"] = error_code
        failed["error_message"] = error_message

    monkeypatch.setattr(task, "fail_summary_audio_generation_job", fake_fail)

    await task._mark_summary_audio_timeout(artifact_id=str(artifact_id))

    assert failed == {
        "artifact_id": str(artifact_id),
        "error_code": "summary_audio_timeout",
        "error_message": "Summary audio generation timed out.",
    }


# --- Celery wrapper tests -------------------------------------------------
#
# The wrapper only runs via ``.delay`` in production, so it is exercised
# directly here. ``asyncio.run`` is replaced (the established pattern from
# test_agent_tasks.py) because the wrapper cannot start a nested loop inside
# pytest-asyncio; the fake consumes the inner coroutine, whose body is covered
# by the direct tests above.


async def test_generate_summary_audio_celery_wrapper_runs_inner_coroutine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import summary_audio_generation as task

    consumed: list[str] = []

    def fake_asyncio_run(coro):
        consumed.append(coro.__qualname__)
        coro.close()
        return None

    monkeypatch.setattr(task.asyncio, "run", fake_asyncio_run)

    task.generate_summary_audio(artifact_id="artifact-1")

    assert consumed == ["_generate_summary_audio"]


async def test_generate_summary_audio_celery_wrapper_marks_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import summary_audio_generation as task

    consumed: list[str] = []
    anomalies: list[tuple[str, dict]] = []

    def fake_asyncio_run(coro):
        consumed.append(coro.__qualname__)
        coro.close()
        if len(consumed) == 1:
            raise SoftTimeLimitExceeded()
        return None

    def fake_anomaly(alert_code, message, *, category, extras=None, level="warning"):
        anomalies.append((alert_code, extras or {}))

    monkeypatch.setattr(task.asyncio, "run", fake_asyncio_run)
    monkeypatch.setattr(task, "capture_sentry_anomaly", fake_anomaly)

    with pytest.raises(SoftTimeLimitExceeded):
        task.generate_summary_audio(artifact_id="artifact-2")

    assert consumed == ["_generate_summary_audio", "_mark_summary_audio_timeout"]
    assert anomalies == [
        (
            "summary_audio.generation.timeout",
            {"artifact_id": "artifact-2", "task_id": None},
        )
    ]


async def test_generate_summary_audio_celery_wrapper_logs_and_reraises_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import summary_audio_generation as task

    def fake_asyncio_run(coro):
        coro.close()
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(task.asyncio, "run", fake_asyncio_run)

    with pytest.raises(RuntimeError, match="provider exploded"):
        task.generate_summary_audio(artifact_id="artifact-3")
