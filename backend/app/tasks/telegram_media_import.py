"""Celery task: download + import Telegram media as a library recording.

The webhook acknowledges the sender ("Принял…") and enqueues this task; the
recording worker then downloads the file (file→file from the local Bot API
volume, or streamed over HTTP), extracts audio with ffmpeg when needed, runs
the guarded STT + summary pipeline, and delivers the full Telegram reply flow
(transcript .txt, summary + share button, error messages).

This work used to run inside the API webhook process, where a 236 MB video
OOM-killed the gunicorn worker (2026-07-09) — the sender got the "Принял…"
acknowledgement and then silence. Every failure path here must answer the
sender instead.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from billiard.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select

from app.config import get_settings
from app.core.observability import capture_sentry_anomaly, capture_sentry_exception
from app.core.recording_import import resolve_import_extension
from app.core.telegram_client import (
    TelegramBotClient,
    TelegramClientError,
    TelegramFileTooLargeError,
)
from app.db.session import get_db_context
from app.models.telegram import TelegramAccount
from app.models.user import User
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _chat_id(message: dict[str, Any]) -> int | None:
    chat = message.get("chat")
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    return chat_id if isinstance(chat_id, int) else None


async def _notify_failure(
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    status_message_id: int | None,
    text: str,
) -> None:
    """Best-effort user-facing failure reply; never masks the original error."""
    chat_id = _chat_id(message)
    if chat_id is None:
        return
    try:
        await client.send_message(
            chat_id,
            text,
            reply_to_message_id=message.get("message_id"),
        )
        if status_message_id is not None:
            await client.delete_message(chat_id, status_message_id)
    except TelegramClientError:
        logger.warning("telegram import failure notification failed")


async def _run(
    *,
    account_id: str,
    user_id: str,
    message: dict[str, Any],
    media: dict[str, Any],
    status_message_id: int | None,
) -> None:
    # The route helpers own the reply flow; imported lazily so the worker does
    # not pay the FastAPI route module import unless a Telegram import runs.
    from app.api.routes.telegram import (
        TELEGRAM_RECORDING_IMPORT_ERROR_REPLY,
        _import_telegram_media_and_reply,
        _set_telegram_import_error_context,
        _telegram_download_error_message,
        _telegram_file_too_large_message,
    )

    settings = get_settings()
    client = TelegramBotClient()
    async with get_db_context() as db:
        account = (
            await db.execute(
                select(TelegramAccount).where(TelegramAccount.id == UUID(account_id))
            )
        ).scalar_one_or_none()
        user = (
            await db.execute(select(User).where(User.id == UUID(user_id)))
        ).scalar_one_or_none()
        if account is None or user is None:
            logger.warning("telegram media import: account or user gone, dropping")
            return

        file_id = media.get("file_id")
        if not isinstance(file_id, str):
            logger.warning("telegram media import: missing file_id, dropping")
            return

        filename_hint = media.get("file_name")
        try:
            tg_file = await client.get_file(file_id)
            if (
                tg_file.file_size is not None
                and tg_file.file_size > settings.telegram_download_max_bytes
            ):
                raise TelegramFileTooLargeError(
                    "Telegram file exceeds configured limit"
                )
            ext = resolve_import_extension(
                filename_hint if isinstance(filename_hint, str) else tg_file.file_path,
                media.get("mime_type"),
            )
            dest = (
                Path(settings.upload_staging_dir)
                / "telegram"
                / user_id
                / f"{uuid4().hex}.{ext}"
            )
            await client.download_file_to_path(
                tg_file,
                dest,
                max_bytes=settings.telegram_download_max_bytes,
            )
        except TelegramFileTooLargeError:
            text = _telegram_file_too_large_message()
            await _set_telegram_import_error_context(db, account, message=text)
            await _notify_failure(
                client, message=message, status_message_id=status_message_id, text=text
            )
            return
        except TelegramClientError as exc:
            text = _telegram_download_error_message(exc)
            await _set_telegram_import_error_context(db, account, message=text)
            await _notify_failure(
                client, message=message, status_message_id=status_message_id, text=text
            )
            return
        except Exception:
            await _set_telegram_import_error_context(
                db, account, message=TELEGRAM_RECORDING_IMPORT_ERROR_REPLY
            )
            await _notify_failure(
                client,
                message=message,
                status_message_id=status_message_id,
                text=TELEGRAM_RECORDING_IMPORT_ERROR_REPLY,
            )
            raise

        try:
            # Handles its own import errors by replying to the sender.
            await _import_telegram_media_and_reply(
                db,
                client,
                message=message,
                account=account,
                user=user,
                media=media,
                status_message_id=status_message_id,
                source_path=dest,
                source_filename=tg_file.file_path,
            )
        finally:
            dest.unlink(missing_ok=True)


@celery_app.task(
    bind=True,
    name="app.tasks.telegram_media_import.import_telegram_media",
    acks_late=True,
    reject_on_worker_lost=True,
    # Multi-hour videos: download + ffmpeg + batch STT + summary. Must stay
    # BELOW the broker visibility_timeout (21600s) like the recording task so a
    # hung task dies before Redis redelivers a duplicate (2026-05-31 incident).
    soft_time_limit=10800,
    time_limit=10860,
    # The import pipeline is idempotent per NEW recording only via Telegram's
    # own dedupe (one update = one enqueue); retries would re-run STT on the
    # same media and re-bill, so failures answer the user instead of retrying.
    max_retries=0,
)
def import_telegram_media_task(
    self,
    *,
    account_id: str,
    user_id: str,
    message: dict[str, Any],
    media: dict[str, Any],
    status_message_id: int | None = None,
) -> None:
    try:
        logger.info("telegram media import task started kind=%s", media.get("kind"))
        asyncio.run(
            _run(
                account_id=account_id,
                user_id=user_id,
                message=message,
                media=media,
                status_message_id=status_message_id,
            )
        )
        logger.info("telegram media import task finished kind=%s", media.get("kind"))
    except SoftTimeLimitExceeded:
        capture_sentry_anomaly(
            "telegram.media_import.timeout",
            "Telegram media import timed out",
            category="recording",
            extras={"media_kind": media.get("kind")},
            level="error",
        )
        raise
    except Exception as exc:  # noqa: BLE001
        capture_sentry_exception(exc)
        logger.error(
            "telegram media import task failed error_type=%s", type(exc).__name__
        )
        raise
