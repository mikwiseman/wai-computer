from types import SimpleNamespace

from app.db import session as session_module
from app.tasks import celery_app as celery_app_module


class DummyEngine:
    def __init__(self, label: int):
        self.label = label
        self.sync_engine = self
        self.dispose_calls = 0

    def dispose(self) -> None:
        self.dispose_calls += 1


class DummySessionFactory:
    def __init__(self, engine: DummyEngine):
        self.engine = engine

    def __call__(self, *args, **kwargs):
        return {"engine_label": self.engine.label, "args": args, "kwargs": kwargs}


def test_reset_db_runtime_recreates_engine(monkeypatch):
    counter = {"value": 0}

    def fake_create_engine():
        counter["value"] += 1
        return DummyEngine(counter["value"])

    def fake_sessionmaker(engine, **_kwargs):
        return DummySessionFactory(engine)

    monkeypatch.setattr(session_module, "_create_engine", fake_create_engine)
    monkeypatch.setattr(session_module, "async_sessionmaker", fake_sessionmaker)
    monkeypatch.setattr(session_module, "_engine", None)
    monkeypatch.setattr(session_module, "_session_maker", None)
    monkeypatch.setattr(session_module, "_runtime_pid", None)
    monkeypatch.setattr(session_module.os, "getpid", lambda: 101)

    session_module.reset_db_runtime()
    first_engine = session_module._engine

    session_module.reset_db_runtime()
    second_engine = session_module._engine

    assert first_engine.label == 1
    assert first_engine.dispose_calls == 1
    assert second_engine.label == 2
    assert session_module._runtime_pid == 101


def test_async_session_maker_proxy_refreshes_after_pid_change(monkeypatch):
    counter = {"value": 0}

    def fake_create_engine():
        counter["value"] += 1
        return DummyEngine(counter["value"])

    def fake_sessionmaker(engine, **_kwargs):
        return DummySessionFactory(engine)

    pid = {"value": 201}

    monkeypatch.setattr(session_module, "_create_engine", fake_create_engine)
    monkeypatch.setattr(session_module, "async_sessionmaker", fake_sessionmaker)
    monkeypatch.setattr(session_module, "_engine", None)
    monkeypatch.setattr(session_module, "_session_maker", None)
    monkeypatch.setattr(session_module, "_runtime_pid", None)
    monkeypatch.setattr(session_module.os, "getpid", lambda: pid["value"])

    first_session = session_module.async_session_maker()
    pid["value"] = 202
    second_session = session_module.async_session_maker()

    assert first_session["engine_label"] == 1
    assert second_session["engine_label"] == 2


def test_async_session_maker_proxy_refreshes_after_loop_change(monkeypatch):
    counter = {"value": 0}

    def fake_create_engine():
        counter["value"] += 1
        return DummyEngine(counter["value"])

    def fake_sessionmaker(engine, **_kwargs):
        return DummySessionFactory(engine)

    class DummyLoop:
        def __init__(self, label: int):
            self.label = label

    loop = {"value": DummyLoop(1)}

    monkeypatch.setattr(session_module, "_create_engine", fake_create_engine)
    monkeypatch.setattr(session_module, "async_sessionmaker", fake_sessionmaker)
    monkeypatch.setattr(session_module, "_engine", None)
    monkeypatch.setattr(session_module, "_session_maker", None)
    monkeypatch.setattr(session_module, "_runtime_pid", None)
    monkeypatch.setattr(session_module, "_runtime_loop", None)
    monkeypatch.setattr(session_module.os, "getpid", lambda: 301)
    monkeypatch.setattr(session_module.asyncio, "get_running_loop", lambda: loop["value"])

    first_session = session_module.async_session_maker()
    first_engine = session_module._engine
    loop["value"] = DummyLoop(2)
    second_session = session_module.async_session_maker()

    assert first_session["engine_label"] == 1
    assert second_session["engine_label"] == 2
    assert first_engine.dispose_calls == 1


def test_celery_worker_init_resets_db_runtime(monkeypatch):
    called = {"value": 0}

    def fake_reset_db_runtime():
        called["value"] += 1

    monkeypatch.setattr("app.db.session.reset_db_runtime", fake_reset_db_runtime)

    celery_app_module.reset_async_db_runtime()

    assert called["value"] == 1


