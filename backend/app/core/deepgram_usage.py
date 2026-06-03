"""Deepgram usage tagging and durable usage ledger helpers."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.ai_usage import (
    DEEPGRAM_PROVIDER,
    FEATURE_TRANSCRIPTION,
    record_ai_usage_event,
)
from app.db.session import get_db_context
from app.models.deepgram_usage import DeepgramUsageEvent

logger = logging.getLogger(__name__)

DEEPGRAM_TAG_APP = "app:wai-computer"
DEEPGRAM_TAG_LIMIT = 128


def deepgram_usage_tags(*, operation: str, purpose: str) -> list[str]:
    """Low-cardinality tags safe for Deepgram usage charts."""
    settings = get_settings()
    environment = "dev" if settings.debug else "prod"
    return [
        DEEPGRAM_TAG_APP,
        f"env:{environment}",
        f"operation:{_tag_value(operation)}",
        f"purpose:{_tag_value(purpose)}",
    ]


def sanitize_deepgram_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    sanitized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        value = _tag_value(tag)
        if not value or value in seen:
            continue
        seen.add(value)
        sanitized.append(value)
    return sanitized


def provider_error_code(error: httpx.HTTPStatusError) -> str | None:
    try:
        payload = error.response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    for container_key in ("error", "detail"):
        container = payload.get(container_key)
        if isinstance(container, dict):
            for key in ("code", "type", "status"):
                value = container.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    for key in ("code", "type", "status"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def record_deepgram_usage_event(
    db: AsyncSession,
    *,
    operation: str,
    purpose: str,
    status: str,
    user_id: UUID | str | None = None,
    recording_id: UUID | str | None = None,
    model: str | None = None,
    language: str | None = None,
    content_type: str | None = None,
    audio_seconds: float | int | None = None,
    billable_seconds: float | int | None = None,
    channel_count: int | None = None,
    audio_bytes: int | None = None,
    latency_ms: int | None = None,
    provider_status_code: int | None = None,
    provider_error_code: str | None = None,
    guard_code: str | None = None,
    error_type: str | None = None,
    request_id: str | None = None,
    task_id: str | None = None,
    details: dict[str, Any] | None = None,
    commit: bool = False,
) -> None:
    """Persist a Deepgram usage event.

    Callers use ``commit=True`` when the event must survive a later route/task
    rollback. The helper never raises because observability must not break STT.
    """
    try:
        event = DeepgramUsageEvent(
            user_id=_uuid_or_none(user_id),
            recording_id=_uuid_or_none(recording_id),
            operation=operation,
            purpose=purpose,
            status=status,
            model=_bounded(model, 80),
            language=_bounded(language, 32),
            content_type=_bounded(content_type, 128),
            audio_seconds=_float_or_none(audio_seconds),
            billable_seconds=_float_or_none(billable_seconds),
            channel_count=channel_count,
            audio_bytes=audio_bytes,
            latency_ms=latency_ms,
            provider_status_code=provider_status_code,
            provider_error_code=_bounded(provider_error_code, 128),
            guard_code=_bounded(guard_code, 128),
            error_type=_bounded(error_type, 128),
            request_id=_bounded(request_id, 128),
            task_id=_bounded(task_id, 128),
            details=details,
        )
        db.add(event)
        await record_ai_usage_event(
            db,
            provider=DEEPGRAM_PROVIDER,
            feature=_feature_for_purpose(purpose),
            operation=operation,
            status=status,
            user_id=user_id,
            recording_id=recording_id,
            model=model,
            audio_seconds=audio_seconds,
            billable_seconds=billable_seconds,
            channel_count=channel_count,
            audio_bytes=audio_bytes,
            latency_ms=latency_ms,
            provider_status_code=provider_status_code,
            provider_error_code=provider_error_code,
            guard_code=guard_code,
            error_type=error_type,
            request_id=request_id,
            task_id=task_id,
            details={
                "source": "deepgram_usage_events",
                "purpose": purpose,
                "content_type": content_type,
            },
        )
        if commit:
            await db.commit()
        else:
            await db.flush()
    except Exception as exc:  # noqa: BLE001 - usage logging must never break STT
        logger.warning("deepgram usage event dropped error_type=%s", type(exc).__name__)
        if commit:
            try:
                await db.rollback()
            except Exception:
                pass


async def record_deepgram_usage_event_standalone(**kwargs: Any) -> None:
    async with get_db_context() as db:
        await record_deepgram_usage_event(db, **kwargs, commit=True)


def effective_billable_seconds(
    *,
    audio_seconds: float | int | None,
    channel_count: int | None = None,
    provider_opened: bool = True,
) -> float | None:
    if not provider_opened:
        return 0.0
    seconds = _float_or_none(audio_seconds)
    if seconds is None:
        return None
    channels = max(1, int(channel_count or 1))
    return round(seconds * channels, 3)


def _tag_value(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "-")
    return normalized[:DEEPGRAM_TAG_LIMIT]


def _feature_for_purpose(purpose: str) -> str:
    normalized = purpose.strip().lower()
    if normalized in {"recording", "dictation", "materials", "telegram"}:
        return normalized
    return FEATURE_TRANSCRIPTION


def _uuid_or_none(value: UUID | str | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: float | int | None) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _bounded(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped[:max_length] if stripped else None
