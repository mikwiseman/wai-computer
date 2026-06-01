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
    # Redis redelivers a task to another worker if it isn't acknowledged within
    # visibility_timeout. The default (1h) is shorter than a long recording's
    # transcription, which caused DUPLICATE concurrent transcription (double
    # Deepgram billing, 2026-05-31). Keep ABOVE the recording task hard time_limit.
    broker_transport_options={"visibility_timeout": 21600},
    # Mirror visibility_timeout onto the result backend transport: if this Redis
    # is ever shared with another app, the SHORTEST visibility_timeout wins (a
    # documented footgun), so keep them consistent. worker_deduplicate_successful_tasks
    # is belt-and-suspenders (drops an already-succeeded redelivered task) — the
    # robust protection is the app-level segment-existence idempotency guard;
    # result_expires=3600 bounds how long this dedupe can help.
    result_backend_transport_options={"visibility_timeout": 21600},
    worker_deduplicate_successful_tasks=True,
    result_expires=3600,
    worker_max_tasks_per_child=100,
    # Explicit imports: autodiscover_tasks only finds modules literally
    # named `tasks.py`; our task modules live under `app.tasks.<name>`.
    imports=[
        "app.tasks.billing_renewals",
        "app.tasks.comparison_generation",
        "app.tasks.consolidate_user_memory",
        "app.tasks.embedding_backfill",
        "app.tasks.item_summary_generation",
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


@worker_process_init.connect
def preload_voice_embedding_model(**_kwargs) -> None:
    """Eagerly load the ECAPA-TDNN model so the first recording in this worker
    doesn't pay the ~3-5s SpeechBrain initialisation cost mid-pipeline.

    Only runs when voice identification is enabled for this process — the API
    container has it off, so this is effectively a no-op there.
    """
    import logging

    from app.config import get_settings

    logger = logging.getLogger(__name__)
    settings = get_settings()
    if not settings.voice_identification_enabled:
        logger.info("voice ID disabled in this worker; skipping ECAPA preload")
        return
    try:
        from app.core.voice_embedding import _get_model

        _get_model()
        logger.info("Preloaded ECAPA-TDNN voice embedding model")
    except Exception:
        logger.exception(
            "Failed to preload ECAPA voice embedding model; first inference "
            "will pay cold-start cost"
        )
