"""Metadata-only AI/model usage ledger helpers."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_context
from app.models.ai_usage import AiUsageEvent

logger = logging.getLogger(__name__)

OPENAI_PROVIDER = "openai"
DEEPGRAM_PROVIDER = "deepgram"

# Explicit, low-cardinality feature names used by the admin dashboard.
FEATURE_COMPANION = "companion"
FEATURE_DICTATION = "dictation"
FEATURE_RECORDING = "recording"
FEATURE_MATERIALS = "materials"
FEATURE_BRAIN = "brain"
FEATURE_SEARCH = "search"
FEATURE_COMPARISON = "comparison"
FEATURE_MEMORY = "memory"
FEATURE_OCR = "ocr"
FEATURE_EMBEDDINGS = "embeddings"
FEATURE_TRANSCRIPTION = "transcription"

STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_REFUSED = "refused"

_PRICE_BY_PROVIDER_MODEL: dict[tuple[str, str], dict[str, float]] = {
    # OpenAI official list price as of the currently configured embedding model.
    # Unknown aliases such as gpt-5.5 intentionally stay unpriced unless added.
    (OPENAI_PROVIDER, "text-embedding-3-large"): {"input_per_1m": 0.13},
}


async def record_ai_usage_event(
    db: AsyncSession,
    *,
    provider: str,
    feature: str,
    operation: str,
    status: str,
    user_id: UUID | str | None = None,
    recording_id: UUID | str | None = None,
    item_id: UUID | str | None = None,
    conversation_id: UUID | str | None = None,
    message_id: UUID | str | None = None,
    model: str | None = None,
    response: Any = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cached_tokens: int | None = None,
    reasoning_tokens: int | None = None,
    total_tokens: int | None = None,
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
    """Persist a model/provider usage event without storing user content."""
    try:
        usage = usage_from_response(response)
        input_value = _int_or_none(input_tokens, usage.get("input_tokens"))
        output_value = _int_or_none(output_tokens, usage.get("output_tokens"))
        cached_value = _int_or_none(cached_tokens, usage.get("cached_tokens"))
        reasoning_value = _int_or_none(reasoning_tokens, usage.get("reasoning_tokens"))
        total_value = _int_or_none(
            total_tokens,
            usage.get("total_tokens"),
            _sum_tokens(input_value, output_value),
        )
        resolved_model = _bounded(model or _string_field(response, "model"), 120)
        cost, pricing_status = estimate_cost_usd(
            provider=provider,
            model=resolved_model,
            input_tokens=input_value,
            output_tokens=output_value,
            cached_tokens=cached_value,
            billable_seconds=_float_or_none(billable_seconds),
        )
        event = AiUsageEvent(
            user_id=_uuid_or_none(user_id),
            recording_id=_uuid_or_none(recording_id),
            item_id=_uuid_or_none(item_id),
            conversation_id=_uuid_or_none(conversation_id),
            message_id=_uuid_or_none(message_id),
            provider=_bounded(provider, 32) or "unknown",
            feature=_bounded(feature, 64) or "unknown",
            operation=_bounded(operation, 80) or "unknown",
            status=_bounded(status, 32) or STATUS_FAILED,
            model=resolved_model,
            input_tokens=input_value,
            output_tokens=output_value,
            cached_tokens=cached_value,
            reasoning_tokens=reasoning_value,
            total_tokens=total_value,
            audio_seconds=_float_or_none(audio_seconds),
            billable_seconds=_float_or_none(billable_seconds),
            channel_count=channel_count,
            audio_bytes=audio_bytes,
            latency_ms=latency_ms,
            estimated_cost_usd=cost,
            pricing_status=pricing_status,
            provider_status_code=provider_status_code,
            provider_error_code=_bounded(provider_error_code, 128),
            guard_code=_bounded(guard_code, 128),
            error_type=_bounded(error_type, 128),
            request_id=_bounded(request_id or _string_field(response, "id"), 128),
            task_id=_bounded(task_id, 128),
            details=_safe_details(details),
        )
        db.add(event)
        if commit:
            await db.commit()
        else:
            await db.flush()
    except Exception:  # noqa: BLE001 - analytics must not break product paths
        logger.warning("ai usage event dropped provider=%s feature=%s", provider, feature)
        if commit:
            try:
                await db.rollback()
            except Exception:
                pass


async def record_ai_usage_event_standalone(**kwargs: Any) -> None:
    try:
        async with get_db_context() as db:
            await record_ai_usage_event(db, **kwargs, commit=True)
    except Exception:  # noqa: BLE001 - analytics must not break product paths
        logger.warning(
            "standalone ai usage event dropped provider=%s feature=%s",
            kwargs.get("provider"),
            kwargs.get("feature"),
        )


def usage_from_response(response: Any) -> dict[str, int | None]:
    usage = _field(response, "usage")
    input_tokens = _usage_int(usage, "input_tokens", "prompt_tokens")
    output_tokens = _usage_int(usage, "output_tokens", "completion_tokens")
    total_tokens = _usage_int(usage, "total_tokens")
    cached_tokens = _cached_tokens(usage)
    reasoning_tokens = _reasoning_tokens(usage)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
    }


def estimate_cost_usd(
    *,
    provider: str,
    model: str | None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cached_tokens: int | None = None,
    billable_seconds: float | None = None,
) -> tuple[float | None, str]:
    del cached_tokens, billable_seconds
    if not model:
        return None, "unpriced"
    price = _PRICE_BY_PROVIDER_MODEL.get((provider, model))
    if not price:
        return None, "unpriced"
    total = 0.0
    if input_tokens and (rate := price.get("input_per_1m")):
        total += input_tokens * rate / 1_000_000
    if output_tokens and (rate := price.get("output_per_1m")):
        total += output_tokens * rate / 1_000_000
    return round(total, 8), "priced"


def _field(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _usage_int(usage: Any, *names: str) -> int | None:
    for name in names:
        raw = _field(usage, name)
        if isinstance(raw, int):
            return raw
    return None


def _cached_tokens(usage: Any) -> int | None:
    for details_name in ("input_tokens_details", "prompt_tokens_details"):
        details = _field(usage, details_name)
        raw = _field(details, "cached_tokens")
        if isinstance(raw, int):
            return raw
    raw = _field(usage, "cached_tokens")
    return raw if isinstance(raw, int) else None


def _reasoning_tokens(usage: Any) -> int | None:
    for details_name in ("output_tokens_details", "completion_tokens_details"):
        details = _field(usage, details_name)
        raw = _field(details, "reasoning_tokens")
        if isinstance(raw, int):
            return raw
    raw = _field(usage, "reasoning_tokens")
    return raw if isinstance(raw, int) else None


def _string_field(value: Any, name: str) -> str | None:
    raw = _field(value, name)
    return raw if isinstance(raw, str) and raw else None


def _sum_tokens(input_tokens: int | None, output_tokens: int | None) -> int | None:
    if input_tokens is None and output_tokens is None:
        return None
    return int(input_tokens or 0) + int(output_tokens or 0)


def _int_or_none(*values: int | None) -> int | None:
    for value in values:
        if isinstance(value, int):
            return value
    return None


def _float_or_none(value: float | int | None) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _uuid_or_none(value: UUID | str | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _bounded(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped[:max_length] if stripped else None


def _safe_details(details: dict[str, Any] | None) -> dict[str, Any] | None:
    if not details:
        return None
    allowed: dict[str, Any] = {}
    for key, value in details.items():
        if key not in {
            "pricing_note",
            "source",
            "purpose",
            "content_type",
            "input_count",
            "dimensions",
            "streamed",
            "step_count",
        }:
            continue
        if isinstance(value, str | int | float | bool) or value is None:
            allowed[key] = value
    return allowed or None
