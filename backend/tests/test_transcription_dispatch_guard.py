"""The batch dispatcher (transcribe_audio_file) is the single choke point for the
Deepgram cost/abuse guards. These verify each guard fires there and that the
breaker + minute metering are fed around the provider call.

The autouse conftest fixture backs the guard with a fresh fakeredis per test.
"""

from datetime import datetime, timezone

import httpx
import pytest

from app.config import get_settings
from app.core import transcription as dispatcher
from app.core import transcription_guard as guard
from app.core.transcription_guard import TranscriptionGuardError


@pytest.fixture
def settings():
    return get_settings()


async def test_dispatch_blocks_when_halted(settings):
    await guard.get_redis().set("dg:killswitch", "1")
    with pytest.raises(TranscriptionGuardError) as ei:
        await dispatcher.transcribe_audio_file(b"x", user_id="u1", audio_duration_seconds=10)
    assert ei.value.code == "transcription_halted"


async def test_dispatch_blocks_when_breaker_open(settings):
    await guard.record_provider_result(success=False, status_code=402)  # opens breaker
    with pytest.raises(TranscriptionGuardError) as ei:
        await dispatcher.transcribe_audio_file(b"x", user_id="u1", audio_duration_seconds=10)
    assert ei.value.code == "provider_unavailable"


async def test_dispatch_rejects_over_max_duration(settings, monkeypatch):
    monkeypatch.setattr(settings, "recording_max_audio_seconds", 60)
    with pytest.raises(TranscriptionGuardError) as ei:
        await dispatcher.transcribe_audio_file(b"x", user_id="u1", audio_duration_seconds=120)
    assert ei.value.code == "recording_too_long"


async def test_dispatch_rejects_over_minute_budget(settings, monkeypatch):
    monkeypatch.setattr(settings, "transcription_abuse_caps_enabled", True)
    monkeypatch.setattr(settings, "deepgram_global_daily_minutes_cap", 1)
    monkeypatch.setattr(settings, "deepgram_user_daily_minutes_cap", 0)
    with pytest.raises(TranscriptionGuardError) as ei:
        await dispatcher.transcribe_audio_file(b"x", user_id="u1", audio_duration_seconds=120)
    assert ei.value.code == "global_minutes"


async def test_dispatch_success_records_minutes_and_keeps_breaker_closed(settings, monkeypatch):
    async def _fake(*_a, **_k):
        return []

    monkeypatch.setattr(dispatcher, "elevenlabs_transcribe_audio_file", _fake)
    await dispatcher.transcribe_audio_file(b"x", user_id="u1", audio_duration_seconds=60)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    used_global = await guard.get_redis().get(f"dg:min:global:{today}")
    used_user = await guard.get_redis().get(f"dg:min:user:u1:{today}")
    assert float(used_global) == pytest.approx(1.0, abs=0.01)
    assert float(used_user) == pytest.approx(1.0, abs=0.01)
    assert await guard.provider_breaker_open() is False


async def test_dispatch_402_opens_breaker_and_reraises(settings, monkeypatch):
    monkeypatch.setattr(settings, "deepgram_breaker_failure_threshold", 5)
    request = httpx.Request("POST", "https://api.deepgram.com/v1/listen")
    response = httpx.Response(402, request=request)

    async def _fake(*_a, **_k):
        raise httpx.HTTPStatusError("budget exceeded", request=request, response=response)

    monkeypatch.setattr(dispatcher, "elevenlabs_transcribe_audio_file", _fake)
    with pytest.raises(httpx.HTTPStatusError):
        await dispatcher.transcribe_audio_file(b"x", user_id="u1", audio_duration_seconds=10)
    assert await guard.provider_breaker_open() is True
