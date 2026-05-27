"""Tests for the active transcription runtime."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_transcription_dispatches_to_elevenlabs():
    with (
        patch(
            "app.core.transcription.elevenlabs_transcribe_audio_file",
            new=AsyncMock(return_value=["ok"]),
        ) as mock_elevenlabs,
    ):
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(b"audio", language="ru", content_type="audio/mp3")

    assert result == ["ok"]
    mock_elevenlabs.assert_awaited_once_with(
        b"audio",
        language="ru",
        content_type="audio/mp3",
        channels=None,
        model="scribe_v2",
    )


@pytest.mark.asyncio
async def test_transcription_ignores_deepgram_user_choice():
    user = type(
        "User",
        (),
        {"file_stt_provider": "deepgram", "file_stt_model": "nova-3"},
    )()
    with patch(
        "app.core.transcription.elevenlabs_transcribe_audio_file",
        new=AsyncMock(return_value=["elevenlabs-ok"]),
    ) as mock_elevenlabs:
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(
            b"audio",
            language="en",
            content_type="audio/wav",
            channels=1,
            user=user,
        )

    assert result == ["elevenlabs-ok"]
    mock_elevenlabs.assert_awaited_once_with(
        b"audio",
        language="en",
        content_type="audio/wav",
        channels=1,
        model="scribe_v2",
    )


@pytest.mark.asyncio
async def test_transcription_ignores_soniox_user_choice():
    user = type(
        "User",
        (),
        {"file_stt_provider": "soniox", "file_stt_model": "stt-async-v4"},
    )()
    with patch(
        "app.core.transcription.elevenlabs_transcribe_audio_file",
        new=AsyncMock(return_value=["elevenlabs-ok"]),
    ) as mock_elevenlabs:
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(
            b"audio",
            language="en",
            content_type="audio/wav",
            channels=1,
            user=user,
        )

    assert result == ["elevenlabs-ok"]
    mock_elevenlabs.assert_awaited_once_with(
        b"audio",
        language="en",
        content_type="audio/wav",
        channels=1,
        model="scribe_v2",
    )


@pytest.mark.asyncio
async def test_transcription_rejects_explicit_soniox_file_stt():
    from app.core.transcription import transcribe_audio_file

    with pytest.raises(ValueError, match="Unsupported file_stt option"):
        await transcribe_audio_file(
            b"webm-data",
            language="en",
            content_type="audio/webm",
            provider="soniox",
            model="stt-async-v4",
        )


@pytest.mark.asyncio
async def test_transcription_rejects_explicit_deepgram_file_stt():
    from app.core.transcription import transcribe_audio_file

    with pytest.raises(ValueError, match="Unsupported file_stt option"):
        await transcribe_audio_file(
            b"audio",
            language="en",
            content_type="audio/wav",
            provider="deepgram",
            model="nova-3",
        )


@pytest.mark.asyncio
async def test_transcription_ignores_dropped_openai_user_choice():
    """User-persisted file STT choices no longer select the runtime model."""
    user = type(
        "User",
        (),
        {"file_stt_provider": "openai", "file_stt_model": "retired-batch-stt"},
    )()
    with patch(
        "app.core.transcription.elevenlabs_transcribe_audio_file",
        new=AsyncMock(return_value=["elevenlabs-ok"]),
    ):
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(b"audio", user=user)

    assert result == ["elevenlabs-ok"]


@pytest.mark.asyncio
async def test_transcription_ignores_unsupported_user_choice():
    user = type("User", (), {"file_stt_provider": "elevenlabs", "file_stt_model": "bad-model"})()
    with patch(
        "app.core.transcription.elevenlabs_transcribe_audio_file",
        new=AsyncMock(return_value=["elevenlabs-ok"]),
    ):
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(b"audio", user=user)

    assert result == ["elevenlabs-ok"]


@pytest.mark.asyncio
async def test_transcription_surfaces_elevenlabs_payment_issue_without_provider_fallback():
    response = httpx.Response(
        401,
        json={
            "detail": {
                "type": "payment_required",
                "code": "payment_issue",
                "message": "Complete the latest invoice to continue usage.",
            }
        },
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )
    error = httpx.HTTPStatusError(
        "Client error '401 Unauthorized'",
        request=response.request,
        response=response,
    )

    with patch(
        "app.core.transcription.elevenlabs_transcribe_audio_file",
        new=AsyncMock(side_effect=error),
    ):
        from app.core.transcription import transcribe_audio_file

        with pytest.raises(httpx.HTTPStatusError):
            await transcribe_audio_file(
                b"wav",
                language="auto",
                content_type="audio/wav",
                channels=1,
            )


@pytest.mark.asyncio
async def test_transcription_logs_provider_latency_without_audio_or_error_body(caplog):
    from app.core.transcript_utils import TranscriptResult

    with patch(
        "app.core.transcription.elevenlabs_transcribe_audio_file",
        new=AsyncMock(
            return_value=[
                TranscriptResult(
                    text="private transcript must not be logged",
                    speaker=None,
                    is_final=True,
                    start_ms=0,
                    end_ms=1000,
                    confidence=0.9,
                )
            ]
        ),
    ):
        from app.core.transcription import transcribe_audio_file

        caplog.set_level("INFO", logger="app.core.transcription")
        await transcribe_audio_file(b"secret-audio-bytes", language="ru", content_type="audio/wav")

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "file STT completed" in messages
    assert "provider=elevenlabs" in messages
    assert "segment_count=1" in messages
    assert "private transcript" not in messages
    assert "secret-audio-bytes" not in messages


@pytest.mark.asyncio
async def test_transcription_captures_slow_file_stt_without_audio_or_transcript(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.core import transcription
    from app.core.transcript_utils import TranscriptResult

    sentry_messages: list[dict[str, object]] = []
    sentry_breadcrumbs: list[dict[str, object]] = []
    tick = iter([0.0, 121.0])
    monkeypatch.setattr(transcription, "perf_counter", lambda: next(tick))
    monkeypatch.setattr(
        transcription,
        "capture_sentry_anomaly",
        lambda alert_code, message, *, category, extras, level="warning": sentry_messages.append(
            {
                "alert_code": alert_code,
                "message": message,
                "category": category,
                "extras": extras,
                "level": level,
            }
        ),
    )
    monkeypatch.setattr(
        transcription,
        "add_sentry_breadcrumb",
        lambda **kwargs: sentry_breadcrumbs.append(kwargs),
    )
    monkeypatch.setattr(
        transcription,
        "elevenlabs_transcribe_audio_file",
        AsyncMock(
            return_value=[
                TranscriptResult(
                    text="private transcript must stay out of Sentry",
                    speaker=None,
                    is_final=True,
                    start_ms=0,
                    end_ms=1000,
                    confidence=0.9,
                )
            ]
        ),
    )

    result = await transcription.transcribe_audio_file(
        b"secret-audio-bytes",
        language="ru",
        content_type="audio/wav",
        audio_duration_seconds=30,
    )

    assert len(result) == 1
    assert sentry_messages == [
        {
            "alert_code": "recording.file_stt.slow",
            "message": "File transcription latency exceeded threshold",
            "category": "recording",
            "extras": {
                "provider": "elevenlabs",
                "model": "scribe_v2",
                "latency_ms": 121_000,
                "slow_threshold_ms": 120_000,
                "audio_duration_seconds": 30,
                "latency_per_audio_second": round(121 / 30, 4),
                "audio_bytes": len(b"secret-audio-bytes"),
                "content_type": "audio/wav",
                "channels": None,
                "segment_count": 1,
            },
            "level": "warning",
        }
    ]
    assert any(
        item.get("message") == "File transcription completed"
        for item in sentry_breadcrumbs
    )
    assert "private transcript" not in repr(sentry_messages)
    assert "secret-audio-bytes" not in repr(sentry_messages)


@pytest.mark.asyncio
async def test_transcription_does_not_fallback_for_elevenlabs_bad_request():
    response = httpx.Response(
        400,
        json={"detail": {"message": "Invalid language_code"}},
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )
    error = httpx.HTTPStatusError(
        "Client error '400 Bad Request'",
        request=response.request,
        response=response,
    )

    with patch(
        "app.core.transcription.elevenlabs_transcribe_audio_file",
        new=AsyncMock(side_effect=error),
    ):
        from app.core.transcription import transcribe_audio_file

        with pytest.raises(httpx.HTTPStatusError):
            await transcribe_audio_file(b"wav", language="auto", content_type="audio/wav")


def test_elevenlabs_error_code_handles_unstructured_error_payloads():
    from app.core.transcription import _elevenlabs_error_code

    invalid_json_response = httpx.Response(
        503,
        content=b"not-json",
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )
    invalid_json_error = httpx.HTTPStatusError(
        "Service unavailable",
        request=invalid_json_response.request,
        response=invalid_json_response,
    )
    assert _elevenlabs_error_code(invalid_json_error) is None

    list_response = httpx.Response(
        401,
        json=["bad"],
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )
    list_error = httpx.HTTPStatusError(
        "Unauthorized",
        request=list_response.request,
        response=list_response,
    )
    assert _elevenlabs_error_code(list_error) is None

    detail_response = httpx.Response(
        402,
        json={"detail": {"status": "payment_issue"}},
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )
    detail_error = httpx.HTTPStatusError(
        "Payment required",
        request=detail_response.request,
        response=detail_response,
    )
    assert _elevenlabs_error_code(detail_error) == "payment_issue"


@pytest.mark.asyncio
async def test_transcription_rejects_provider_left_after_validation(monkeypatch):
    monkeypatch.setattr(
        "app.core.transcription.validate_option",
        lambda _kind, _provider, _model: ("bogus", "model"),
    )
    from app.core.transcription import transcribe_audio_file

    with pytest.raises(ValueError, match="Unsupported file_stt_provider: bogus"):
        await transcribe_audio_file(b"audio", provider="elevenlabs", model="scribe_v2")
