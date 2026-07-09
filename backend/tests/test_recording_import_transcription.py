"""Tests for imported recording transcription routing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.transcript_utils import FileTranscription


@pytest.mark.asyncio
async def test_import_transcription_uses_locked_file_stt_runtime(monkeypatch, tmp_path):
    from app.core import recording_import

    calls: list[dict[str, object]] = []

    async def fake_transcribe_audio_file(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return FileTranscription(segments=[], words=[])

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

    media_path = tmp_path / "audio.wav"
    media_path.write_bytes(b"audio")
    await recording_import._transcribe(
        db=object(),
        media_path=media_path,
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
    from app.core.media_audio import is_video_media

    assert is_video_media("mp4", "video/mp4") is True
    assert is_video_media("mp3", "audio/mpeg") is False
    # falls back to extension when content type is unhelpful
    assert is_video_media("mp4", None) is True
    assert is_video_media("mp3", None) is False


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


@pytest.mark.asyncio
async def test_extract_speaker_names_accepts_import_usage_context():
    from app.core.speaker_name_extraction import extract_speaker_names

    assert (
        await extract_speaker_names(
            transcript_results=[],
            raw_labels=[],
            usage_user_id=uuid4(),
            usage_recording_id=uuid4(),
        )
        == {}
    )


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


def test_video_summary_style_forces_structured_media_output():
    from app.core.recording_import import _summary_style

    user = SimpleNamespace(summary_style="brief")

    assert _summary_style(user, source_label="upload", media_kind="video") == "structured"
    assert _summary_style(user, source_label="telegram", media_kind="video") == "structured"
    assert _summary_style(user, source_label="upload", media_kind="audio") == "brief"


def test_video_summary_instructions_match_wai_rocks_media_quality_rules():
    from app.core.recording_import import _summary_instructions

    instructions = _summary_instructions(
        SimpleNamespace(summary_instructions="Keep project names verbatim."),
        source_label="upload",
        media_kind="video",
    )

    assert instructions is not None
    assert "Keep project names verbatim." in instructions
    assert "Overall overview" in instructions
    assert "Highlight crucial data" in instructions
    assert "Identify key points" in instructions
    assert "Timestamps and section summaries" in instructions
    assert "source tone, style, and language" in instructions


def test_telegram_summary_instructions_are_scannable_and_kind_aware():
    from app.core.recording_import import TELEGRAM_IMPORT_SUMMARY_INSTRUCTIONS

    instructions = TELEGRAM_IMPORT_SUMMARY_INSTRUCTIONS
    # No padding floor: length follows content, a ceiling only tightens.
    assert "never pad" in instructions
    assert "tightening bullets" in instructions
    # Kind-aware + scannable: bold markdown headers, dash bullets, action-first.
    assert "KIND" in instructions
    assert "**" in instructions  # instructs Markdown bold section headers
    assert "- " in instructions  # instructs dash bullets
    assert "plan" in instructions and "meeting" in instructions and "lecture" in instructions
    # The wai-rocks-grade look: inline bold emphasis + monospace metrics.
    assert "load-bearing words in **bold**" in instructions
    assert "`backticks`" in instructions


@pytest.mark.asyncio
async def test_import_transcription_records_usage_on_provider_http_error(
    monkeypatch, tmp_path
):
    import httpx

    from app.core import recording_import

    usage_events: list[dict] = []

    async def fake_record_usage(db, **kwargs):
        usage_events.append(kwargs)

    request = httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text")
    response = httpx.Response(429, request=request, json={"detail": {"status": "busy"}})

    async def failing_transcribe(*args, **kwargs):
        raise httpx.HTTPStatusError("throttled", request=request, response=response)

    monkeypatch.setattr(recording_import, "transcribe_audio_file", failing_transcribe)
    monkeypatch.setattr(recording_import, "record_deepgram_usage_event", fake_record_usage)
    monkeypatch.setattr(recording_import, "load_user_keyterms", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        recording_import, "load_user_replacements", AsyncMock(return_value=[])
    )

    media_path = tmp_path / "audio.wav"
    media_path.write_bytes(b"audio")

    with pytest.raises(httpx.HTTPStatusError):
        await recording_import._transcribe(
            db=object(),
            media_path=media_path,
            content_type="audio/wav",
            language="auto",
            user=SimpleNamespace(id=uuid4()),
            audio_duration_seconds=12.0,
        )

    assert len(usage_events) == 1
    event = usage_events[0]
    assert event["status"] == "failed"
    assert event["provider_status_code"] == 429
    assert event["billable_seconds"] == 0


@pytest.mark.asyncio
async def test_import_transcription_records_usage_on_unexpected_error(
    monkeypatch, tmp_path
):
    from app.core import recording_import

    usage_events: list[dict] = []

    async def fake_record_usage(db, **kwargs):
        usage_events.append(kwargs)

    async def failing_transcribe(*args, **kwargs):
        raise RuntimeError("socket closed")

    monkeypatch.setattr(recording_import, "transcribe_audio_file", failing_transcribe)
    monkeypatch.setattr(recording_import, "record_deepgram_usage_event", fake_record_usage)
    monkeypatch.setattr(recording_import, "load_user_keyterms", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        recording_import, "load_user_replacements", AsyncMock(return_value=[])
    )

    media_path = tmp_path / "audio.wav"
    media_path.write_bytes(b"audio")

    with pytest.raises(RuntimeError):
        await recording_import._transcribe(
            db=object(),
            media_path=media_path,
            content_type="audio/wav",
            language="auto",
            user=SimpleNamespace(id=uuid4()),
        )

    assert len(usage_events) == 1
    assert usage_events[0]["status"] == "failed"
    assert usage_events[0]["error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_resolve_speaker_display_names_prefers_intros_over_directory(
    db_session,
):
    from app.core.recording_import import _resolve_speaker_display_names
    from app.models.person import Person
    from app.models.user import User
    from tests.conftest import LEGAL_ACCEPTANCE

    user = User(
        email=f"speaker-names-{uuid4()}@example.com",
        password_hash="hash",
        **{
            "legal_terms_version": LEGAL_ACCEPTANCE["legal_terms_version"],
            "legal_privacy_version": LEGAL_ACCEPTANCE["legal_privacy_version"],
        },
    )
    db_session.add(user)
    await db_session.flush()
    anna = Person(user_id=user.id, display_name="  Анна  ")
    blank = Person(user_id=user.id, display_name="   ")
    db_session.add_all([anna, blank])
    await db_session.flush()

    names = await _resolve_speaker_display_names(
        db_session,
        speaker_assignments={
            "speaker_0": (anna.id, 0.9),
            "speaker_1": None,
            "speaker_2": (blank.id, 0.8),
        },
        extracted_names={
            "speaker_0": SimpleNamespace(name="  Аня  "),
            "speaker_3": SimpleNamespace(name=""),
        },
    )

    # Directory match resolves the display name; a same-cluster introduction
    # overrides it; blank names never leak.
    assert names == {"speaker_0": "Аня"}
