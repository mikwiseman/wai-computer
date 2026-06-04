"""Small contract tests for agent dispatch and self-host export helpers."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.agent_dispatch import AgentDispatchError, enqueue_agent_run
from app.core.self_host_migration import (
    _derived_owner_edge,
    _table_scope_strategy,
    migration_contract_response,
)
from app.tasks import agents as agent_tasks


def test_enqueue_agent_run_returns_broker_task_id(monkeypatch):
    seen: list[str] = []

    def fake_delay(run_id: str):
        seen.append(run_id)
        return SimpleNamespace(id="celery-task-1")

    run_id = uuid4()
    monkeypatch.setattr(agent_tasks.run, "delay", fake_delay)

    assert enqueue_agent_run(run_id) == "celery-task-1"
    assert seen == [str(run_id)]


def test_enqueue_agent_run_surfaces_broker_failure(monkeypatch):
    def fail_delay(_run_id: str):
        raise RuntimeError("redis offline")

    monkeypatch.setattr(agent_tasks.run, "delay", fail_delay)

    with pytest.raises(AgentDispatchError) as exc:
        enqueue_agent_run(uuid4())

    assert exc.value.message == "Could not start agent run"


def test_self_host_contract_helper_classifies_owner_edges():
    assert _table_scope_strategy("agents") == "owner_scoped_user_id"
    assert _table_scope_strategy("agent_steps") == "derived_owner_scoped"
    assert _table_scope_strategy("missing_table") == "model_table_missing"

    edge = _derived_owner_edge("agent_steps")
    assert edge == {
        "parent_table": "agent_runs",
        "local_column": "run_id",
        "parent_column": "id",
        "owner_column": "user_id",
    }
    assert _derived_owner_edge("agents") is None


def test_self_host_contract_groups_non_owned_tables_and_artifacts():
    contract = migration_contract_response()

    assert contract["reconnect_required"]["tables"]
    assert contract["server_local"]["tables"]
    assert contract["excluded"]["tables"]
    assert contract["owned_exportable"]["artifacts"]
    assert contract["server_local"]["artifacts"]
    assert contract["reconnect_required"]["artifacts"] == []
    assert contract["excluded"]["artifacts"] == []
