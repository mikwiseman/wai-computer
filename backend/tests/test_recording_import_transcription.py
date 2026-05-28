"""Tests for imported recording transcription routing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_import_transcription_uses_locked_file_stt_runtime(monkeypatch):
    from app.core import recording_import

    calls: list[dict[str, object]] = []

    async def fake_transcribe_audio_file(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return []

    monkeypatch.setattr(recording_import, "transcribe_audio_file", fake_transcribe_audio_file)
    monkeypatch.setattr(
        recording_import,
        "load_user_keyterms",
        AsyncMock(return_value=[]),
    )

    await recording_import._transcribe(
        db=object(),
        data=b"audio",
        content_type="audio/wav",
        language="auto",
        user=SimpleNamespace(
            id=uuid4(),
            file_stt_provider="removed-provider",
            file_stt_model="removed-model",
        ),
    )

    assert len(calls) == 1
    kwargs = calls[0]["kwargs"]
    assert kwargs["language"] == "auto"
    assert kwargs["content_type"] == "audio/wav"
    assert kwargs["keyterms"] == []
    assert "provider" not in kwargs
    assert "model" not in kwargs
