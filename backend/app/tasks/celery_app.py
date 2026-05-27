"""Celery application configuration.

Uses Redis as broker and result backend. Celery Beat is embedded
in the worker process (-B flag) for single-node deployment.
"""

from datetime import timedelta

from celery import Celery
from celery.schedules import crontab
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
    # Explicit imports: autodiscover_tasks only finds modules literally
    # named `tasks.py`; our task modules live under `app.tasks.<name>`.
    imports=[
        "app.tasks.billing_renewals",
        "app.tasks.consolidate_user_memory",
        "app.tasks.embedding_backfill",
        "app.tasks.recording_audio_processing",
        "app.tasks.summary_generation",
    ],
)

celery_app.conf.beat_schedule = {
    "consolidate-user-memory-nightly": {
        # Sleep-time consolidation of Wai's long-term memory blocks.
        # Per-user-local-time scheduling is a Phase 4 nicety; daily 03:00
        # UTC covers most of Europe/Africa overnight.
        "task": "app.tasks.consolidate_user_memory.run",
        "schedule": crontab(hour=3, minute=0),
    },
    "embedding-backfill-every-30-minutes": {
        "task": "app.tasks.embedding_backfill.backfill_missing_segment_embeddings",
        "schedule": timedelta(minutes=settings.embedding_backfill_interval_minutes),
    },
    "billing-renewals-every-15-minutes": {
        "task": "app.tasks.billing_renewals.charge_due_tinkoff_renewals",
        "schedule": timedelta(minutes=15),
    },
    "recording-processing-recovery-every-minute": {
        "task": "app.tasks.recording_audio_processing.recover_stale_recording_processing",
        "schedule": timedelta(minutes=1),
    },
}


@worker_process_init.connect
def reset_async_db_runtime(**_kwargs) -> None:
    """Ensure forked workers do not inherit async DB connections from the parent process."""
    from app.db.session import reset_db_runtime

    reset_db_runtime()
