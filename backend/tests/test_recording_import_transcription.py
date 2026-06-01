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


# --- pure import-path helpers (pre-existing, cost-surface adjacent) -----------
def test_is_video_media_by_content_type_then_extension():
    from app.core.recording_import import _is_video_media

    assert _is_video_media("mp4", "video/mp4") is True
    assert _is_video_media("mp3", "audio/mpeg") is False
    # falls back to extension when content type is unhelpful
    assert _is_video_media("mp4", None) is True
    assert _is_video_media("mp3", None) is False


def test_resolve_language_normalizes_auto_multi():
    from app.core.recording_import import _resolve_language

    user = SimpleNamespace(default_language="en")
    assert _resolve_language(user, "ru") == "ru"
    assert _resolve_language(user, "MULTI") == "auto"
    assert _resolve_language(user, "auto") == "auto"
    assert _resolve_language(user, None) == "en"  # falls back to user default
    assert _resolve_language(SimpleNamespace(default_language="multi"), None) == "auto"


def test_summary_instructions_appends_telegram_block():
    from app.core.recording_import import (
        TELEGRAM_IMPORT_SUMMARY_INSTRUCTIONS,
        _summary_instructions,
    )

    # non-telegram source: raw instructions (or None)
    terse_user = SimpleNamespace(summary_instructions="be terse")
    blank_user = SimpleNamespace(summary_instructions="  ")
    assert _summary_instructions(terse_user, source_label="web") == "be terse"
    assert _summary_instructions(blank_user, source_label="web") is None
    # telegram: appends the telegram block, or uses it alone
    combined = _summary_instructions(
        SimpleNamespace(summary_instructions="keep it short"), source_label="telegram"
    )
    assert combined.startswith("keep it short")
    assert TELEGRAM_IMPORT_SUMMARY_INSTRUCTIONS in combined
    assert (
        _summary_instructions(SimpleNamespace(summary_instructions=""), source_label="telegram")
        == TELEGRAM_IMPORT_SUMMARY_INSTRUCTIONS
    )


def test_summary_style_forces_detailed_for_telegram():
    from app.core.recording_import import _summary_style

    user = SimpleNamespace(summary_style="medium")
    assert _summary_style(user, source_label="telegram") == "detailed"
    assert _summary_style(user, source_label="web") == "medium"
