"""Tests for the active file transcription runtime."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

DEEPGRAM_FILE_STT_MODEL = "nova-3"


def test_provider_error_code_reads_openai_error_shape():
    from app.core.transcription import _provider_error_code

    request = httpx.Request("POST", "https://provider.example/transcribe")
    response = httpx.Response(
        400,
        json={"error": {"code": "invalid_audio"}},
        request=request,
    )
    error = httpx.HTTPStatusError("bad request", request=request, response=response)

    assert _provider_error_code(error) == "invalid_audio"


@pytest.mark.asyncio
async def test_transcription_dispatches_to_deepgram_file_stt():
    with patch(
        "app.core.transcription.deepgram_transcribe_audio_file",
        new=AsyncMock(return_value=["ok"]),
    ) as mock_deepgram:
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(b"audio", language="ru", content_type="audio/mp3")

    assert result == ["ok"]
    mock_deepgram.assert_awaited_once_with(
        b"audio",
        language="ru",
        content_type="audio/mp3",
        channels=None,
        model=DEEPGRAM_FILE_STT_MODEL,
        keyterms=None,
        max_channels=2,
    )


@pytest.mark.asyncio
async def test_transcription_ignores_removed_user_file_stt_choice():
    user = type(
        "User",
        (),
        {"file_stt_provider": "removed-provider", "file_stt_model": "removed-model"},
    )()
    with patch(
        "app.core.transcription.deepgram_transcribe_audio_file",
        new=AsyncMock(return_value=["deepgram-ok"]),
    ) as mock_deepgram:
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(
            b"audio",
            language="en",
            content_type="audio/wav",
            channels=1,
            user=user,
        )

    assert result == ["deepgram-ok"]
    mock_deepgram.assert_awaited_once_with(
        b"audio",
        language="en",
        content_type="audio/wav",
        channels=1,
        model=DEEPGRAM_FILE_STT_MODEL,
        keyterms=None,
        max_channels=2,
    )


@pytest.mark.asyncio
async def test_transcription_accepts_explicit_deepgram_file_stt():
    with patch(
        "app.core.transcription.deepgram_transcribe_audio_file",
        new=AsyncMock(return_value=["ok"]),
    ) as mock_deepgram:
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(
            b"audio",
            language="en",
            content_type="audio/wav",
            provider="deepgram",
            model="nova-3",
        )

    assert result == ["ok"]
    mock_deepgram.assert_awaited_once()


@pytest.mark.asyncio
async def test_transcription_rejects_explicit_elevenlabs_file_stt():
    from app.core.transcription import transcribe_audio_file

    with pytest.raises(ValueError, match="Unsupported file_stt option"):
        await transcribe_audio_file(
            b"audio",
            language="en",
            content_type="audio/wav",
            provider="elevenlabs",
            model="scribe_v2",
        )


@pytest.mark.asyncio
async def test_transcription_rejects_explicit_openai_file_stt():
    from app.core.transcription import transcribe_audio_file

    with pytest.raises(ValueError, match="Unsupported file_stt option"):
        await transcribe_audio_file(
            b"audio",
            language="en",
            content_type="audio/wav",
            provider="openai",
            model="removed-file-model",
        )


@pytest.mark.asyncio
async def test_transcription_rejects_explicit_removed_file_stt_provider():
    from app.core.transcription import transcribe_audio_file

    with pytest.raises(ValueError, match="Unsupported file_stt option"):
        await transcribe_audio_file(
            b"webm-data",
            language="en",
            content_type="audio/webm",
            provider="removed-provider",
            model="removed-model",
        )


@pytest.mark.asyncio
async def test_transcription_surfaces_deepgram_quota_issue_without_provider_fallback():
    response = httpx.Response(
        429,
        json={"detail": {"status": "quota_exceeded", "message": "Quota exceeded."}},
        request=httpx.Request("POST", "https://api.deepgram.com/v1/listen"),
    )
    error = httpx.HTTPStatusError(
        "Client error '429 Too Many Requests'",
        request=response.request,
        response=response,
    )

    with patch(
        "app.core.transcription.deepgram_transcribe_audio_file",
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
async def test_transcription_reraises_unexpected_deepgram_failure_without_fallback(caplog):
    with patch(
        "app.core.transcription.deepgram_transcribe_audio_file",
        new=AsyncMock(side_effect=RuntimeError("socket closed")),
    ):
        from app.core.transcription import transcribe_audio_file

        caplog.set_level("ERROR", logger="app.core.transcription")
        with pytest.raises(RuntimeError, match="socket closed"):
            await transcribe_audio_file(
                b"secret-audio-bytes",
                language="ru",
                content_type="audio/wav",
                channels=1,
            )

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "file STT failed" in messages
    assert "provider=deepgram" in messages
    assert "error_type=RuntimeError" in messages
    assert "secret-audio-bytes" not in messages


@pytest.mark.asyncio
async def test_transcription_logs_provider_latency_without_audio_or_error_body(caplog):
    from app.core.transcript_utils import TranscriptResult

    with patch(
        "app.core.transcription.deepgram_transcribe_audio_file",
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
    assert "provider=deepgram" in messages
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
        "deepgram_transcribe_audio_file",
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
                "provider": "deepgram",
                "model": DEEPGRAM_FILE_STT_MODEL,
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
async def test_transcription_does_not_fallback_for_deepgram_bad_request():
    response = httpx.Response(
        400,
        json={"detail": {"message": "Invalid language"}},
        request=httpx.Request("POST", "https://api.deepgram.com/v1/listen"),
    )
    error = httpx.HTTPStatusError(
        "Client error '400 Bad Request'",
        request=response.request,
        response=response,
    )

    with patch(
        "app.core.transcription.deepgram_transcribe_audio_file",
        new=AsyncMock(side_effect=error),
    ):
        from app.core.transcription import transcribe_audio_file

        with pytest.raises(httpx.HTTPStatusError):
            await transcribe_audio_file(b"wav", language="not-a-language", content_type="audio/wav")


def test_provider_error_code_handles_unstructured_error_payloads():
    from app.core.transcription import _provider_error_code

    invalid_json_response = httpx.Response(
        503,
        content=b"not-json",
        request=httpx.Request("POST", "https://api.deepgram.com/v1/listen"),
    )
    invalid_json_error = httpx.HTTPStatusError(
        "Service unavailable",
        request=invalid_json_response.request,
        response=invalid_json_response,
    )
    assert _provider_error_code(invalid_json_error) is None

    list_response = httpx.Response(
        401,
        json=["bad"],
        request=httpx.Request("POST", "https://api.deepgram.com/v1/listen"),
    )
    list_error = httpx.HTTPStatusError(
        "Unauthorized",
        request=list_response.request,
        response=list_response,
    )
    assert _provider_error_code(list_error) is None

    error_response = httpx.Response(
        429,
        json={"detail": {"status": "quota_exceeded"}},
        request=httpx.Request("POST", "https://api.deepgram.com/v1/listen"),
    )
    error = httpx.HTTPStatusError(
        "Quota exceeded",
        request=error_response.request,
        response=error_response,
    )
    assert _provider_error_code(error) == "quota_exceeded"


@pytest.mark.asyncio
async def test_transcription_rejects_provider_left_after_validation(monkeypatch):
    monkeypatch.setattr(
        "app.core.transcription.validate_option",
        lambda _kind, _provider, _model: ("bogus", "model"),
    )
    from app.core.transcription import transcribe_audio_file

    with pytest.raises(ValueError, match="Unsupported file_stt_provider: bogus"):
        await transcribe_audio_file(
            b"audio",
            provider="deepgram",
            model=DEEPGRAM_FILE_STT_MODEL,
        )
