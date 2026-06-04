"""Deepgram usage ledger regression tests."""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deepgram_usage import (
    record_deepgram_usage_event,
    record_deepgram_usage_event_standalone,
)
from app.models.ai_usage import AiUsageEvent
from app.models.deepgram_usage import DeepgramUsageEvent


@pytest.mark.asyncio
async def test_record_deepgram_usage_event_prices_addons_in_both_ledgers(
    db_session: AsyncSession,
) -> None:
    await record_deepgram_usage_event(
        db_session,
        operation="file_stt",
        purpose="recording",
        status="succeeded",
        model="nova-3",
        language="ru",
        content_type="audio/mp4",
        audio_seconds=60,
        billable_seconds=60,
        channel_count=1,
        billing_mode="pre_recorded",
        language_mode="multilingual",
        addons=["speaker_diarization", "keyterm_prompting"],
        request_id="dg-request-1",
        task_id="celery-task-1",
        commit=True,
    )

    deepgram_event = (await db_session.execute(select(DeepgramUsageEvent))).scalar_one()
    assert deepgram_event.billing_mode == "pre_recorded"
    assert deepgram_event.language_mode == "multilingual"
    assert deepgram_event.addons == ["keyterm_prompting", "speaker_diarization"]
    assert deepgram_event.estimated_cost_usd == 0.0125
    assert deepgram_event.pricing_status == "priced"
    assert deepgram_event.price_source == "deepgram-payg-2026-06-04"
    assert deepgram_event.request_id == "dg-request-1"
    assert deepgram_event.task_id == "celery-task-1"

    ai_event = (await db_session.execute(select(AiUsageEvent))).scalar_one()
    assert ai_event.provider == "deepgram"
    assert ai_event.billing_mode == "pre_recorded"
    assert ai_event.language_mode == "multilingual"
    assert ai_event.addons == ["keyterm_prompting", "speaker_diarization"]
    assert ai_event.estimated_cost_usd == 0.0125
    assert ai_event.pricing_status == "priced"
    assert ai_event.price_source == "deepgram-payg-2026-06-04"
    assert ai_event.request_id == "dg-request-1"
    assert ai_event.task_id == "celery-task-1"


@pytest.mark.asyncio
async def test_record_deepgram_usage_event_standalone_drops_context_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail_context():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.core.deepgram_usage.get_db_context", fail_context)

    with caplog.at_level(logging.WARNING):
        await record_deepgram_usage_event_standalone(
            operation="realtime_stream",
            purpose="dictation",
            status="failed",
            model="nova-3",
            audio_seconds=10,
            billable_seconds=10,
        )

    assert "standalone deepgram usage event dropped" in caplog.text
