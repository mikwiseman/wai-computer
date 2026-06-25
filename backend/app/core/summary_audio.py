"""Lifecycle helpers for server-generated summary audio."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.ai_usage import (
    FEATURE_SUMMARY_AUDIO,
    STATUS_SUCCEEDED,
    XAI_PROVIDER,
    record_ai_usage_event,
)
from app.core.xai_tts import XaiTTSResult, synthesize_xai_tts
from app.models.item import Item, ItemSummary
from app.models.recording import Recording, Segment
from app.models.summary_audio import SummaryAudioArtifact, SummaryAudioStatus

ACTIVE_SUMMARY_AUDIO_STATUSES = {
    SummaryAudioStatus.QUEUED.value,
    SummaryAudioStatus.RUNNING.value,
}

SUMMARY_AUDIO_SOURCE_RECORDING = "recording"
SUMMARY_AUDIO_SOURCE_ITEM = "item"


@dataclass(frozen=True)
class SummaryAudioPayload:
    artifact_id: UUID
    user_id: UUID
    recording_id: UUID | None
    item_id: UUID | None
    source_kind: str
    text: str
    summary_hash: str
    input_char_count: int
    provider: str
    model: str
    voice_id: str
    language: str
    codec: str
    sample_rate: int
    bit_rate: int
    text_normalization: bool
    task_id: str | None


class SummaryAudioError(RuntimeError):
    """User-visible summary audio failure without raw summary text."""

    def __init__(self, *, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def summary_audio_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_recording_summary_audio_text(recording: Recording) -> str:
    if recording.summary is None:
        return ""
    names = _assigned_speaker_names(recording)
    summary = recording.summary
    values = [
        _apply_speaker_names(summary.summary, names),
        *[_apply_speaker_names(str(point), names) for point in summary.key_points or []],
        *_json_lines(summary.decisions),
        *_json_lines(summary.topics),
        *_json_lines(summary.people_mentioned),
    ]
    return _join_spoken_summary(values)


def build_item_summary_audio_text(summary: ItemSummary | None) -> str:
    if summary is None:
        return ""
    values = [
        summary.summary,
        *_json_lines(summary.key_points),
        *_json_lines(summary.key_moments, preferred_keys=("moment", "why_it_matters", "quote")),
        *_json_lines(summary.action_items, preferred_keys=("task", "owner", "due", "priority")),
        *_json_lines(summary.topics),
        *_json_lines(summary.people_mentioned),
    ]
    return _join_spoken_summary(values)


async def start_summary_audio_artifact(
    db: AsyncSession,
    *,
    source_kind: str,
    source_id: UUID,
    user_id: UUID,
) -> SummaryAudioArtifact:
    settings = get_settings()
    if not settings.summary_audio_enabled:
        raise SummaryAudioError(
            code="summary_audio_disabled",
            message="Summary audio is disabled.",
            status_code=503,
        )
    if settings.summary_audio_provider != XAI_PROVIDER:
        raise SummaryAudioError(
            code="summary_audio_provider_unsupported",
            message="Configured summary audio provider is unsupported.",
            status_code=503,
        )

    text, owner_id = await _load_source_text_for_update(
        db,
        source_kind=source_kind,
        source_id=source_id,
        user_id=user_id,
    )
    if owner_id is None:
        raise SummaryAudioError(
            code="source_not_found",
            message="Source not found.",
            status_code=404,
        )
    if not text:
        raise SummaryAudioError(
            code="summary_missing",
            message="Summary has not been generated.",
            status_code=404,
        )

    char_count = len(text)
    if char_count > settings.summary_audio_max_chars:
        raise SummaryAudioError(
            code="summary_audio_text_too_long",
            message="Summary is too long to turn into audio.",
            status_code=413,
        )
    await _enforce_daily_caps(db, user_id=user_id, input_char_count=char_count)

    current_hash = summary_audio_hash(text)
    active = await load_active_summary_audio_artifact(
        db, source_kind=source_kind, source_id=source_id, user_id=user_id
    )
    if active is not None:
        if active.summary_hash == current_hash:
            return active
        mark_summary_audio_failed(
            active,
            error_code="stale_summary",
            error_message="Summary changed before audio generation started.",
        )
        await db.flush()

    cached = await load_latest_summary_audio_artifact(
        db,
        source_kind=source_kind,
        source_id=source_id,
        user_id=user_id,
        summary_hash=current_hash,
        status_value=SummaryAudioStatus.SUCCEEDED.value,
    )
    if cached is not None:
        return cached

    artifact = SummaryAudioArtifact(
        user_id=user_id,
        recording_id=source_id if source_kind == SUMMARY_AUDIO_SOURCE_RECORDING else None,
        item_id=source_id if source_kind == SUMMARY_AUDIO_SOURCE_ITEM else None,
        source_kind=source_kind,
        status=SummaryAudioStatus.QUEUED.value,
        stage="queued",
        progress_percent=5,
        summary_hash=current_hash,
        input_char_count=char_count,
        provider=settings.summary_audio_provider,
        model=settings.summary_audio_model,
        voice_id=settings.summary_audio_voice_id,
        language=settings.summary_audio_language,
        content_type="audio/mpeg",
    )
    db.add(artifact)
    await db.flush()
    return artifact


async def load_active_summary_audio_artifact(
    db: AsyncSession,
    *,
    source_kind: str,
    source_id: UUID,
    user_id: UUID,
) -> SummaryAudioArtifact | None:
    statement = _source_artifact_query(source_kind, source_id, user_id).where(
        SummaryAudioArtifact.status.in_(ACTIVE_SUMMARY_AUDIO_STATUSES)
    )
    result = await db.execute(statement.order_by(SummaryAudioArtifact.created_at.desc()).limit(1))
    return result.scalar_one_or_none()


async def load_latest_summary_audio_artifact(
    db: AsyncSession,
    *,
    source_kind: str,
    source_id: UUID,
    user_id: UUID,
    summary_hash: str | None = None,
    status_value: str | None = None,
) -> SummaryAudioArtifact | None:
    statement = _source_artifact_query(source_kind, source_id, user_id)
    if summary_hash is not None:
        statement = statement.where(SummaryAudioArtifact.summary_hash == summary_hash)
    if status_value is not None:
        statement = statement.where(SummaryAudioArtifact.status == status_value)
    result = await db.execute(statement.order_by(SummaryAudioArtifact.created_at.desc()).limit(1))
    return result.scalar_one_or_none()


def latest_summary_audio_artifact_for_hash(
    artifacts: list[SummaryAudioArtifact],
    summary_hash: str,
) -> SummaryAudioArtifact | None:
    matches = [artifact for artifact in artifacts if artifact.summary_hash == summary_hash]
    if not matches:
        return None
    return max(matches, key=lambda item: item.created_at or item.requested_at)


async def prepare_summary_audio_generation_payload(
    db: AsyncSession,
    *,
    artifact_id: UUID,
    task_id: str | None = None,
) -> SummaryAudioPayload | None:
    artifact = await _load_artifact_for_update(db, artifact_id)
    if artifact is None or artifact.status not in ACTIVE_SUMMARY_AUDIO_STATUSES:
        return None

    artifact.status = SummaryAudioStatus.RUNNING.value
    artifact.stage = "preparing_summary"
    artifact.progress_percent = 10
    artifact.task_id = task_id or artifact.task_id
    artifact.started_at = artifact.started_at or datetime.now(timezone.utc)
    artifact.attempt_count += 1

    text = await _current_text_for_artifact(db, artifact)
    if not text:
        mark_summary_audio_failed(
            artifact,
            error_code="summary_missing",
            error_message="Summary has not been generated.",
        )
        return None
    if summary_audio_hash(text) != artifact.summary_hash:
        mark_summary_audio_failed(
            artifact,
            error_code="stale_summary",
            error_message="Summary changed before audio generation started.",
        )
        return None
    if len(text) > get_settings().summary_audio_max_chars:
        mark_summary_audio_failed(
            artifact,
            error_code="summary_audio_text_too_long",
            error_message="Summary is too long to turn into audio.",
        )
        return None

    artifact.stage = "generating_audio"
    artifact.progress_percent = 35
    await db.flush()
    settings = get_settings()
    return SummaryAudioPayload(
        artifact_id=artifact.id,
        user_id=artifact.user_id,
        recording_id=artifact.recording_id,
        item_id=artifact.item_id,
        source_kind=artifact.source_kind,
        text=text,
        summary_hash=artifact.summary_hash,
        input_char_count=artifact.input_char_count,
        provider=artifact.provider,
        model=artifact.model,
        voice_id=artifact.voice_id,
        language=artifact.language,
        codec=settings.summary_audio_codec,
        sample_rate=settings.summary_audio_output_sample_rate,
        bit_rate=settings.summary_audio_output_bit_rate,
        text_normalization=settings.summary_audio_text_normalization,
        task_id=artifact.task_id,
    )


async def generate_summary_audio_for_payload(payload: SummaryAudioPayload) -> XaiTTSResult:
    if payload.provider != XAI_PROVIDER:
        raise SummaryAudioError(
            code="summary_audio_provider_unsupported",
            message="Configured summary audio provider is unsupported.",
            status_code=503,
        )
    return await synthesize_xai_tts(
        text=payload.text,
        voice_id=payload.voice_id,
        language=payload.language,
        codec=payload.codec,
        sample_rate=payload.sample_rate,
        bit_rate=payload.bit_rate,
        text_normalization=payload.text_normalization,
    )


async def persist_summary_audio_generation_result(
    db: AsyncSession,
    *,
    artifact_id: UUID,
    result: XaiTTSResult,
) -> SummaryAudioArtifact | None:
    artifact = await _load_artifact_for_update(db, artifact_id)
    if artifact is None or artifact.status not in ACTIVE_SUMMARY_AUDIO_STATUSES:
        return artifact

    artifact.stage = "saving_audio"
    artifact.progress_percent = 90
    text = await _current_text_for_artifact(db, artifact)
    if not text or summary_audio_hash(text) != artifact.summary_hash:
        mark_summary_audio_failed(
            artifact,
            error_code="stale_summary",
            error_message="Summary changed while audio generation was running.",
        )
        return artifact

    storage_path = write_summary_audio_file(
        artifact=artifact,
        audio_bytes=result.audio_bytes,
        codec=get_settings().summary_audio_codec,
    )
    artifact.status = SummaryAudioStatus.SUCCEEDED.value
    artifact.stage = "complete"
    artifact.progress_percent = 100
    artifact.content_type = result.content_type
    artifact.storage_path = storage_path
    artifact.byte_size = len(result.audio_bytes)
    artifact.error_code = None
    artifact.error_message = None
    artifact.completed_at = datetime.now(timezone.utc)
    artifact.failed_at = None
    await record_ai_usage_event(
        db,
        provider=artifact.provider,
        feature=FEATURE_SUMMARY_AUDIO,
        operation="tts.batch",
        status=STATUS_SUCCEEDED,
        user_id=artifact.user_id,
        recording_id=artifact.recording_id,
        item_id=artifact.item_id,
        model=artifact.model,
        audio_bytes=artifact.byte_size,
        latency_ms=result.latency_ms,
        estimated_cost_usd=round(artifact.input_char_count * 15.0 / 1_000_000, 8),
        pricing_status="priced",
        provider_status_code=result.provider_status_code,
        request_id=result.request_id,
        task_id=artifact.task_id,
        details={
            "input_char_count": artifact.input_char_count,
            "voice_id": artifact.voice_id,
            "language": artifact.language,
            "codec": get_settings().summary_audio_codec,
            "sample_rate": get_settings().summary_audio_output_sample_rate,
            "bit_rate": get_settings().summary_audio_output_bit_rate,
        },
    )
    await db.flush()
    return artifact


async def fail_summary_audio_generation_job(
    db: AsyncSession,
    *,
    artifact_id: UUID,
    error_code: str,
    error_message: str,
) -> SummaryAudioArtifact | None:
    artifact = await _load_artifact_for_update(db, artifact_id)
    if artifact is None:
        return None
    if artifact.status not in ACTIVE_SUMMARY_AUDIO_STATUSES:
        return artifact
    mark_summary_audio_failed(artifact, error_code=error_code, error_message=error_message)
    await db.flush()
    return artifact


def mark_summary_audio_failed(
    artifact: SummaryAudioArtifact,
    *,
    error_code: str,
    error_message: str,
) -> None:
    artifact.status = SummaryAudioStatus.FAILED.value
    artifact.stage = "failed"
    artifact.progress_percent = 100
    artifact.error_code = error_code
    artifact.error_message = error_message
    artifact.failed_at = datetime.now(timezone.utc)


def write_summary_audio_file(
    *,
    artifact: SummaryAudioArtifact,
    audio_bytes: bytes,
    codec: str,
) -> str:
    root = Path(get_settings().summary_audio_storage_dir)
    relative = Path(str(artifact.user_id)) / f"{artifact.id}.{codec}"
    final_path = root / relative
    final_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = final_path.with_suffix(f".{codec}.part")
    try:
        temp_path.write_bytes(audio_bytes)
        os.replace(temp_path, final_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return relative.as_posix()


def resolve_summary_audio_file_path(artifact: SummaryAudioArtifact) -> Path:
    if not artifact.storage_path:
        raise SummaryAudioError(
            code="summary_audio_file_missing",
            message="Summary audio file is missing.",
            status_code=404,
        )
    root = Path(get_settings().summary_audio_storage_dir).resolve()
    relative = Path(artifact.storage_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise SummaryAudioError(
            code="summary_audio_file_path_invalid",
            message="Summary audio file path is invalid.",
            status_code=500,
        )
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise SummaryAudioError(
            code="summary_audio_file_path_invalid",
            message="Summary audio file path is invalid.",
            status_code=500,
        )
    return path


def summary_audio_source_id(artifact: SummaryAudioArtifact) -> UUID:
    if artifact.source_kind == SUMMARY_AUDIO_SOURCE_RECORDING and artifact.recording_id:
        return artifact.recording_id
    if artifact.source_kind == SUMMARY_AUDIO_SOURCE_ITEM and artifact.item_id:
        return artifact.item_id
    raise SummaryAudioError(
        code="summary_audio_source_invalid",
        message="Summary audio source is invalid.",
        status_code=500,
    )


def _source_artifact_query(source_kind: str, source_id: UUID, user_id: UUID):
    statement = select(SummaryAudioArtifact).where(
        SummaryAudioArtifact.source_kind == source_kind,
        SummaryAudioArtifact.user_id == user_id,
    )
    if source_kind == SUMMARY_AUDIO_SOURCE_RECORDING:
        return statement.where(SummaryAudioArtifact.recording_id == source_id)
    if source_kind == SUMMARY_AUDIO_SOURCE_ITEM:
        return statement.where(SummaryAudioArtifact.item_id == source_id)
    raise SummaryAudioError(
        code="summary_audio_source_invalid",
        message="Summary audio source is invalid.",
        status_code=500,
    )


async def _load_source_text_for_update(
    db: AsyncSession,
    *,
    source_kind: str,
    source_id: UUID,
    user_id: UUID,
) -> tuple[str, UUID | None]:
    if source_kind == SUMMARY_AUDIO_SOURCE_RECORDING:
        result = await db.execute(
            select(Recording)
            .where(Recording.id == source_id, Recording.user_id == user_id)
            .options(
                selectinload(Recording.summary),
                selectinload(Recording.segments).selectinload(Segment.person),
            )
            .with_for_update()
        )
        recording = result.scalar_one_or_none()
        if recording is None or recording.deleted_at is not None:
            return "", None
        return build_recording_summary_audio_text(recording), recording.user_id

    if source_kind == SUMMARY_AUDIO_SOURCE_ITEM:
        result = await db.execute(
            select(Item)
            .where(Item.id == source_id, Item.user_id == user_id)
            .options(selectinload(Item.summary))
            .with_for_update()
        )
        item = result.scalar_one_or_none()
        if item is None or item.deleted_at is not None:
            return "", None
        return build_item_summary_audio_text(item.summary), item.user_id

    raise SummaryAudioError(
        code="summary_audio_source_invalid",
        message="Summary audio source is invalid.",
        status_code=500,
    )


async def _current_text_for_artifact(
    db: AsyncSession,
    artifact: SummaryAudioArtifact,
) -> str:
    if artifact.source_kind == SUMMARY_AUDIO_SOURCE_RECORDING and artifact.recording_id:
        result = await db.execute(
            select(Recording)
            .where(Recording.id == artifact.recording_id, Recording.user_id == artifact.user_id)
            .options(
                selectinload(Recording.summary),
                selectinload(Recording.segments).selectinload(Segment.person),
            )
        )
        recording = result.scalar_one_or_none()
        return build_recording_summary_audio_text(recording) if recording else ""

    if artifact.source_kind == SUMMARY_AUDIO_SOURCE_ITEM and artifact.item_id:
        result = await db.execute(
            select(Item)
            .where(Item.id == artifact.item_id, Item.user_id == artifact.user_id)
            .options(selectinload(Item.summary))
        )
        item = result.scalar_one_or_none()
        return build_item_summary_audio_text(item.summary) if item else ""

    return ""


async def _load_artifact_for_update(
    db: AsyncSession,
    artifact_id: UUID,
) -> SummaryAudioArtifact | None:
    result = await db.execute(
        select(SummaryAudioArtifact)
        .where(SummaryAudioArtifact.id == artifact_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def _enforce_daily_caps(
    db: AsyncSession,
    *,
    user_id: UUID,
    input_char_count: int,
) -> None:
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    if settings.summary_audio_user_daily_chars_cap > 0:
        user_total = await _daily_char_total(db, cutoff=cutoff, user_id=user_id)
        if user_total + input_char_count > settings.summary_audio_user_daily_chars_cap:
            raise SummaryAudioError(
                code="summary_audio_user_daily_cap_exceeded",
                message="Summary audio daily limit reached.",
                status_code=429,
            )
    if settings.summary_audio_global_daily_chars_cap > 0:
        global_total = await _daily_char_total(db, cutoff=cutoff, user_id=None)
        if global_total + input_char_count > settings.summary_audio_global_daily_chars_cap:
            raise SummaryAudioError(
                code="summary_audio_global_daily_cap_exceeded",
                message="Summary audio is temporarily rate limited.",
                status_code=429,
            )


async def _daily_char_total(
    db: AsyncSession,
    *,
    cutoff: datetime,
    user_id: UUID | None,
) -> int:
    statement = select(func.coalesce(func.sum(SummaryAudioArtifact.input_char_count), 0)).where(
        SummaryAudioArtifact.requested_at >= cutoff,
        SummaryAudioArtifact.status != SummaryAudioStatus.FAILED.value,
    )
    if user_id is not None:
        statement = statement.where(SummaryAudioArtifact.user_id == user_id)
    result = await db.execute(statement)
    return int(result.scalar_one() or 0)


def _join_spoken_summary(values: list[str | None]) -> str:
    lines = [str(value).strip() for value in values if value and str(value).strip()]
    return "\n".join(lines).strip()


def _json_lines(
    value: Any,
    *,
    preferred_keys: tuple[str, ...] = ("decision", "task", "title", "summary", "moment"),
) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [_json_line(item, preferred_keys=preferred_keys) for item in value if item]
    return [_json_line(value, preferred_keys=preferred_keys)]


def _json_line(value: Any, *, preferred_keys: tuple[str, ...]) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = [str(value[key]).strip() for key in preferred_keys if value.get(key)]
        if parts:
            return ". ".join(parts)
        return ". ".join(str(item).strip() for item in value.values() if item)
    return str(value)


def _assigned_speaker_names(recording: Recording) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for segment in recording.segments:
        raw = (segment.speaker or segment.raw_label or "").strip()
        if raw and raw not in mapping and segment.person and segment.person.display_name:
            mapping[raw] = segment.person.display_name
    return mapping


def _apply_speaker_names(text: str | None, names: dict[str, str]) -> str | None:
    if not text or not names:
        return text
    for raw in sorted(names, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(raw)}\b", names[raw], text)
    return text
