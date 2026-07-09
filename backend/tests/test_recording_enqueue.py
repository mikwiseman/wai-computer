"""The summary-generation enqueue wrapper sends the real Celery task."""

from uuid import uuid4


def test_enqueue_recording_summary_generation_sends_celery_task(monkeypatch) -> None:
    from app.core.recording_audio_processing import (
        _enqueue_recording_summary_generation,
    )

    sent: dict[str, object] = {}

    class _Result:
        id = "task-123"

    def fake_send_task(name, kwargs=None, **_extra):
        sent["name"] = name
        sent["kwargs"] = kwargs
        return _Result()

    monkeypatch.setattr(
        "app.tasks.celery_app.celery_app.send_task",
        fake_send_task,
    )

    job_id = uuid4()
    task_id = _enqueue_recording_summary_generation(job_id)

    assert task_id == "task-123"
    assert sent["name"] == "app.tasks.summary_generation.generate_recording_summary"
    assert sent["kwargs"] == {"job_id": str(job_id)}
