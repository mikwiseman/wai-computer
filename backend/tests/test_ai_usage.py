"""Unified AI usage ledger tests."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai_usage import (
    CEREBRAS_PROVIDER,
    DEEPGRAM_PROVIDER,
    FEATURE_SEARCH,
    OPENAI_PROVIDER,
    STATUS_SUCCEEDED,
    estimate_cost_usd,
    estimate_deepgram_usage_cost,
    record_ai_usage_event,
    usage_from_response,
)
from app.models.ai_usage import AiUsageEvent


def test_usage_from_response_reads_openai_token_breakdowns() -> None:
    response = {
        "id": "resp_test",
        "model": "text-embedding-3-large",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "input_tokens_details": {"cached_tokens": 40},
            "output_tokens_details": {"reasoning_tokens": 5},
        },
    }

    usage = usage_from_response(response)

    assert usage == {
        "input_tokens": 100,
        "output_tokens": 20,
        "cached_tokens": 40,
        "reasoning_tokens": 5,
        "total_tokens": 120,
    }


def test_usage_from_response_reads_chat_completions_token_breakdowns() -> None:
    response = {
        "id": "chatcmpl_test",
        "model": "gpt-oss-120b",
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_tokens_details": {"cached_tokens": 40},
            "completion_tokens_details": {"reasoning_tokens": 5},
        },
    }

    usage = usage_from_response(response)

    assert usage == {
        "input_tokens": 100,
        "output_tokens": 20,
        "cached_tokens": 40,
        "reasoning_tokens": 5,
        "total_tokens": 120,
    }


def test_estimate_cost_prices_known_models_and_marks_unknown_models_unpriced() -> None:
    assert estimate_cost_usd(
        provider=OPENAI_PROVIDER,
        model="text-embedding-3-large",
        input_tokens=1_000,
    ) == (0.00013, "priced")
    assert estimate_cost_usd(
        provider=OPENAI_PROVIDER,
        model="gpt-5.5",
        input_tokens=1_000_000,
        cached_tokens=100_000,
        output_tokens=10_000,
    ) == (4.85, "priced")
    assert estimate_cost_usd(
        provider=OPENAI_PROVIDER,
        model="gpt-5.5-2026-04-23",
        input_tokens=1_000_000,
        cached_tokens=100_000,
        output_tokens=10_000,
    ) == (4.85, "priced")
    assert estimate_cost_usd(
        provider=DEEPGRAM_PROVIDER,
        model="nova-3",
        billable_seconds=60,
    ) == (0.0058, "priced")
    assert estimate_cost_usd(
        provider=CEREBRAS_PROVIDER,
        model="gpt-oss-120b",
        input_tokens=1_000_000,
        output_tokens=10_000,
    ) == (0.2569, "priced")
    assert estimate_cost_usd(
        provider=OPENAI_PROVIDER,
        model="gpt-unknown",
        input_tokens=1_000,
    ) == (None, "unpriced")


def test_estimate_deepgram_usage_cost_prices_mode_and_addons() -> None:
    cost = estimate_deepgram_usage_cost(
        model="nova-3",
        billable_seconds=60,
        billing_mode="pre_recorded",
        language_mode="multilingual",
        addons=["speaker_diarization", "keyterm_prompting"],
    )

    assert cost.amount_usd == 0.0125
    assert cost.pricing_status == "priced"
    assert cost.price_source == "deepgram-payg-2026-06-04"
    assert cost.addons == ["keyterm_prompting", "speaker_diarization"]


@pytest.mark.asyncio
async def test_record_ai_usage_event_persists_metadata_without_content(
    db_session: AsyncSession,
) -> None:
    await record_ai_usage_event(
        db_session,
        provider=OPENAI_PROVIDER,
        feature=FEATURE_SEARCH,
        operation="embedding.query",
        status=STATUS_SUCCEEDED,
        model="text-embedding-3-large",
        response={
            "id": "resp_ledger",
            "usage": {"input_tokens": 2_000, "total_tokens": 2_000},
        },
        latency_ms=37,
        details={
            "input_count": 1,
            "dimensions": 3_072,
            "prompt": "private prompt must not be stored",
        },
        commit=True,
    )

    event = (await db_session.execute(select(AiUsageEvent))).scalar_one()
    assert event.provider == "openai"
    assert event.feature == "search"
    assert event.operation == "embedding.query"
    assert event.total_tokens == 2_000
    assert event.input_tokens == 2_000
    assert event.estimated_cost_usd == 0.00026
    assert event.pricing_status == "priced"
    assert event.request_id == "resp_ledger"
    assert event.details == {"input_count": 1, "dimensions": 3072}
