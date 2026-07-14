"""Celery task: generate summary audio and deliver it into a Telegram chat.

The 🎧 Озвучить button starts (or reuses) the same durable summary-audio
artifact the apps use; this task runs the identical prepare → generate →
persist pipeline and then sends the finished track into the chat. Every
failure path answers the sender — a tapped button must never end in silence.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from uuid import UUID

from billiard.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select

from app.core.observability import capture_sentry_anomaly, capture_sentry_exception
from app.core.summary_audio import (
    SummaryAudioError,
    fail_summary_audio_generation_job,
    generate_summary_audio_for_payload,
    persist_summary_audio_generation_result,
    prepare_summary_audio_generation_payload,
)
from app.core.telegram_client import TelegramBotClient, TelegramClientError
from app.core.xai_tts import XaiTTSError
from app.db.session import get_db_context
from app.models.summary_audio import SummaryAudioArtifact, SummaryAudioStatus
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_TTS_FAILURE_REPLY = "Озвучить саммари не получилось. Попробуй ещё раз позже."


async def _notify(client: TelegramBotClient, chat_id: int, text: str) -> None:
    try:
        await client.send_message(chat_id, text)
    except TelegramClientError:
        logger.warning("telegram summary audio notification failed")


async def _set_button_markup(
    client: TelegramBotClient,
    *,
    chat_id: int,
    message_id: int | None,
    markup: dict | None,
) -> None:
    """Best-effort inline-keyboard swap on the summary message — the button
    states are cosmetic and must never fail the delivery."""
    if message_id is None or markup is None:
        return
    try:
        await client.edit_message_reply_markup(chat_id, message_id, markup)
    except TelegramClientError:
        logger.info("telegram summary audio: button markup edit skipped")


async def _record_voice_heartbeat(client: TelegramBotClient, chat_id: int) -> None:
    """Keep the chat header showing "recording voice message…" while the track
    renders. Telegram clears a chat action after ~5s, so re-send every 4s."""
    try:
        while True:
            try:
                await client.send_chat_action(chat_id, "record_voice")
            except TelegramClientError:
                return  # cosmetic; never let the indicator kill the task
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


async def _run(
    *,
    artifact_id: str,
    chat_id: int,
    reply_to_message_id: int | None,
    task_id: str | None,
    button_message_id: int | None = None,
    restore_markup: dict | None = None,
    final_markup: dict | None = None,
) -> None:
    # Route helpers own the delivery formatting; imported lazily so the worker
    # does not pay the FastAPI route module import unless a delivery runs.
    from app.api.routes.telegram import deliver_summary_audio_to_telegram

    artifact_uuid = UUID(artifact_id)
    client = TelegramBotClient()

    async with get_db_context() as db:
        payload = await prepare_summary_audio_generation_payload(
            db, artifact_id=artifact_uuid, task_id=task_id
        )

    if payload is not None:
        heartbeat = asyncio.create_task(_record_voice_heartbeat(client, chat_id))
        try:
            result = await generate_summary_audio_for_payload(payload)
        except (XaiTTSError, SummaryAudioError) as exc:
            code = getattr(exc, "code", "summary_audio_generation_failed")
            message = getattr(exc, "message", str(exc))
            async with get_db_context() as db:
                await fail_summary_audio_generation_job(
                    db,
                    artifact_id=artifact_uuid,
                    error_code=code,
                    error_message=message,
                )
            await _notify(client, chat_id, _TTS_FAILURE_REPLY)
            # Give the button back so the user can retry with one tap.
            await _set_button_markup(
                client,
                chat_id=chat_id,
                message_id=button_message_id,
                markup=restore_markup,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            capture_sentry_exception(exc)
            async with get_db_context() as db:
                await fail_summary_audio_generation_job(
                    db,
                    artifact_id=artifact_uuid,
                    error_code="summary_audio_generation_failed",
                    error_message="We couldn't create summary audio right now.",
                )
            await _notify(client, chat_id, _TTS_FAILURE_REPLY)
            await _set_button_markup(
                client,
                chat_id=chat_id,
                message_id=button_message_id,
                markup=restore_markup,
            )
            raise
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

        async with get_db_context() as db:
            await persist_summary_audio_generation_result(
                db, artifact_id=artifact_uuid, result=result
            )

    async with get_db_context() as db:
        artifact = (
            await db.execute(
                select(SummaryAudioArtifact).where(
                    SummaryAudioArtifact.id == artifact_uuid
                )
            )
        ).scalar_one_or_none()
        if artifact is None:
            logger.warning("telegram summary audio: artifact gone, dropping")
            return
        if artifact.status != SummaryAudioStatus.SUCCEEDED.value:
            # prepare() returned None because the artifact was claimed/failed
            # elsewhere; the failure was already surfaced by that path.
            logger.info(
                "telegram summary audio: artifact not succeeded status=%s",
                artifact.status,
            )
            await _set_button_markup(
                client,
                chat_id=chat_id,
                message_id=button_message_id,
                markup=restore_markup,
            )
            return
        try:
            # The header flips from "recording…" to "sending voice message…"
            # right before the upload lands.
            try:
                await client.send_chat_action(chat_id, "upload_voice")
            except TelegramClientError:
                pass  # cosmetic
            await deliver_summary_audio_to_telegram(
                db,
                client,
                artifact=artifact,
                chat_id=chat_id,
                reply_to_message_id=reply_to_message_id,
            )
        except (SummaryAudioError, TelegramClientError, OSError) as exc:
            logger.warning(
                "telegram summary audio delivery failed error=%s", type(exc).__name__
            )
            await _notify(
                client, chat_id, "Аудио готово, но отправить не вышло. Попробуй ещё раз."
            )
            await _set_button_markup(
                client,
                chat_id=chat_id,
                message_id=button_message_id,
                markup=restore_markup,
            )
            raise
        # Delivered: the voice bubble replaces the button.
        await _set_button_markup(
            client,
            chat_id=chat_id,
            message_id=button_message_id,
            markup=final_markup,
        )


@celery_app.task(
    bind=True,
    name="app.tasks.telegram_summary_audio.deliver_summary_audio_telegram",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=180,
    time_limit=240,
    # A retry could double-send the track; failures answer the user instead.
    max_retries=0,
)
def deliver_summary_audio_telegram_task(
    self,
    *,
    artifact_id: str,
    chat_id: int,
    reply_to_message_id: int | None = None,
    button_message_id: int | None = None,
    restore_markup: dict | None = None,
    final_markup: dict | None = None,
) -> None:
    try:
        logger.info("telegram summary audio task started artifact_id=%s", artifact_id)
        asyncio.run(
            _run(
                artifact_id=artifact_id,
                chat_id=chat_id,
                reply_to_message_id=reply_to_message_id,
                task_id=getattr(self.request, "id", None),
                button_message_id=button_message_id,
                restore_markup=restore_markup,
                final_markup=final_markup,
            )
        )
        logger.info("telegram summary audio task finished artifact_id=%s", artifact_id)
    except SoftTimeLimitExceeded:
        capture_sentry_anomaly(
            "telegram.summary_audio.timeout",
            "Telegram summary audio delivery timed out",
            category="summary_audio",
            extras={"artifact_id": artifact_id},
            level="error",
        )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "telegram summary audio task failed artifact_id=%s error_type=%s",
            artifact_id,
            type(exc).__name__,
        )
        raise
