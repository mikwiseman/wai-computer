"""Celery application configuration.

Uses Redis as broker and result backend. Celery Beat is embedded
in the worker process (-B flag) for single-node deployment.
"""

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "wai_computer",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.agent_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)

celery_app.conf.beat_schedule = {
    "run-due-agents": {
        "task": "app.tasks.agent_tasks.run_due_agents",
        "schedule": 60,
    },
}
