"""Shared API helpers for generated summary audio."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.summary_audio import SummaryAudioError, resolve_summary_audio_file_path
from app.models.summary_audio import SummaryAudioArtifact, SummaryAudioStatus


class SummaryAudioResponse(BaseModel):
    artifact_id: str | None
    source_kind: str
    source_id: str
    status: str
    stage: str
    progress_percent: int
    message: str
    provider: str | None
    model: str | None
    voice_id: str | None
    language: str | None
    content_type: str | None
    byte_size: int | None
    duration_seconds: int | None
    audio_url: str | None
    requested_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    error_code: str | None
    error_message: str | None


def serialize_summary_audio(
    *,
    source_kind: str,
    source_id: UUID,
    artifact: SummaryAudioArtifact | None,
    audio_url: str,
) -> SummaryAudioResponse:
    if artifact is None:
        return SummaryAudioResponse(
            artifact_id=None,
            source_kind=source_kind,
            source_id=str(source_id),
            status="not_started",
            stage="idle",
            progress_percent=0,
            message="Summary audio has not been created.",
            provider=None,
            model=None,
            voice_id=None,
            language=None,
            content_type=None,
            byte_size=None,
            duration_seconds=None,
            audio_url=None,
            requested_at=None,
            started_at=None,
            completed_at=None,
            failed_at=None,
            error_code=None,
            error_message=None,
        )

    return SummaryAudioResponse(
        artifact_id=str(artifact.id),
        source_kind=artifact.source_kind,
        source_id=str(source_id),
        status=artifact.status,
        stage=artifact.stage,
        progress_percent=artifact.progress_percent,
        message=_summary_audio_message(artifact.status, artifact.stage),
        provider=artifact.provider,
        model=artifact.model,
        voice_id=artifact.voice_id,
        language=artifact.language,
        content_type=artifact.content_type,
        byte_size=artifact.byte_size,
        duration_seconds=artifact.duration_seconds,
        audio_url=audio_url if artifact.status == SummaryAudioStatus.SUCCEEDED.value else None,
        requested_at=artifact.requested_at,
        started_at=artifact.started_at,
        completed_at=artifact.completed_at,
        failed_at=artifact.failed_at,
        error_code=artifact.error_code,
        error_message=artifact.error_message,
    )


def summary_audio_file_response(
    *,
    artifact: SummaryAudioArtifact,
    request: Request,
) -> Response:
    if artifact.status != SummaryAudioStatus.SUCCEEDED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Summary audio is not ready.",
        )
    try:
        path = resolve_summary_audio_file_path(artifact)
    except SummaryAudioError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Summary audio file is missing.",
        )

    content_type = artifact.content_type or "audio/mpeg"
    size = path.stat().st_size
    range_header = request.headers.get("range")
    if range_header:
        start, end = _parse_range_header(range_header, size)
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(end - start + 1),
        }
        return StreamingResponse(
            _file_iterator(path, start=start, end=end),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=content_type,
            headers=headers,
        )

    return StreamingResponse(
        _file_iterator(path, start=0, end=size - 1),
        media_type=content_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(size),
        },
    )


def _summary_audio_message(status_value: str, stage: str) -> str:
    if status_value == "not_started":
        return "Summary audio has not been created."
    if status_value == SummaryAudioStatus.QUEUED.value:
        return "Summary audio generation is queued."
    if status_value == SummaryAudioStatus.RUNNING.value:
        if stage == "preparing_summary":
            return "Preparing summary for audio generation."
        if stage == "saving_audio":
            return "Saving generated audio."
        return "Generating summary audio."
    if status_value == SummaryAudioStatus.SUCCEEDED.value:
        return "Summary audio is ready."
    if status_value == SummaryAudioStatus.FAILED.value:
        return "Summary audio generation failed."
    return "Summary audio status is unknown."


def _parse_range_header(value: str, size: int) -> tuple[int, int]:
    if not value.startswith("bytes="):
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="Invalid range.",
            headers={"Content-Range": f"bytes */{size}"},
        )
    raw = value.removeprefix("bytes=").split(",", 1)[0].strip()
    start_raw, _, end_raw = raw.partition("-")
    try:
        if start_raw:
            start = int(start_raw)
            end = int(end_raw) if end_raw else size - 1
        else:
            suffix_length = int(end_raw)
            if suffix_length <= 0:
                raise ValueError
            start = max(size - suffix_length, 0)
            end = size - 1
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="Invalid range.",
            headers={"Content-Range": f"bytes */{size}"},
        ) from exc

    if start < 0 or end < start or start >= size:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="Range not satisfiable.",
            headers={"Content-Range": f"bytes */{size}"},
        )
    return start, min(end, size - 1)


def _file_iterator(path: Path, *, start: int, end: int, chunk_size: int = 1024 * 1024):
    with path.open("rb") as file:
        file.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = file.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
