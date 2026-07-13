"""Celery application configuration.

Uses Redis as broker and result backend. Celery Beat is embedded
in the worker process (-B flag) for single-node deployment.
"""

from datetime import timedelta
from uuid import uuid4

from celery import Celery
from celery.schedules import crontab
from celery.signals import (
    after_setup_logger,
    after_setup_task_logger,
    before_task_publish,
    task_postrun,
    task_prerun,
    worker_process_init,
)
from kombu import Exchange, Queue

from app.config import get_settings
from app.core.observability import (
    begin_request_context,
    configure_logging,
    current_request_id,
    end_request_context,
    initialize_sentry,
)

settings = get_settings()
configure_logging(log_format=settings.log_format)
REQUEST_ID_HEADER = "x-request-id"
_REQUEST_CONTEXT_ATTR = "_wai_request_context_tokens"
initialize_sentry(
    dsn=settings.sentry_dsn,
    debug=settings.debug,
    include_celery=True,
)


def _configure_celery_logging(logger=None, **_kwargs) -> None:  # noqa: ANN001
    configure_logging(log_format=settings.log_format, logger=logger)


after_setup_logger.connect(_configure_celery_logging)
after_setup_task_logger.connect(_configure_celery_logging)


@before_task_publish.connect
def propagate_request_id(headers=None, **_kwargs) -> None:
    if headers is None:
        return
    request_id = current_request_id()
    if request_id:
        headers.setdefault(REQUEST_ID_HEADER, request_id)


@task_prerun.connect
def begin_celery_task_request_context(task=None, **_kwargs) -> None:
    if task is None:
        return
    request = getattr(task, "request", None)
    headers = getattr(request, "headers", None) or {}
    request_id = (
        headers.get(REQUEST_ID_HEADER)
        or headers.get("X-Request-ID")
        or getattr(request, "id", None)
        or uuid4().hex
    )
    tokens = begin_request_context(
        request_id=str(request_id),
        request_method="CELERY",
        request_path=getattr(task, "name", None) or "-",
    )
    if request is not None:
        setattr(request, _REQUEST_CONTEXT_ATTR, tokens)


@task_postrun.connect
def end_celery_task_request_context(task=None, **_kwargs) -> None:
    request = getattr(task, "request", None) if task is not None else None
    tokens = getattr(request, _REQUEST_CONTEXT_ATTR, None)
    if tokens:
        end_request_context(tokens)
        delattr(request, _REQUEST_CONTEXT_ATTR)

