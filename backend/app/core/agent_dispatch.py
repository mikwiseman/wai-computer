"""Shared dispatch helper for queued agent runs."""

from __future__ import annotations

from uuid import UUID


class AgentDispatchError(Exception):
    """The broker did not accept an agent run."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def enqueue_agent_run(run_id: UUID | str) -> str | None:
    """Enqueue a run in Celery and surface broker failures to callers."""
    try:
        from app.tasks.agents import run as agent_run_task

        result = agent_run_task.delay(str(run_id))
    except Exception as exc:  # noqa: BLE001 - broker failure must be visible.
        raise AgentDispatchError("Could not start agent run") from exc
    return getattr(result, "id", None)
