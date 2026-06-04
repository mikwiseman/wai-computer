"""Celery task for durable summary audio generation."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from billiard.exceptions import SoftTimeLimitExceeded

from app.core.observability import (
    capture_sentry_anomaly,
    capture_sentry_exception,
    fingerprint_text,
)
from app.core.summary_audio import (
    SummaryAudioError,
    fail_summary_audio_generation_job,
    generate_summary_audio_for_payload,
    persist_summary_audio_generation_result,
    prepare_summary_audio_generation_payload,
)
from app.core.xai_tts import XaiTTSError
from app.db.session import get_db_context
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _generate_summary_audio(
    *,
    artifact_id: str,
    task_id: str | None = None,
) -> None:
    artifact_uuid = UUID(artifact_id)
    async with get_db_context() as db:
        payload = await prepare_summary_audio_generation_payload(
            db,
            artifact_id=artifact_uuid,
            task_id=task_id,
        )

    if payload is None:
        return

    try:
        result = await generate_summary_audio_for_payload(payload)
    except XaiTTSError as exc:
        async with get_db_context() as db:
            await fail_summary_audio_generation_job(
                db,
                artifact_id=artifact_uuid,
                error_code=exc.code,
                error_message=exc.message,
            )
        raise
    except SummaryAudioError as exc:
        async with get_db_context() as db:
            await fail_summary_audio_generation_job(
                db,
                artifact_id=artifact_uuid,
                error_code=exc.code,
                error_message=exc.message,
            )
        raise
    except Exception as exc:  # noqa: BLE001
        capture_sentry_exception(exc)
        async with get_db_context() as db:
            await fail_summary_audio_generation_job(
                db,
                artifact_id=artifact_uuid,
                error_code="summary_audio_generation_failed",
                error_message="We couldn't create summary audio right now. Please try again.",
            )
        raise

    async with get_db_context() as db:
        await persist_summary_audio_generation_result(
            db,
            artifact_id=artifact_uuid,
            result=result,
        )


@celery_app.task(
    bind=True,
    name="app.tasks.summary_audio_generation.generate_summary_audio",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=180,
    time_limit=240,
)
def generate_summary_audio(self, *, artifact_id: str) -> None:
    try:
        logger.info(
            "summary audio task started artifact_id=%s task_id=%s",
            artifact_id,
            getattr(self.request, "id", None),
        )
        asyncio.run(
            _generate_summary_audio(
                artifact_id=artifact_id,
                task_id=getattr(self.request, "id", None),
            )
        )
        logger.info(
            "summary audio task finished artifact_id=%s task_id=%s",
            artifact_id,
            getattr(self.request, "id", None),
        )
    except SoftTimeLimitExceeded:
        asyncio.run(_mark_summary_audio_timeout(artifact_id=artifact_id))
        capture_sentry_anomaly(
            "summary_audio.generation.timeout",
            "Summary audio generation task timed out",
            category="summary_audio",
            extras={
                "artifact_id": artifact_id,
                "task_id": getattr(self.request, "id", None),
            },
            level="error",
        )
        raise
    except Exception as exc:
        logger.error(
            (
                "summary audio task failed artifact_id=%s task_id=%s "
                "error_type=%s error_fingerprint=%s"
            ),
            artifact_id,
            getattr(self.request, "id", None),
            type(exc).__name__,
            fingerprint_text(str(exc)),
        )
        raise


async def _mark_summary_audio_timeout(*, artifact_id: str) -> None:
    async with get_db_context() as db:
        await fail_summary_audio_generation_job(
            db,
            artifact_id=UUID(artifact_id),
            error_code="summary_audio_timeout",
            error_message="Summary audio generation timed out.",
        )
