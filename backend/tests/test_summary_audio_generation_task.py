"""Summary-audio Celery task orchestration tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

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
