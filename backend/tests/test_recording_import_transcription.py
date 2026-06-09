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
    monkeypatch.setattr(
        recording_import,
        "load_user_replacements",
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
    assert kwargs["replacements"] == []
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


def test_speaker_roster_instructions():
    from app.core.recording_import import _speaker_roster_instructions

    assert _speaker_roster_instructions({}) is None
    text = _speaker_roster_instructions({"speaker_0": "Дима", "speaker_1": "Слава"})
    assert text is not None
    assert "Дима" in text and "Слава" in text
    assert "owner" in text
    assert "never guess" in text.lower()


def test_labeled_summary_transcript_uses_resolved_names():
    from app.core.recording_import import _labeled_summary_transcript

    results = [
        SimpleNamespace(speaker="speaker_0", text="Я займусь продажами."),
        SimpleNamespace(speaker="speaker_1", text="Хорошо."),
        SimpleNamespace(speaker=None, text="Без спикера."),
    ]
    labeled = _labeled_summary_transcript(results, {"speaker_0": "Дима"})
    assert "Дима: Я займусь продажами." in labeled
    # Unmapped label keeps its raw label; None falls back to 'Speaker'.
    assert "speaker_1: Хорошо." in labeled
    assert "Speaker: Без спикера." in labeled


def test_summary_style_forces_structured_for_telegram():
    from app.core.recording_import import _summary_style

    user = SimpleNamespace(summary_style="medium")
    # Telegram gets the structure-first style (scannable sections), not a paragraph.
    assert _summary_style(user, source_label="telegram") == "structured"
    assert _summary_style(user, source_label="web") == "medium"


def test_telegram_summary_instructions_are_scannable_and_kind_aware():
    from app.core.recording_import import TELEGRAM_IMPORT_SUMMARY_INSTRUCTIONS

    instructions = TELEGRAM_IMPORT_SUMMARY_INSTRUCTIONS
    # No fixed character floor anymore (was "between 1000 and 3500 characters").
    assert "1000" not in instructions
    assert "3500" not in instructions
    # Kind-aware + scannable: bold markdown headers, dash bullets, action-first.
    assert "KIND" in instructions
    assert "**" in instructions  # instructs Markdown bold section headers
    assert "- " in instructions  # instructs dash bullets
    assert "plan" in instructions and "meeting" in instructions and "lecture" in instructions
