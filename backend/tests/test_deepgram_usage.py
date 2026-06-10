"""Deepgram usage ledger regression tests."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deepgram_usage import (
    DEEPGRAM_TAG_APP,
    DEEPGRAM_TAG_LIMIT,
    deepgram_usage_tags,
    effective_billable_seconds,
    provider_error_code,
    record_deepgram_usage_event,
    record_deepgram_usage_event_standalone,
    sanitize_deepgram_tags,
)
from app.models.ai_usage import AiUsageEvent
from app.models.deepgram_usage import DeepgramUsageEvent


def _provider_error(status_code: int, **response_kwargs) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.deepgram.com/v1/listen")
    response = httpx.Response(status_code, request=request, **response_kwargs)
    return httpx.HTTPStatusError("provider error", request=request, response=response)


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


def test_deepgram_usage_tags_marks_dev_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.deepgram_usage.get_settings",
        lambda: SimpleNamespace(debug=True),
    )

    assert deepgram_usage_tags(operation="File STT", purpose="Voice Sample") == [
        DEEPGRAM_TAG_APP,
        "env:dev",
        "operation:file-stt",
        "purpose:voice-sample",
    ]


def test_deepgram_usage_tags_marks_prod_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.deepgram_usage.get_settings",
        lambda: SimpleNamespace(debug=False),
    )

    tags = deepgram_usage_tags(operation="realtime_stream", purpose="dictation")
    assert "env:prod" in tags


def test_sanitize_deepgram_tags_handles_empty_input() -> None:
    assert sanitize_deepgram_tags(None) == []
    assert sanitize_deepgram_tags([]) == []


def test_sanitize_deepgram_tags_normalizes_dedupes_and_truncates() -> None:
    long_tag = "x" * (DEEPGRAM_TAG_LIMIT + 40)
    tags = sanitize_deepgram_tags(["My Tag", "my-tag", "   ", "Other", long_tag])
    assert tags == ["my-tag", "other", "x" * DEEPGRAM_TAG_LIMIT]


def test_provider_error_code_returns_none_for_invalid_json() -> None:
    assert provider_error_code(_provider_error(503, content=b"not-json")) is None


def test_provider_error_code_returns_none_for_non_dict_payload() -> None:
    assert provider_error_code(_provider_error(401, json=["unauthorized"])) is None


def test_provider_error_code_reads_nested_error_container() -> None:
    error = _provider_error(429, json={"error": {"code": "rate_limit"}})
    assert provider_error_code(error) == "rate_limit"


def test_provider_error_code_falls_back_to_top_level_keys() -> None:
    error = _provider_error(402, json={"error": {"code": "   "}, "type": " payment_required "})
    assert provider_error_code(error) == "payment_required"


def test_provider_error_code_returns_none_when_no_code_present() -> None:
    assert provider_error_code(_provider_error(500, json={"message": "kaboom"})) is None


@pytest.mark.asyncio
async def test_record_deepgram_usage_event_flushes_without_commit(
    db_session: AsyncSession,
) -> None:
    await record_deepgram_usage_event(
        db_session,
        operation="file_stt",
        purpose="voice_sample",
        status="refused",
        guard_code="weekly_word_quota",
        recording_id="not-a-uuid",
    )

    deepgram_event = (await db_session.execute(select(DeepgramUsageEvent))).scalar_one()
    assert deepgram_event.status == "refused"
    assert deepgram_event.guard_code == "weekly_word_quota"
    assert deepgram_event.recording_id is None  # unparseable ids never break logging
    assert deepgram_event.audio_seconds is None

    ai_event = (await db_session.execute(select(AiUsageEvent))).scalar_one()
    assert ai_event.feature == "transcription"  # non-product purposes fall back


@pytest.mark.asyncio
async def test_record_deepgram_usage_event_never_raises_even_when_rollback_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class ExplodingSession:
        def add(self, obj: object) -> None:
            raise RuntimeError("insert failed")

        async def rollback(self) -> None:
            raise RuntimeError("rollback failed")

    with caplog.at_level(logging.WARNING):
        await record_deepgram_usage_event(
            ExplodingSession(),  # type: ignore[arg-type]
            operation="file_stt",
            purpose="recording",
            status="failed",
            commit=True,
        )

    assert "deepgram usage event dropped" in caplog.text


@pytest.mark.asyncio
async def test_record_deepgram_usage_event_standalone_persists_event(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr("app.core.deepgram_usage.get_db_context", fake_db_context)

    await record_deepgram_usage_event_standalone(
        operation="realtime_stream",
        purpose="dictation",
        status="succeeded",
        model="nova-3",
        audio_seconds=12,
        billable_seconds=12,
    )

    event = (await db_session.execute(select(DeepgramUsageEvent))).scalar_one()
    assert event.operation == "realtime_stream"
    assert event.status == "succeeded"
    assert event.billable_seconds == 12.0


def test_effective_billable_seconds_is_zero_when_provider_never_opened() -> None:
    assert effective_billable_seconds(audio_seconds=42.5, provider_opened=False) == 0.0


def test_effective_billable_seconds_is_none_when_audio_unknown() -> None:
    assert effective_billable_seconds(audio_seconds=None) is None


def test_effective_billable_seconds_multiplies_channels() -> None:
    assert effective_billable_seconds(audio_seconds=10.5, channel_count=2) == 21.0
    assert effective_billable_seconds(audio_seconds=7, channel_count=None) == 7.0


def test_uuid_or_none_accepts_uuids_and_rejects_garbage() -> None:
    from app.core.deepgram_usage import _uuid_or_none

    value = uuid4()
    assert _uuid_or_none(None) is None
    assert _uuid_or_none(value) is value
    assert _uuid_or_none(str(value)) == value
    assert _uuid_or_none("not-a-uuid") is None


def test_float_or_none_rounds_and_rejects_unparseable_values() -> None:
    from app.core.deepgram_usage import _float_or_none

    assert _float_or_none(None) is None
    assert _float_or_none(7.23456) == 7.235
    assert _float_or_none("not-a-number") is None  # ValueError
    assert _float_or_none(object()) is None  # TypeError
