"""Celery application configuration.

Uses Redis as broker and result backend. Celery Beat is embedded
in the worker process (-B flag) for single-node deployment.
"""

from celery import Celery
from celery.signals import worker_process_init

from app.config import get_settings
from app.core.observability import initialize_sentry

settings = get_settings()
initialize_sentry(
    dsn=settings.sentry_dsn,
    debug=settings.debug,
    include_celery=True,
)

celery_app = Celery(
    "waicomputer",
    broker=settings.redis_url,
    backend=settings.redis_url,
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
    result_expires=3600,
    worker_max_tasks_per_child=100,
)

celery_app.conf.beat_schedule = {}


@worker_process_init.connect
def reset_async_db_runtime(**_kwargs) -> None:
    """Ensure forked workers do not inherit async DB connections from the parent process."""
    from app.db.session import reset_db_runtime

    reset_db_runtime()
