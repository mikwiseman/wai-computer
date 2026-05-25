"""Celery task for canonical audio-backed recording processing."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from app.core.recording_audio_processing import (
    process_staged_recording_upload as process_staged_recording_upload_core,
)
from app.db.session import get_db_context
from app.tasks.celery_app import celery_app


async def _process_staged_recording_upload(
    *,
    recording_id: str,
    user_id: str,
    staged_path: str,
    content_type: str,
    user_default_language: str | None,
) -> None:
    async with get_db_context() as db:
        await process_staged_recording_upload_core(
            db,
            recording_id=UUID(recording_id),
            user_id=UUID(user_id),
            staged_path=Path(staged_path),
            content_type=content_type,
            user_default_language=user_default_language,
        )


@celery_app.task(name="app.tasks.recording_audio_processing.process_staged_recording_upload")
def process_staged_recording_upload(
    *,
    recording_id: str,
    user_id: str,
    staged_path: str,
    content_type: str,
    user_default_language: str | None,
) -> None:
    asyncio.run(
        _process_staged_recording_upload(
            recording_id=recording_id,
            user_id=user_id,
            staged_path=staged_path,
            content_type=content_type,
            user_default_language=user_default_language,
        )
    )
