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
    monkeypatch.setattr(session_module, "_runtime_loop_id", None)
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


def test_celery_app_has_no_stale_task_includes():
    assert celery_app_module.celery_app.conf.include in (None, ())