celery_app = Celery(
    "waicomputer",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

DEFAULT_TASK_EXCHANGE = Exchange("celery", type="direct")
RECORDING_TASK_EXCHANGE = Exchange("recording", type="direct")
SUMMARY_TASK_EXCHANGE = Exchange("summary", type="direct")

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_default_queue="celery",
    task_default_exchange="celery",
    task_default_routing_key="celery",
    task_queues=(
        Queue("celery", DEFAULT_TASK_EXCHANGE, routing_key="celery"),
        Queue("recording", RECORDING_TASK_EXCHANGE, routing_key="recording"),
        Queue("summary", SUMMARY_TASK_EXCHANGE, routing_key="summary"),
    ),
    task_routes={
        "app.tasks.recording_audio_processing.process_staged_recording_upload": {
            "queue": "recording",
            "routing_key": "recording",
        },
        "app.tasks.media_import.import_uploaded_media": {
            "queue": "recording",
            "routing_key": "recording",
        },
        "app.tasks.telegram_media_import.import_telegram_media": {
            "queue": "recording",
            "routing_key": "recording",
        },
        "app.tasks.summary_generation.generate_recording_summary": {
            "queue": "summary",
            "routing_key": "summary",
        },
        "app.tasks.summary_generation.recover_missing_summary_generation_jobs": {
            "queue": "summary",
            "routing_key": "summary",
        },
        "app.tasks.item_summary_generation.generate_item_summary": {
            "queue": "summary",
            "routing_key": "summary",
        },
    },
    task_track_started=True,
    task_time_limit=3600,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    # Redis redelivers a task to another worker if it isn't acknowledged within
    # visibility_timeout. The default (1h) is shorter than a long recording's
    # transcription, which caused DUPLICATE concurrent transcription (double
    # Deepgram billing, 2026-05-31). Keep ABOVE the recording task hard time_limit.
    broker_transport_options={"visibility_timeout": 21600},
    visibility_timeout=21600,
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
    # Forked pool children run worker_process_init before reporting UP, and the
    # recording worker's ECAPA preload takes 3-5s cold (far longer under swap
    # pressure). The billiard default of 4s SIGKILLed mid-boot children on every
    # recycle, orphaning claimed tasks until the recovery sweeps re-queued them.
    worker_proc_alive_timeout=120,
    # Explicit imports: autodiscover_tasks only finds modules literally
    # named `tasks.py`; our task modules live under `app.tasks.<name>`.
    imports=[
        "app.tasks.agents",
        "app.tasks.billing_renewals",
        "app.tasks.comparison_generation",
        "app.tasks.consolidate_user_memory",
        "app.tasks.conversation_linking",
        "app.tasks.embedding_backfill",
        "app.tasks.item_summary_generation",
        "app.tasks.media_import",
        "app.tasks.recompile_entity_dossiers",
        "app.tasks.recording_audio_processing",
        "app.tasks.summary_audio_generation",
        "app.tasks.summary_generation",
        "app.tasks.telegram_album_import",
        "app.tasks.telegram_media_import",
        "app.tasks.telegram_reminders",
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
    "recompile-dirty-dossiers-hourly": {
        # O(changed) living-wiki refresh: bounded + cache-aware. OFF by default
        # (brain_dossier_recompile_enabled); the task no-ops when disabled.
        "task": "app.tasks.recompile_entity_dossiers.run",
        "schedule": crontab(minute=0),
    },
    "link-unlinked-conversations-nightly": {
        # Bounded backstop: chats auto-link on turn completion, but this links
        # the legacy backlog (and anything a dropped enqueue missed) a little
        # each night so the whole Brain converges without a cost spike.
        "task": "app.tasks.conversation_linking.sweep_unlinked_conversations",
        "schedule": crontab(hour=4, minute=0),
    },
    "embedding-backfill-every-30-minutes": {
        "task": "app.tasks.embedding_backfill.backfill_missing_segment_embeddings",
        "schedule": crontab(minute=f"*/{settings.embedding_backfill_interval_minutes}"),
    },
    "billing-renewals-every-15-minutes": {
        "task": "app.tasks.billing_renewals.charge_due_tinkoff_renewals",
        "schedule": crontab(minute="*/15"),
    },
    "billing-renewal-reminders-daily": {
        # Heads-up email ~3 days before each T-Bank recurring charge.
        "task": "app.tasks.billing_renewals.send_due_renewal_reminders",
        "schedule": crontab(hour=9, minute=0),
    },
    "recording-processing-recovery-every-minute": {
        "task": "app.tasks.recording_audio_processing.recover_stale_recording_processing",
        "schedule": timedelta(minutes=1),
    },
    "summary-generation-recovery-every-15-minutes": {
        "task": "app.tasks.summary_generation.recover_missing_summary_generation_jobs",
        "schedule": crontab(minute="*/15"),
        "kwargs": {"limit": 5},
    },
    "agent-dispatch-every-minute": {
        "task": "app.tasks.agents.dispatch_due_agents",
        "schedule": timedelta(minutes=1),
    },
    "agent-recovery-every-minute": {
        "task": "app.tasks.agents.recover_stale_agent_runs",
        "schedule": timedelta(minutes=1),
    },
    "agent-action-expiry-every-minute": {
        "task": "app.tasks.agents.expire_due_actions",
        "schedule": timedelta(minutes=1),
    },
    "telegram-reminders-every-minute": {
        "task": "app.tasks.telegram_reminders.dispatch_due",
        "schedule": timedelta(minutes=1),
    },
}


@worker_process_init.connect
def reset_async_db_runtime(**_kwargs) -> None:
    """Forked workers must not inherit async DB connections from the parent, and
    each task runs in its own asyncio.run() loop — so use NullPool here to avoid
    closing a pooled connection from a dead loop (MissingGreenlet)."""
    from app.db.session import enable_nullpool

    enable_nullpool()


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
