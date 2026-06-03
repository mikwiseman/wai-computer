"""Tests for Deepgram usage ledger helpers."""

import httpx

from app.core.deepgram_usage import (
    effective_billable_seconds,
    provider_error_code,
    sanitize_deepgram_tags,
)


def test_sanitize_deepgram_tags_dedupes_normalizes_and_drops_empty_values():
    assert sanitize_deepgram_tags(
        [
            " Purpose:Recording ",
            "",
            "Purpose:Recording",
            "Operation:File STT",
        ]
    ) == ["purpose:recording", "operation:file-stt"]


def test_provider_error_code_reads_top_level_provider_payloads():
    request = httpx.Request("POST", "https://api.deepgram.com/v1/listen")
    response = httpx.Response(
        402,
        json={"code": "ASR_PAYMENT_REQUIRED"},
        request=request,
    )
    error = httpx.HTTPStatusError("payment required", request=request, response=response)

    assert provider_error_code(error) == "ASR_PAYMENT_REQUIRED"


def test_effective_billable_seconds_handles_refused_and_multichannel_audio():
    assert effective_billable_seconds(audio_seconds=60, provider_opened=False) == 0.0
    assert effective_billable_seconds(audio_seconds=12.5, channel_count=2) == 25.0
    assert effective_billable_seconds(audio_seconds=None) is None