def test_celery_publish_propagates_current_request_id():
    from app.core import observability
    from app.tasks import celery_app as celery_app_module

    tokens = observability.begin_request_context(
        request_id="req-publish",
        request_method="POST",
        request_path="/api/recordings",
    )
    try:
        headers: dict[str, str] = {}
        celery_app_module.propagate_request_id(headers=headers)
        assert headers[celery_app_module.REQUEST_ID_HEADER] == "req-publish"
    finally:
        observability.end_request_context(tokens)


def test_celery_task_prerun_and_postrun_manage_request_context():
    from types import SimpleNamespace

    from app.core import observability
    from app.tasks import celery_app as celery_app_module

    task = SimpleNamespace(
        name="app.tasks.example",
        request=SimpleNamespace(headers={celery_app_module.REQUEST_ID_HEADER: "req-task"}),
    )

    celery_app_module.begin_celery_task_request_context(task=task)
    assert observability.current_request_id() == "req-task"
    celery_app_module.end_celery_task_request_context(task=task)
    assert observability.current_request_id() is None


def test_celery_preload_voice_embedding_skips_when_voice_id_disabled(monkeypatch):
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(voice_identification_enabled=False),
    )

    celery_app_module.preload_voice_embedding_model()


def test_celery_preload_voice_embedding_loads_model_when_voice_id_enabled(monkeypatch):
    called = {"value": 0}

    def fake_get_model():
        called["value"] += 1
        return object()

    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(voice_identification_enabled=True),
    )
    monkeypatch.setattr("app.core.voice_embedding._get_model", fake_get_model)

    celery_app_module.preload_voice_embedding_model()

    assert called["value"] == 1


def test_celery_preload_voice_embedding_logs_and_continues_on_failure(monkeypatch):
    def failing_get_model():
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(voice_identification_enabled=True),
    )
    monkeypatch.setattr("app.core.voice_embedding._get_model", failing_get_model)

    celery_app_module.preload_voice_embedding_model()


def test_celery_app_has_no_stale_task_includes():
    assert celery_app_module.celery_app.conf.include in (None, ())


def test_recording_audio_processing_task_has_reliability_options():
    import app.tasks.recording_audio_processing  # noqa: F401

    task = celery_app_module.celery_app.tasks[
        "app.tasks.recording_audio_processing.process_staged_recording_upload"
    ]

    assert task.acks_late is True
    assert task.reject_on_worker_lost is True
    # Long-recording sizing from the 2026-05-31 batch cost incident: limits exceed
    # the worst-case recording, and the hard limit stays BELOW the broker
    # visibility_timeout (21600) so a hung task is killed before Redis redelivers.
    assert task.soft_time_limit == 21000
    assert task.time_limit == 21300
    assert task.max_retries == 1
    assert celery_app_module.celery_app.conf.visibility_timeout > task.time_limit
    assert (
        celery_app_module.celery_app.conf.broker_transport_options["visibility_timeout"]
        > task.time_limit
    )
    assert (
        celery_app_module.celery_app.conf.result_backend_transport_options["visibility_timeout"]
        > task.time_limit
    )


def test_summary_tasks_are_routed_to_dedicated_queue():
    import app.tasks.item_summary_generation  # noqa: F401
    import app.tasks.summary_generation  # noqa: F401

    routes = celery_app_module.celery_app.conf.task_routes

    assert celery_app_module.celery_app.conf.task_default_queue == "celery"
    assert routes["app.tasks.summary_generation.generate_recording_summary"] == {
        "queue": "summary"
    }
    assert routes["app.tasks.summary_generation.recover_missing_summary_generation_jobs"] == {
        "queue": "summary"
    }
    assert routes["app.tasks.item_summary_generation.generate_item_summary"] == {
        "queue": "summary"
    }


def test_embedding_backfill_task_is_registered_for_periodic_repair():
    import app.tasks.embedding_backfill  # noqa: F401

    assert (
        "app.tasks.embedding_backfill.backfill_missing_segment_embeddings"
        in celery_app_module.celery_app.tasks
    )
    assert "embedding-backfill-every-30-minutes" in celery_app_module.celery_app.conf.beat_schedule


def test_recording_processing_recovery_task_is_registered_for_periodic_repair():
    import app.tasks.recording_audio_processing  # noqa: F401

    assert (
        "app.tasks.recording_audio_processing.recover_stale_recording_processing"
        in celery_app_module.celery_app.tasks
    )
    schedule = celery_app_module.celery_app.conf.beat_schedule[
        "recording-processing-recovery-every-minute"
    ]
    assert (
        schedule["task"]
        == "app.tasks.recording_audio_processing.recover_stale_recording_processing"
    )
