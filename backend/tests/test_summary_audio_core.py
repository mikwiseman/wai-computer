"""Core summary-audio lifecycle tests."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.summary_audio import (
    SummaryAudioError,
    build_item_summary_audio_text,
    build_recording_summary_audio_text,
    fail_summary_audio_generation_job,
    latest_summary_audio_artifact_for_hash,
    persist_summary_audio_generation_result,
    prepare_summary_audio_generation_payload,
    resolve_summary_audio_file_path,
    start_summary_audio_artifact,
    summary_audio_hash,
)
from app.core.xai_tts import XaiTTSResult
from app.models.ai_usage import AiUsageEvent
from app.models.item import Item, ItemSummary
from app.models.recording import Recording, Segment, Summary
from app.models.summary_audio import SummaryAudioArtifact, SummaryAudioStatus
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _user(db) -> User:
    user = User(email=f"summary-audio-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def _recording_with_summary(db, user: User) -> Recording:
    recording = Recording(user_id=user.id, type="note", status="ready", language="ru")
    db.add(recording)
    await db.flush()
    db.add(
        Segment(
            recording_id=recording.id,
            speaker="speaker_0",
            raw_label="speaker_0",
            content="Привет",
            start_ms=0,
        )
    )
    summary = Summary(
        recording_id=recording.id,
        summary="speaker_0 promised to ship the release.",
        key_points=["Prepare rollout"],
        decisions=[{"decision": "Ship today"}],
        topics=["release"],
        people_mentioned=["Mik"],
        sentiment="neutral",
    )
    db.add(summary)
    await db.flush()
    await db.refresh(recording, attribute_names=["summary", "segments"])
    return recording


async def _item_with_summary(db, user: User) -> Item:
    item = Item(
        user_id=user.id,
        source="paste",
        kind="note",
        title="Item",
        body="Body",
        content_hash=f"summary-audio-{uuid4().hex}",
    )
    db.add(item)
    await db.flush()
    db.add(
        ItemSummary(
            item_id=item.id,
            summary="Item summary.",
            key_points=["Point"],
            action_items=[{"task": "Follow up"}],
            topics=["topic"],
            people_mentioned=["Alice"],
            highlights=[],
            key_moments=[{"moment": "Important moment", "why_it_matters": "It matters"}],
            sentiment="neutral",
        )
    )
    await db.flush()
    await db.refresh(item, attribute_names=["summary"])
    return item


async def test_start_summary_audio_reuses_active_then_supersedes_stale(db_session) -> None:
    user = await _user(db_session)
    recording = await _recording_with_summary(db_session, user)

    first = await start_summary_audio_artifact(
        db_session, source_kind="recording", source_id=recording.id, user_id=user.id
    )
    reused = await start_summary_audio_artifact(
        db_session, source_kind="recording", source_id=recording.id, user_id=user.id
    )
    assert reused.id == first.id

    recording.summary.summary = "Updated summary."
    replacement = await start_summary_audio_artifact(
        db_session, source_kind="recording", source_id=recording.id, user_id=user.id
    )

    assert first.status == SummaryAudioStatus.FAILED.value
    assert first.error_code == "stale_summary"
    assert replacement.id != first.id
    assert replacement.status == SummaryAudioStatus.QUEUED.value


async def test_summary_audio_payload_persists_file_and_usage(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "summary_audio_storage_dir", str(tmp_path))
    user = await _user(db_session)
    item = await _item_with_summary(db_session, user)
    artifact = await start_summary_audio_artifact(
        db_session, source_kind="item", source_id=item.id, user_id=user.id
    )

    payload = await prepare_summary_audio_generation_payload(
        db_session, artifact_id=artifact.id, task_id="task-1"
    )
    assert payload is not None
    assert payload.source_kind == "item"
    assert payload.input_char_count == artifact.input_char_count

    result = XaiTTSResult(
        audio_bytes=b"ID3audio",
        content_type="audio/mpeg",
        latency_ms=42,
        provider_status_code=200,
        request_id="xai-req",
    )
    persisted = await persist_summary_audio_generation_result(
        db_session, artifact_id=artifact.id, result=result
    )

    assert persisted is not None
    assert persisted.status == SummaryAudioStatus.SUCCEEDED.value
    assert resolve_summary_audio_file_path(persisted).read_bytes() == b"ID3audio"
    event = (await db_session.execute(select(AiUsageEvent))).scalar_one()
    assert event.provider == "xai"
    assert event.feature == "summary_audio"
    assert event.details["input_char_count"] == artifact.input_char_count
    assert event.details["voice_id"] == "ara"
    assert event.estimated_cost_usd is not None


async def test_prepare_summary_audio_marks_stale_summary(db_session) -> None:
    user = await _user(db_session)
    item = await _item_with_summary(db_session, user)
    artifact = await start_summary_audio_artifact(
        db_session, source_kind="item", source_id=item.id, user_id=user.id
    )
    item.summary.summary = "Changed before worker start."

    payload = await prepare_summary_audio_generation_payload(db_session, artifact_id=artifact.id)

    assert payload is None
    assert artifact.status == SummaryAudioStatus.FAILED.value
    assert artifact.error_code == "stale_summary"


async def test_summary_audio_text_builders_and_safe_file_paths(db_session, tmp_path: Path) -> None:
    user = await _user(db_session)
    recording = await _recording_with_summary(db_session, user)
    item = await _item_with_summary(db_session, user)

    assert "speaker_0 promised" in build_recording_summary_audio_text(recording)
    assert "Important moment" in build_item_summary_audio_text(item.summary)

    artifact = SummaryAudioArtifact(
        user_id=user.id,
        item_id=item.id,
        source_kind="item",
        status=SummaryAudioStatus.QUEUED.value,
        stage="queued",
        progress_percent=5,
        summary_hash=summary_audio_hash("x"),
        input_char_count=1,
        provider="xai",
        model="xai-text-to-speech",
        voice_id="ara",
        language="auto",
        storage_path="../private.mp3",
    )
    with pytest.raises(SummaryAudioError):
        resolve_summary_audio_file_path(artifact)

    assert latest_summary_audio_artifact_for_hash([], "missing") is None
    db_session.add(artifact)
    await db_session.flush()
    await fail_summary_audio_generation_job(
        db_session,
        artifact_id=artifact.id,
        error_code="failed",
        error_message="Failed.",
    )
    assert artifact.status == SummaryAudioStatus.FAILED.value


async def test_fail_summary_audio_generation_job_keeps_succeeded_artifact_terminal(
    db_session,
) -> None:
    user = await _user(db_session)
    item = await _item_with_summary(db_session, user)
    artifact = SummaryAudioArtifact(
        user_id=user.id,
        item_id=item.id,
        source_kind="item",
        status=SummaryAudioStatus.SUCCEEDED.value,
        stage="complete",
        progress_percent=100,
        summary_hash=summary_audio_hash("x"),
        input_char_count=1,
        provider="xai",
        model="xai-text-to-speech",
        voice_id="ara",
        language="auto",
        storage_path=f"{user.id}/summary.mp3",
        content_type="audio/mpeg",
        byte_size=7,
    )
    db_session.add(artifact)
    await db_session.flush()

    marked = await fail_summary_audio_generation_job(
        db_session,
        artifact_id=artifact.id,
        error_code="late_timeout",
        error_message="Late timeout after the audio was already saved.",
    )

    assert marked is artifact
    assert artifact.status == SummaryAudioStatus.SUCCEEDED.value
    assert artifact.stage == "complete"
    assert artifact.progress_percent == 100
    assert artifact.error_code is None
    assert artifact.error_message is None
    assert artifact.storage_path == f"{user.id}/summary.mp3"
    assert artifact.byte_size == 7
