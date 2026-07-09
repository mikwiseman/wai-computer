"""Telegram bot linking and import tests."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import telegram as telegram_routes
from app.core import companion_actions as ca
from app.core import companion_actuators
from app.core.agent_runtime import RETRYABLE_AGENT_ERROR_PREFIX, static_config_planner
from app.core.recording_import import (
    RecordingImportError,
    import_media_as_recording,
    resolve_import_extension,
)
from app.core.summarizer import SummaryResult
from app.core.telegram_client import (
    TelegramBotClient,
    TelegramClientError,
    TelegramFile,
    TelegramFileTooLargeError,
    telegram_chunks,
)
from app.core.transcript_utils import TranscriptResult
from app.core.unified_search import UnifiedHit
from app.models.agent import Agent, AgentRun
from app.models.billing import UsageWeek
from app.models.companion import ChatMessage, Conversation
from app.models.companion_pending_action import CompanionPendingAction
from app.models.item import Item, ItemChunk, ItemSummary
from app.models.recording import (
    ActionItem,
    Highlight,
    Recording,
    RecordingShare,
    RecordingStatus,
    Segment,
    Summary,
)
from app.models.reminder import UserReminder
from app.models.telegram import (
    TelegramAccount,
    TelegramBotLinkCode,
    TelegramPairing,
    TelegramUpdate,
)
from app.models.user import User
from app.models.user_memory import UserMemoryBlock, UserMemoryLogEntry


async def _user(db: AsyncSession, email: str = "telegram@example.com") -> User:
    user = User(email=email, password_hash="hash")
    db.add(user)
    await db.flush()
    return user


def _stub_empty_brain_answer(monkeypatch, expected_question: str) -> None:
    async def fake_ask_brain(_session, _user_id, question, *, limit=None):
        assert question == expected_question
        assert limit == 12
        return SimpleNamespace(
            answer="",
            citations=[],
            gaps=["No matching sources yet."],
            freshness=None,
        )

    monkeypatch.setattr("app.core.agent_runtime.ask_brain", fake_ask_brain)


def _stub_telegram_turn(monkeypatch, answer: str, contexts: list[Any] | None = None) -> None:
    async def fake_run_turn(*args, **kwargs):
        if contexts is not None:
            contexts.append(kwargs.get("turn_context"))
        yield telegram_routes.TokenEvent(text=answer)

    monkeypatch.setattr(telegram_routes, "run_turn", fake_run_turn)


@pytest.mark.asyncio
async def test_start_link_returns_waicomputer_bot_deep_link(client, auth_headers, monkeypatch):
    monkeypatch.setattr(telegram_routes.settings, "telegram_bot_username", "waicomputer_bot")
    monkeypatch.setattr(telegram_routes.settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(telegram_routes.settings, "telegram_webhook_secret_token", "secret")

    response = await client.post("/api/telegram/link/start", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["bot_username"] == "waicomputer_bot"
    assert body["deep_link"].startswith("tg://resolve?domain=waicomputer_bot&start=link_")
    assert body["web_link"].startswith("https://t.me/waicomputer_bot?start=link_")


@pytest.mark.asyncio
async def test_start_link_requires_runtime_configuration(client, auth_headers, monkeypatch):
    monkeypatch.setattr(telegram_routes.settings, "telegram_bot_token", "")
    monkeypatch.setattr(telegram_routes.settings, "telegram_webhook_secret_token", "")

    response = await client.post("/api/telegram/link/start", headers=auth_headers)

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_consume_pairing_links_telegram_account(db_session: AsyncSession):
    user = await _user(db_session)
    raw_token = "secret-pairing-token"
    pairing = TelegramPairing(
        user_id=user.id,
        token_hash=telegram_routes._token_hash(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    db_session.add(pairing)
    await db_session.commit()

    message = await telegram_routes._consume_pairing(
        db_session,
        token=raw_token,
        telegram_user_id=12345,
        telegram_chat_id=12345,
        username="mik",
        first_name="Mik",
        last_name="Wiseman",
    )

    assert "Готово" in message
    account = (
        await db_session.execute(select(TelegramAccount).where(TelegramAccount.user_id == user.id))
    ).scalar_one()
    assert account.telegram_user_id == 12345
    assert account.username == "mik"
    await db_session.refresh(pairing)
    assert pairing.consumed_at is not None


@pytest.mark.asyncio
async def test_consume_pairing_rejects_conflicting_telegram_account(db_session: AsyncSession):
    owner = await _user(db_session, "owner@example.com")
    other = await _user(db_session, "other@example.com")
    db_session.add(TelegramAccount(user_id=owner.id, telegram_user_id=555))
    raw_token = "conflict-token"
    db_session.add(
        TelegramPairing(
            user_id=other.id,
            token_hash=telegram_routes._token_hash(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
    )
    await db_session.commit()

    message = await telegram_routes._consume_pairing(
        db_session,
        token=raw_token,
        telegram_user_id=555,
        telegram_chat_id=555,
        username=None,
        first_name=None,
        last_name=None,
    )

    assert "другому аккаунту" in message


def test_extract_media_accepts_voice_video_and_audio_documents():
    assert telegram_routes._extract_media({"voice": {"file_id": "voice-id"}})["kind"] == "voice"
    assert telegram_routes._extract_media({"video": {"file_id": "video-id"}})["kind"] == "video"
    assert (
        telegram_routes._extract_media(
            {
                "document": {
                    "file_id": "doc-id",
                    "file_name": "clip.mp4",
                    "mime_type": "application/octet-stream",
                }
            }
        )["kind"]
        == "document"
    )
    assert (
        telegram_routes._extract_media({"document": {"file_id": "doc-id", "file_name": "x.pdf"}})
        is None
    )


def test_extract_document_accepts_supported_material_documents():
    pdf = telegram_routes._extract_document(
        {"document": {"file_id": "doc-id", "file_name": "x.pdf", "mime_type": "application/pdf"}}
    )
    assert pdf is not None
    assert pdf["kind"] == "document"
    assert pdf["file_name"] == "x.pdf"

    html = telegram_routes._extract_document(
        {"document": {"file_id": "doc-id", "file_name": "report.html", "mime_type": "text/html"}}
    )
    assert html is not None

    assert (
        telegram_routes._extract_document(
            {"document": {"file_id": "doc-id", "file_name": "archive.zip"}}
        )
        is None
    )


@pytest.mark.parametrize(
    ("filename", "mime_type", "expected_ext"),
    [
        ("legacy.xls", "application/vnd.ms-excel", "xls"),
        ("slides.ppt", "application/vnd.ms-powerpoint", "ppt"),
        ("brief.odt", "application/vnd.oasis.opendocument.text", "odt"),
        ("sheet.ods", "application/vnd.oasis.opendocument.spreadsheet", "ods"),
        ("deck.odp", "application/vnd.oasis.opendocument.presentation", "odp"),
        ("book.epub", "application/epub+zip", "epub"),
        ("mail.eml", "message/rfc822", "eml"),
        ("outlook.msg", "application/vnd.ms-outlook", "msg"),
        ("snapshot.mhtml", "application/x-mimearchive", "mhtml"),
        ("config.yaml", "application/x-yaml", "yaml"),
        ("feed.xml", "application/xml", "xml"),
    ],
)
def test_extract_document_accepts_broad_material_documents(
    filename: str,
    mime_type: str,
    expected_ext: str,
) -> None:
    document = telegram_routes._extract_document(
        {
            "document": {
                "file_id": "doc-id",
                "file_name": filename,
                "mime_type": mime_type,
            }
        }
    )

    assert document is not None
    assert document["kind"] == "document"
    assert document["document_ext"] == expected_ext


@pytest.mark.asyncio
async def test_import_media_as_recording_persists_transcript_and_summary(
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    user = await _user(db_session)
    user.default_language = "ru"
    user.summary_language = "ru"
    user.summary_style = "medium"
    db_session.add(user)
    await db_session.commit()
    monkeypatch.setattr("app.core.recording_import.settings.upload_staging_dir", str(tmp_path))

    async def fake_transcribe(*args, **kwargs):
        return [
            TranscriptResult(
                text="Привет из Telegram",
                speaker="speaker_1",
                is_final=True,
                start_ms=0,
                end_ms=1200,
                confidence=0.95,
            )
        ]

    async def fake_embedding(text: str, **_: object):
        raise RuntimeError("embedding offline")

    async def fake_identify(**kwargs):
        raise RuntimeError("voice id offline")

    async def fake_summary(transcript: str, **kwargs):
        assert "For Telegram voice/audio imports" in kwargs["instructions"]
        assert "scannable at a glance" in kwargs["instructions"]
        assert kwargs["style"] == "structured"
        return SummaryResult(
            title="Telegram запись",
            summary="Короткое саммари.",
            key_points=["Главная мысль"],
            decisions=[],
            action_items=[
                {
                    "task": "Позвонить",
                    "owner": "Mik",
                    "due": date(2026, 5, 23),
                    "priority": "urgent",
                },
                {"task": "Проверить", "due": "bad-date", "priority": "low"},
                {"task": ""},
            ],
            topics=["Telegram"],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
            highlights=[
                {
                    "category": "decision",
                    "title": "Важный момент",
                    "description": "Описание",
                    "speaker": "speaker_1",
                    "start_ms": 0,
                    "end_ms": 1200,
                    "importance": "critical",
                },
                {"title": ""},
            ],
        )

    monkeypatch.setattr("app.core.recording_import.transcribe_audio_file", fake_transcribe)
    monkeypatch.setattr("app.core.recording_import.generate_embedding", fake_embedding)
    monkeypatch.setattr("app.core.recording_import.identify_speakers_for_recording", fake_identify)
    monkeypatch.setattr("app.core.recording_import.summarize_transcript", fake_summary)

    result = await import_media_as_recording(
        db=db_session,
        user=user,
        data=b"fake wav",
        filename="voice.wav",
        content_type="audio/wav",
        title=None,
        source_label="telegram",
        language="ru",
    )

    assert result.recording.status == RecordingStatus.READY.value
    assert result.recording.title == "Telegram запись"
    assert result.transcript == "Привет из Telegram"

    recording = (
        await db_session.execute(select(Recording).where(Recording.id == result.recording.id))
    ).scalar_one()
    segments = (
        (await db_session.execute(select(Segment).where(Segment.recording_id == recording.id)))
        .scalars()
        .all()
    )
    summary = (
        await db_session.execute(select(Summary).where(Summary.recording_id == recording.id))
    ).scalar_one()
    action_items = (
        (
            await db_session.execute(
                select(ActionItem).where(ActionItem.recording_id == recording.id)
            )
        )
        .scalars()
        .all()
    )
    highlights = (
        (await db_session.execute(select(Highlight).where(Highlight.recording_id == recording.id)))
        .scalars()
        .all()
    )
    assert len(segments) == 1
    assert segments[0].content == "Привет из Telegram"
    assert summary.summary == "Короткое саммари."
    assert len(action_items) == 2
    assert action_items[0].priority == "medium"
    assert action_items[0].due_date == date(2026, 5, 23)
    assert action_items[1].priority == "low"
    assert action_items[1].due_date is None
    assert len(highlights) == 1
    assert highlights[0].importance == "medium"
    usage = (
        await db_session.execute(select(UsageWeek).where(UsageWeek.user_id == user.id))
    ).scalar_one()
    assert usage.words_used == 3
    assert recording.billed_word_count == 3


@pytest.mark.asyncio
async def test_import_media_keeps_transcript_when_summary_fails(
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    user = await _user(db_session, "telegram-summary-fails@example.com")
    await db_session.commit()
    monkeypatch.setattr("app.core.recording_import.settings.upload_staging_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.core.recording_import.capture_sentry_anomaly",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    async def fake_transcribe(*args, **kwargs):
        return [
            TranscriptResult(
                text="Транскрипт сохранен",
                speaker="speaker_1",
                is_final=True,
                start_ms=0,
                end_ms=1400,
                confidence=0.96,
            )
        ]

    async def fake_summary(*args, **kwargs):
        raise RuntimeError("summary offline")

    monkeypatch.setattr("app.core.recording_import.transcribe_audio_file", fake_transcribe)
    monkeypatch.setattr(
        "app.core.recording_import.generate_embedding",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.core.recording_import.identify_speakers_for_recording",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.core.recording_import.extract_speaker_names",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr("app.core.recording_import.summarize_transcript", fake_summary)

    result = await import_media_as_recording(
        db=db_session,
        user=user,
        data=b"fake wav",
        filename="voice.wav",
        content_type="audio/wav",
        title="Telegram audio",
        source_label="telegram",
        language="ru",
    )

    assert result.recording.status == RecordingStatus.READY.value
    assert result.recording.failure_code is None
    assert result.transcript == "Транскрипт сохранен"
    assert result.summary is None

    recording = (
        await db_session.execute(select(Recording).where(Recording.id == result.recording.id))
    ).scalar_one()
    segments = (
        (await db_session.execute(select(Segment).where(Segment.recording_id == recording.id)))
        .scalars()
        .all()
    )
    summary = (
        await db_session.execute(select(Summary).where(Summary.recording_id == recording.id))
    ).scalar_one_or_none()
    assert recording.status == RecordingStatus.READY.value
    assert len(segments) == 1
    assert segments[0].content == "Транскрипт сохранен"
    assert summary is None


@pytest.mark.asyncio
async def test_import_media_keeps_transcript_when_billing_fails(
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    user = await _user(db_session, "telegram-billing-fails@example.com")
    await db_session.commit()
    monkeypatch.setattr("app.core.recording_import.settings.upload_staging_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.core.recording_import.capture_sentry_anomaly",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    async def fake_transcribe(*args, **kwargs):
        return [
            TranscriptResult(
                text="Транскрипт и саммари сохранены",
                speaker="speaker_1",
                is_final=True,
                start_ms=0,
                end_ms=1600,
                confidence=0.95,
            )
        ]

    async def fake_summary(*args, **kwargs):
        return SummaryResult(
            title="Billing degraded",
            summary="Саммари сохранено.",
            key_points=[],
            decisions=[],
            action_items=[],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
            highlights=[],
        )

    async def broken_billing(*args, **kwargs):
        raise RuntimeError("billing offline")

    monkeypatch.setattr("app.core.recording_import.transcribe_audio_file", fake_transcribe)
    monkeypatch.setattr(
        "app.core.recording_import.generate_embedding",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.core.recording_import.identify_speakers_for_recording",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.core.recording_import.extract_speaker_names",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr("app.core.recording_import.summarize_transcript", fake_summary)
    monkeypatch.setattr(
        "app.core.recording_import.record_recording_transcript_words",
        broken_billing,
    )

    result = await import_media_as_recording(
        db=db_session,
        user=user,
        data=b"fake wav",
        filename="voice.wav",
        content_type="audio/wav",
        title=None,
        source_label="telegram",
        language="ru",
    )

    assert result.recording.status == RecordingStatus.READY.value
    assert result.transcript == "Транскрипт и саммари сохранены"
    assert result.summary is not None

    recording = (
        await db_session.execute(select(Recording).where(Recording.id == result.recording.id))
    ).scalar_one()
    summary = (
        await db_session.execute(select(Summary).where(Summary.recording_id == recording.id))
    ).scalar_one()
    assert recording.status == RecordingStatus.READY.value
    assert recording.title == "Billing degraded"
    assert recording.billed_word_count == 0
    assert summary.summary == "Саммари сохранено."


@pytest.mark.asyncio
async def test_import_media_marks_failed_on_cost_guard_rejection(
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    """A Deepgram cost/abuse guard rejection during an import surfaces a
    RecordingImportError carrying the guard code (and marks the recording failed
    via _mark_failed, verified separately) — it does NOT retry or re-bill."""
    from app.core.transcription_guard import TranscriptionGuardError

    user = await _user(db_session, "telegram-guard@example.com")
    await db_session.commit()
    monkeypatch.setattr("app.core.recording_import.settings.upload_staging_dir", str(tmp_path))

    marked: dict[str, object] = {}

    async def _raise_guard(*_args, **_kwargs):
        raise TranscriptionGuardError("transcription_halted", "halted")

    async def _capture_mark_failed(*, db, recording_id, code, message):
        marked["code"] = code
        return None

    monkeypatch.setattr("app.core.recording_import.transcribe_audio_file", _raise_guard)
    monkeypatch.setattr("app.core.recording_import._mark_failed", _capture_mark_failed)

    with pytest.raises(RecordingImportError) as ei:
        await import_media_as_recording(
            db=db_session,
            user=user,
            data=b"fake wav",
            filename="voice.wav",
            content_type="audio/wav",
            title=None,
            source_label="telegram",
            language="ru",
        )
    assert ei.value.code == "transcription_halted"
    # the handler routed the guard code into _mark_failed (recording -> failed)
    assert marked["code"] == "transcription_halted"


@pytest.mark.asyncio
async def test_webhook_requires_secret(client, monkeypatch):
    monkeypatch.setattr(telegram_routes.settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(telegram_routes.settings, "telegram_webhook_secret_token", "secret")

    response = await client.post("/api/telegram/webhook", json={"update_id": 1})

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_link_status_unlink_and_missing_bot_username(db_session: AsyncSession, monkeypatch):
    user = await _user(db_session)
    monkeypatch.setattr(telegram_routes.settings, "telegram_bot_username", "waicomputer_bot")

    status = await telegram_routes.get_link_status(user, db_session)
    assert status.linked is False
    assert status.bot_username == "waicomputer_bot"

    db_session.add(
        TelegramAccount(
            user_id=user.id,
            telegram_user_id=777,
            telegram_chat_id=777,
            username="mik",
        )
    )
    await db_session.commit()
    linked = await telegram_routes.get_link_status(user, db_session)
    assert linked.linked is True
    assert linked.username == "mik"

    response = await telegram_routes.unlink(user, db_session)
    assert response.status_code == 204
    assert await telegram_routes._load_account(db_session, 777) is None

    monkeypatch.setattr(telegram_routes.settings, "telegram_bot_username", " ")
    with pytest.raises(telegram_routes.HTTPException) as exc:
        await telegram_routes.get_link_status(user, db_session)
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_expired_pairing_and_command_helpers(db_session: AsyncSession):
    user = await _user(db_session)
    raw_token = "expired-token"
    db_session.add(
        TelegramPairing(
            user_id=user.id,
            token_hash=telegram_routes._token_hash(raw_token),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
    )
    await db_session.commit()

    message = await telegram_routes._consume_pairing(
        db_session,
        token=raw_token,
        telegram_user_id=500,
        telegram_chat_id=500,
        username=None,
        first_name=None,
        last_name=None,
    )

    assert "устарел" in message
    assert telegram_routes._message_command({"text": "/start@waicomputer_bot payload"}) == (
        "/start",
        "payload",
    )
    assert telegram_routes._message_command({"caption": "hello"}) is None
    assert telegram_routes._telegram_user({"from": "bad"}) is None
    assert telegram_routes._telegram_chat_id({"chat": "bad"}) is None


def test_telegram_import_response_helpers():
    result = SimpleNamespace(
        recording=SimpleNamespace(title="Рефлексия 21 неделя 17 23 мая"),
        summary=SimpleNamespace(
            summary="Что понравилось:\n- Первый пункт\n\nЧто дальше:\n- Второй пункт",
            key_points=["Первый пункт", "", "Второй пункт"],
            topics=["Работа", "Режим"],
        ),
    )

    assert (
        telegram_routes._safe_transcript_filename(result.recording.title, media_kind="voice")
        == "refleksiya-21-nedelya-17-23-maya.txt"
    )
    assert (
        telegram_routes._safe_transcript_filename("!!!", media_kind="voice") == "telegram-voice.txt"
    )
    assert telegram_routes._sent_message_id("not-dict") is None

    text = telegram_routes._format_import_summary_message(result)
    assert text.startswith("<b>Рефлексия 21 неделя 17 23 мая</b>")
    assert "<b>Что понравилось:</b>\n- Первый пункт" in text
    assert "<b>Что дальше:</b>\n- Второй пункт" in text

    html = telegram_routes._format_import_summary_message(
        SimpleNamespace(
            recording=SimpleNamespace(title="A <B> & C"),
            summary=SimpleNamespace(summary="Risk <check>:\n- Keep A & B"),
        )
    )
    assert html.startswith("<b>A &lt;B&gt; &amp; C</b>")
    assert "<b>Risk &lt;check&gt;:</b>" in html
    assert "- Keep A &amp; B" in html


def test_telegram_command_and_formatting_helpers_cover_edge_branches():
    assert telegram_routes._is_private_chat({}) is False
    assert telegram_routes._is_private_chat({"chat": {"type": "private"}}) is True
    assert telegram_routes._format_duration(None) == "длительность неизвестна"
    assert telegram_routes._format_duration(42) == "42 сек"
    assert telegram_routes._format_duration(65) == "1:05"
    assert telegram_routes._format_duration(3661) == "1:01:01"
    assert telegram_routes._format_created_at(None) == "дата неизвестна"
    assert telegram_routes._format_created_at("bad-date") == "bad-date"
    assert telegram_routes._format_created_at("2026-06-04T10:11:12+00:00") == "2026-06-04 10:11"
    assert telegram_routes._extract_search_query("поиск") == ""
    assert telegram_routes._extract_search_query("find roadmap") == "roadmap"
    assert telegram_routes._text_intent("") is None
    assert telegram_routes._text_intent("помощь") == ("help", "")
    assert telegram_routes._text_intent("запомни отвечать короче") == (
        "remember",
        "отвечать короче",
    )
    assert telegram_routes._text_intent("remind me in 10m stretch") == (
        "remind",
        "in 10m stretch",
    )
    assert telegram_routes._text_intent("what did we discuss launch") == (
        "search",
        "what did we discuss launch",
    )
    assert telegram_routes._text_intent("latest meetings") == ("meetings", "")
    assert telegram_routes._format_recording_list([], empty_text="empty") == "empty"
    assert telegram_routes._format_search_results([], query="roadmap") == (
        "Ничего не нашел по запросу: roadmap"
    )

    recordings = telegram_routes._format_recording_list(
        [
            {
                "title": "",
                "metadata": {"created_at": "not-a-date", "duration_seconds": 61},
                "url": "https://wai.computer/r/1",
            }
        ],
        empty_text="empty",
    )
    assert "Без названия" in recordings
    assert "1:01" in recordings

    search_results = telegram_routes._format_search_results(
        [
            UnifiedHit(
                source_kind="item",
                parent_id=str(uuid4()),
                chunk_id=str(uuid4()),
                title="Roadmap",
                kind="note",
                snippet="Launch plan",
                score=1.0,
                created_at=None,
            )
        ],
        query="launch",
    )
    assert "Roadmap" in search_results
    assert "материал" in search_results
    assert "Launch plan" in search_results

    assert telegram_routes._parse_remember_arg("preferences: answer shorter") == (
        "preferences",
        "- answer shorter",
    )
    now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
    due_at, reminder_text = telegram_routes._parse_remind_arg("in 10m stand up", now=now)
    assert due_at == datetime(2026, 6, 4, 12, 10, tzinfo=timezone.utc)
    assert reminder_text == "stand up"
    due_at, reminder_text = telegram_routes._parse_remind_arg(
        "2026-06-04T18:30+03:00 call team",
        now=now,
    )
    assert due_at == datetime(2026, 6, 4, 15, 30, tzinfo=timezone.utc)
    assert reminder_text == "call team"
    with pytest.raises(ValueError, match="timezone"):
        telegram_routes._parse_remind_arg("2026-06-04T18:30 call team", now=now)


@pytest.mark.asyncio
async def test_delete_status_message_handles_missing_and_telegram_error(caplog):
    client = MagicMock()
    client.delete_message = AsyncMock(side_effect=TelegramClientError("blocked"))

    await telegram_routes._delete_status_message(client, chat_id=1, message_id=None)
    client.delete_message.assert_not_awaited()

    with caplog.at_level("WARNING", logger="app.api.routes.telegram"):
        await telegram_routes._delete_status_message(client, chat_id=1, message_id=2)

    client.delete_message.assert_awaited_once_with(1, 2)
    assert "telegram status delete failed" in caplog.text


@pytest.mark.asyncio
async def test_chat_action_loop_handles_telegram_and_internal_errors(monkeypatch):
    class TelegramErrorClient:
        async def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
            raise TelegramClientError("blocked")

    async def cancel_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(telegram_routes.asyncio, "sleep", cancel_sleep)
    with pytest.raises(asyncio.CancelledError):
        await telegram_routes._send_chat_action_until_cancelled(TelegramErrorClient(), 1)

    class BrokenClient:
        async def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
            raise RuntimeError("boom")

    await telegram_routes._send_chat_action_until_cancelled(BrokenClient(), 1)
    await telegram_routes._stop_chat_action_task(None)


class _TelegramCapture:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []
        self.documents: list[dict[str, Any]] = []
        self.deleted_messages: list[dict[str, Any]] = []
        self.callback_answers: list[dict[str, Any]] = []
        self.edited_messages: list[dict[str, Any]] = []
        self.file = TelegramFile("file-id", "voice/file.ogg", 12)
        self.data = b"telegram audio"

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_to_message_id: int | None = None,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        message_id = len(self.messages) + 1
        self.messages.append(
            {
                "message_id": message_id,
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            }
        )
        return {"message_id": message_id}

    async def answer_callback_query(
        self, callback_query_id: str, *, text: str | None = None
    ) -> None:
        self.callback_answers.append({"id": callback_query_id, "text": text})

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = None,
    ) -> None:
        self.edited_messages.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
            }
        )
        return {"message_id": message_id}

    async def send_document(
        self,
        chat_id: int,
        *,
        filename: str,
        data: bytes,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> None:
        self.documents.append(
            {
                "chat_id": chat_id,
                "filename": filename,
                "data": data,
                "caption": caption,
                "reply_to_message_id": reply_to_message_id,
            }
        )

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        self.deleted_messages.append({"chat_id": chat_id, "message_id": message_id})

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        self.actions.append({"chat_id": chat_id, "action": action})

    async def get_file(self, file_id: str) -> TelegramFile:
        assert file_id == "file-id"
        return self.file

    async def download_file(self, file: TelegramFile, *, max_bytes: int | None = None) -> bytes:
        assert file.file_path == self.file.file_path
        if max_bytes is not None and len(self.data) > max_bytes:
            raise TelegramFileTooLargeError("Telegram file exceeds configured limit")
        return self.data

    async def download_file_to_path(
        self, file: TelegramFile, dest, *, max_bytes: int | None = None
    ) -> int:
        assert file.file_path == self.file.file_path
        if max_bytes is not None and len(self.data) > max_bytes:
            raise TelegramFileTooLargeError("Telegram file exceeds configured limit")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.data)
        return len(self.data)


@pytest.mark.asyncio
async def test_handle_start_command_existing_and_missing_link(db_session: AsyncSession):
    user = await _user(db_session)
    db_session.add(TelegramAccount(user_id=user.id, telegram_user_id=123, telegram_chat_id=123))
    await db_session.commit()
    capture = _TelegramCapture()
    message = {
        "message_id": 7,
        "from": {"id": 123, "username": "mik"},
        "chat": {"id": 123},
        "text": "/start",
    }

    await telegram_routes._handle_start_command(
        db_session,
        capture,
        message=message,
        arg="",
    )
    await telegram_routes._handle_start_command(
        db_session,
        capture,
        message={**message, "from": {"id": 999}, "chat": {"id": 999}},
        arg="",
    )

    assert "Telegram привязан" in capture.messages[0]["text"]
    assert "/meetings" in capture.messages[0]["text"]
    # A brand-new user is offered Telegram-only signup (consent button), not a code.
    assert "Условия" in capture.messages[1]["text"]
    assert capture.messages[1]["reply_markup"]["inline_keyboard"]
    assert (
        await db_session.execute(
            select(TelegramBotLinkCode).where(TelegramBotLinkCode.telegram_user_id == 999)
        )
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_handle_update_routes_help_meetings_and_natural_search(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-commands@example.com")
    other = await _user(db_session, "telegram-commands-other@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=60, telegram_chat_id=60)
    db_session.add(account)
    meeting = Recording(
        user_id=user.id,
        title="Roadmap Sync",
        type="meeting",
        status=RecordingStatus.READY.value,
        duration_seconds=184,
        language="ru",
    )
    meeting.created_at = datetime(2026, 5, 24, 10, 0, tzinfo=timezone.utc)
    note = Recording(user_id=user.id, title="Private note", type="note", language="ru")
    deleted_meeting = Recording(user_id=user.id, title="Deleted meeting", type="meeting")
    deleted_meeting.deleted_at = datetime(2026, 5, 25, tzinfo=timezone.utc)
    other_meeting = Recording(user_id=other.id, title="Other meeting", type="meeting")
    db_session.add_all([meeting, note, deleted_meeting, other_meeting])
    await db_session.flush()
    db_session.add(Segment(recording_id=meeting.id, content="Дорожная карта и запуск", start_ms=0))
    item = Item(
        user_id=user.id,
        source="paste",
        kind="note",
        title="Launch memo",
        body="Материал про запуск Product Radar",
        content_hash="a" * 64,
        embedding=[0.02] * 1536,
    )
    db_session.add(item)
    await db_session.flush()
    db_session.add(
        ItemChunk(
            item_id=item.id,
            seq=0,
            content="Материал про запуск Product Radar",
            embedding=[0.02] * 1536,
        )
    )
    for update_id in (201, 202, 203, 204):
        db_session.add(
            TelegramUpdate(
                update_id=update_id,
                status="accepted",
                received_at=datetime.now(timezone.utc),
            )
        )
    await db_session.commit()
    capture = _TelegramCapture()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(telegram_routes, "TelegramBotClient", lambda: capture)
    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)
    _stub_telegram_turn(
        monkeypatch,
        "Пока не могу ответить из твоего Brain.\nNo matching sources yet.",
    )

    async def fake_unified_search(_db, received_user_id, query, *, limit: int):
        assert received_user_id == user.id
        assert query == "запуск"
        assert limit == 5
        return [
            UnifiedHit(
                source_kind="item",
                parent_id=str(item.id),
                chunk_id=str(uuid4()),
                title="Launch memo",
                kind="note",
                snippet="Материал про запуск Product Radar",
                score=1.0,
                created_at=None,
            )
        ]

    monkeypatch.setattr(telegram_routes, "unified_search", fake_unified_search)

    async def send_text(update_id: int, text: str) -> None:
        await telegram_routes._handle_update(
            {
                "update_id": update_id,
                "message": {
                    "message_id": update_id,
                    "from": {"id": 60, "username": "mik"},
                    "chat": {"id": 60, "type": "private"},
                    "text": text,
                },
            }
        )

    await send_text(201, "/help")
    await send_text(202, "/meetings")
    await send_text(203, "покажи последние встречи")
    await send_text(204, "найди запуск")

    assert "/meetings" in capture.messages[0]["text"]
    assert "/actions" not in capture.messages[0]["text"]
    assert "Roadmap Sync" in capture.messages[1]["text"]
    assert "Private note" not in capture.messages[1]["text"]
    assert "Deleted meeting" not in capture.messages[1]["text"]
    assert "Roadmap Sync" in capture.messages[2]["text"]
    assert "запуск" in capture.messages[3]["text"]
    assert "Launch memo" in capture.messages[3]["text"]
    assert (await db_session.get(TelegramUpdate, 204)).status == "completed"


@pytest.mark.asyncio
async def test_telegram_remember_and_remind_commands_persist_portable_state(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-memory-reminders@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=61, telegram_chat_id=61)
    db_session.add(account)
    for update_id in (205, 206, 207):
        db_session.add(
            TelegramUpdate(
                update_id=update_id,
                status="accepted",
                received_at=datetime.now(timezone.utc),
            )
        )
    await db_session.commit()
    capture = _TelegramCapture()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(telegram_routes, "TelegramBotClient", lambda: capture)
    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)

    async def send_text(update_id: int, text: str) -> None:
        await telegram_routes._handle_update(
            {
                "update_id": update_id,
                "message": {
                    "message_id": update_id,
                    "from": {"id": 61, "username": "mik"},
                    "chat": {"id": 61, "type": "private"},
                    "text": text,
                },
            }
        )

    await send_text(205, "/remember preferences отвечать короче")
    await send_text(206, "/remind in 10m stretch")
    await send_text(207, "/remind tomorrow stretch")

    memory = (
        await db_session.execute(
            select(UserMemoryBlock).where(
                UserMemoryBlock.user_id == user.id,
                UserMemoryBlock.label == "preferences",
            )
        )
    ).scalar_one()
    memory_log = (
        await db_session.execute(
            select(UserMemoryLogEntry).where(UserMemoryLogEntry.user_id == user.id)
        )
    ).scalar_one()
    reminder = (
        await db_session.execute(select(UserReminder).where(UserReminder.user_id == user.id))
    ).scalar_one()

    assert "отвечать короче" in memory.body
    assert memory.updated_by == "user"
    assert memory_log.source == "user"
    assert reminder.status == "pending"
    assert reminder.text == "stretch"
    assert reminder.source == "telegram"
    assert reminder.telegram_chat_id == 61
    assert reminder.due_at > datetime.now(timezone.utc)
    assert "Запомнил" in capture.messages[0]["text"]
    assert "Поставил напоминание" in capture.messages[1]["text"]
    assert "Формат: /remind" in capture.messages[2]["text"]
    assert (await db_session.get(TelegramUpdate, 207)).status == "completed"


@pytest.mark.asyncio
async def test_telegram_agent_commands_start_list_status_cancel_and_approvals(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-agents@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=77, telegram_chat_id=77)
    agent = Agent(
        user_id=user.id,
        name="Researcher",
        kind="research",
        trigger_type="manual",
        config={"steps": [{"tool": "note", "args": {"text": "hello"}}]},
    )
    db_session.add_all([account, agent])
    await db_session.commit()
    capture = _TelegramCapture()
    dispatched: list[str] = []
    monkeypatch.setattr(
        telegram_routes,
        "enqueue_agent_run",
        lambda run_id: dispatched.append(str(run_id)) or "task-telegram",
    )

    message = {"message_id": 301, "chat": {"id": 77}}
    await telegram_routes._handle_account_command(
        db_session,
        capture,
        message=message,
        account=account,
        intent="agents",
    )
    await telegram_routes._handle_account_command(
        db_session,
        capture,
        message=message,
        account=account,
        intent="run",
        arg="Researcher check today",
    )
    run = (
        await db_session.execute(select(AgentRun).where(AgentRun.agent_id == agent.id))
    ).scalar_one()
    await telegram_routes._handle_account_command(
        db_session,
        capture,
        message=message,
        account=account,
        intent="list",
    )
    await telegram_routes._handle_account_command(
        db_session,
        capture,
        message=message,
        account=account,
        intent="status",
        arg=str(run.id)[:8],
    )
    await telegram_routes._handle_account_command(
        db_session,
        capture,
        message=message,
        account=account,
        intent="cancel",
        arg=str(run.id)[:8],
    )

    assert "Researcher" in capture.messages[0]["text"]
    assert "Запустил" in capture.messages[1]["text"]
    assert dispatched == [str(run.id)]
    assert "Последние запуски" in capture.messages[2]["text"]
    assert "pending approvals" in capture.messages[3]["text"]
    assert "Остановил" in capture.messages[4]["text"]
    await db_session.refresh(run)
    assert run.status == "cancelled"


@pytest.mark.asyncio
async def test_telegram_agent_commands_empty_invalid_and_dispatch_failure(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-agent-edges@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=79, telegram_chat_id=79)
    disabled = Agent(
        user_id=user.id,
        name="Disabled",
        kind="research",
        trigger_type="manual",
        enabled=False,
        config={"steps": [{"tool": "note", "args": {"text": "off"}}]},
    )
    brokered = Agent(
        user_id=user.id,
        name="Brokered",
        kind="research",
        trigger_type="manual",
        config={"steps": [{"tool": "note", "args": {"text": "later"}}]},
    )
    db_session.add_all([account, disabled, brokered])
    await db_session.commit()
    capture = _TelegramCapture()
    message = {"message_id": 401, "chat": {"id": 79}}

    async def command(intent: str, arg: str = "") -> None:
        await telegram_routes._handle_account_command(
            db_session,
            capture,
            message=message,
            account=account,
            intent=intent,
            arg=arg,
        )

    await command("agents")
    await command("run")
    await command("run", "missing-agent do it")
    await command("run", "Disabled do it")
    await command("runs")
    await command("run_status", "missing-run")
    await command("cancel_run", "missing-run")
    await command("approvals")
    await command("approve", "not-a-uuid")

    def fail_dispatch(_run_id):
        raise telegram_routes.AgentDispatchError("broker offline")

    monkeypatch.setattr(telegram_routes, "enqueue_agent_run", fail_dispatch)
    await command("run", "Brokered do it")
    await command("run", "Brokered do it")

    assert "Disabled" in capture.messages[0]["text"]
    assert "Формат: /run" in capture.messages[1]["text"]
    assert "Агент не найден" in capture.messages[2]["text"]
    assert "Агент выключен" in capture.messages[3]["text"]
    assert "Запусков агентов пока нет" in capture.messages[4]["text"]
    assert "Запуск не найден" in capture.messages[5]["text"]
    assert "Запуск не найден" in capture.messages[6]["text"]
    assert "Нет действий" in capture.messages[7]["text"]
    assert "Нужен action_id" in capture.messages[8]["text"]
    assert "Не смог запустить агента: broker offline" in capture.messages[9]["text"]
    assert "status: failed" in capture.messages[10]["text"]


@pytest.mark.asyncio
async def test_telegram_run_requires_id_for_duplicate_agent_names(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-agent-duplicate@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=75, telegram_chat_id=75)
    first = Agent(
        user_id=user.id,
        name="Researcher",
        kind="research",
        trigger_type="manual",
        config={"steps": [{"tool": "note", "args": {"text": "first"}}]},
    )
    second = Agent(
        user_id=user.id,
        name="Researcher",
        kind="research",
        trigger_type="manual",
        config={"steps": [{"tool": "note", "args": {"text": "second"}}]},
    )
    db_session.add_all([account, first, second])
    await db_session.commit()
    capture = _TelegramCapture()
    dispatched: list[str] = []
    monkeypatch.setattr(
        telegram_routes,
        "enqueue_agent_run",
        lambda run_id: dispatched.append(str(run_id)) or "task-duplicate",
    )

    await telegram_routes._handle_account_command(
        db_session,
        capture,
        message={"message_id": 407, "chat": {"id": 75}},
        account=account,
        intent="run",
        arg="Researcher compare notes",
    )

    assert "Несколько агентов" in capture.messages[-1]["text"]
    assert str(first.id)[:8] in capture.messages[-1]["text"]
    assert str(second.id)[:8] in capture.messages[-1]["text"]
    assert dispatched == []
    runs = (await db_session.execute(select(AgentRun).where(AgentRun.user_id == user.id))).all()
    assert runs == []


@pytest.mark.asyncio
async def test_telegram_run_supports_multi_word_agent_name(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-agent-multiword@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=74, telegram_chat_id=74)
    agent = Agent(
        user_id=user.id,
        name="Daily Researcher",
        kind="research",
        trigger_type="manual",
        config={"steps": [{"tool": "note", "args": {"text": "first"}}]},
    )
    db_session.add_all([account, agent])
    await db_session.commit()
    capture = _TelegramCapture()
    dispatched: list[str] = []
    monkeypatch.setattr(
        telegram_routes,
        "enqueue_agent_run",
        lambda run_id: dispatched.append(str(run_id)) or "task-multiword",
    )

    await telegram_routes._handle_account_command(
        db_session,
        capture,
        message={"message_id": 409, "chat": {"id": 74}},
        account=account,
        intent="run",
        arg="Daily Researcher compare notes",
    )

    run = (
        await db_session.execute(select(AgentRun).where(AgentRun.agent_id == agent.id))
    ).scalar_one()
    assert "Запустил: Daily Researcher" in capture.messages[-1]["text"]
    assert run.trigger_payload["objective"] == "compare notes"
    assert dispatched == [str(run.id)]


@pytest.mark.asyncio
async def test_telegram_run_requires_objective_after_agent_ref(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-agent-objective-required@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=76, telegram_chat_id=76)
    agent = Agent(
        user_id=user.id,
        name="Researcher",
        kind="research",
        trigger_type="manual",
        config={"steps": [{"tool": "note", "args": {"text": "first"}}]},
    )
    db_session.add_all([account, agent])
    await db_session.commit()
    capture = _TelegramCapture()
    dispatched: list[str] = []
    monkeypatch.setattr(
        telegram_routes,
        "enqueue_agent_run",
        lambda run_id: dispatched.append(str(run_id)) or "task-objective",
    )

    await telegram_routes._handle_account_command(
        db_session,
        capture,
        message={"message_id": 408, "chat": {"id": 76}},
        account=account,
        intent="run",
        arg="Researcher",
    )

    assert "Формат: /run" in capture.messages[-1]["text"]
    assert dispatched == []
    runs = (await db_session.execute(select(AgentRun).where(AgentRun.user_id == user.id))).all()
    assert runs == []


@pytest.mark.asyncio
async def test_telegram_command_guards_missing_chat_inactive_user_and_short_refs(
    db_session: AsyncSession,
):
    user = await _user(db_session, "telegram-command-guards@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=83, telegram_chat_id=83)
    agent = Agent(
        user_id=user.id,
        name="Lookup",
        kind="research",
        trigger_type="manual",
        config={"steps": [{"tool": "note", "args": {"text": "lookup"}}]},
    )
    db_session.add_all([account, agent])
    await db_session.flush()
    run = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{agent.id}:lookup",
        trigger_kind="manual",
    )
    db_session.add(run)
    await db_session.commit()
    capture = _TelegramCapture()

    missing_chat_message = {"message_id": 501}
    await telegram_routes._handle_help_command(capture, message=missing_chat_message, linked=True)
    await telegram_routes._handle_meetings_command(
        db_session, capture, message=missing_chat_message, account=account
    )
    await telegram_routes._handle_search_command(
        db_session, capture, message=missing_chat_message, account=account, query="roadmap"
    )
    await telegram_routes._handle_settings_command(
        capture, message=missing_chat_message, linked=True
    )
    await telegram_routes._handle_agents_command(
        db_session, capture, message=missing_chat_message, account=account
    )
    await telegram_routes._handle_run_command(
        db_session, capture, message=missing_chat_message, account=account, arg="Lookup test"
    )
    await telegram_routes._handle_runs_command(
        db_session, capture, message=missing_chat_message, account=account
    )
    await telegram_routes._handle_run_status_command(
        db_session, capture, message=missing_chat_message, account=account, arg=str(run.id)
    )
    await telegram_routes._handle_cancel_run_command(
        db_session, capture, message=missing_chat_message, account=account, arg=str(run.id)
    )
    await telegram_routes._handle_approvals_command(
        db_session, capture, message=missing_chat_message, account=account
    )
    await telegram_routes._handle_approval_decision_command(
        db_session,
        capture,
        message=missing_chat_message,
        account=account,
        arg=str(uuid4()),
        decision="once",
    )
    await telegram_routes._handle_text_message(
        db_session,
        capture,
        message=missing_chat_message,
        account=account,
        text="hello",
    )
    await telegram_routes._handle_document_message(
        db_session,
        capture,
        message=missing_chat_message,
        account=account,
        document={"file_id": "file-id", "document_ext": "pdf"},
    )
    assert capture.messages == []

    message = {"message_id": 502, "chat": {"id": 83}}
    await telegram_routes._handle_account_command(
        db_session, capture, message=message, account=account, intent="help"
    )
    await telegram_routes._handle_account_command(
        db_session, capture, message=message, account=account, intent="settings"
    )
    assert "Telegram привязан" in capture.messages[-2]["text"]
    assert "Управление привязкой" in capture.messages[-1]["text"]

    user.account_status = "paused"
    await db_session.flush()
    await telegram_routes._handle_agents_command(
        db_session, capture, message=message, account=account
    )
    assert "сейчас не активен" in capture.messages[-1]["text"]

    user.account_status = "active"
    await db_session.flush()
    assert await telegram_routes._load_agent_ref(db_session, user_id=user.id, ref=" ") is None
    assert await telegram_routes._load_agent_ref(
        db_session, user_id=user.id, ref=str(agent.id)
    ) == agent
    assert await telegram_routes._load_agent_ref(
        db_session, user_id=user.id, ref=str(agent.id)[:8]
    ) == agent
    assert await telegram_routes._load_run_ref(
        db_session, user_id=user.id, ref=str(run.id)
    ) == run
    assert await telegram_routes._load_run_ref(
        db_session, user_id=user.id, ref="short"
    ) is None


@pytest.mark.asyncio
async def test_telegram_can_resolve_agent_pending_action(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-agent-approval@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=78, telegram_chat_id=78)
    agent = Agent(
        user_id=user.id,
        name="Messenger",
        kind="message",
        trigger_type="manual",
        config={
            "steps": [
                {
                    "tool": "propose_action",
                    "args": {
                        "kind": "send",
                        "tool_name": "send_message_telegram",
                        "action_args": {"text": "hello"},
                        "preview": "Send to you: hello",
                        "recipient_display": "you",
                    },
                }
            ]
        },
    )
    db_session.add_all([account, agent])
    await db_session.flush()
    run = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{agent.id}:telegram-approval",
        trigger_kind="manual",
    )
    db_session.add(run)
    await db_session.flush()
    await telegram_routes.run_job(
        db_session,
        run.id,
        planner=static_config_planner,
        executor=telegram_routes.execute_agent_step,
    )
    row = (
        await db_session.execute(
            select(CompanionPendingAction).where(CompanionPendingAction.agent_run_id == run.id)
        )
    ).scalar_one()
    capture = _TelegramCapture()

    class FakeTelegram:
        async def send_message(self, chat_id, text, **_kwargs):
            return {"message_id": 99, "chat_id": chat_id, "text": text}

    monkeypatch.setattr(companion_actuators, "TelegramBotClient", FakeTelegram)
    await telegram_routes._handle_account_command(
        db_session,
        capture,
        message={"message_id": 302, "chat": {"id": 78}},
        account=account,
        intent="approvals",
    )
    await telegram_routes._handle_account_command(
        db_session,
        capture,
        message={"message_id": 303, "chat": {"id": 78}},
        account=account,
        intent="approve_always",
        arg=str(row.id),
    )

    assert str(row.id) in capture.messages[0]["text"]
    assert f"/approve_always {row.id}" in capture.messages[0]["text"]
    assert "Выполнил действие" in capture.messages[1]["text"]
    await db_session.refresh(row)
    await db_session.refresh(run)
    assert row.status == "executed"
    assert row.decision == "always"
    assert run.status == "done"


@pytest.mark.asyncio
async def test_telegram_approvals_expires_stale_actions_before_listing(
    db_session: AsyncSession,
):
    user = await _user(db_session, "telegram-expired-approvals@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=84, telegram_chat_id=84)
    db_session.add(account)
    await db_session.flush()
    expired = await ca.propose_action(
        db_session,
        user_id=user.id,
        conversation_id=None,
        kind="send",
        tool_name="send_message_telegram",
        args={"text": "expired"},
        preview="expired",
        idempotency_key=f"expired:{uuid4().hex}",
        ttl_seconds=-1,
    )
    active = await ca.propose_action(
        db_session,
        user_id=user.id,
        conversation_id=None,
        kind="send",
        tool_name="send_message_telegram",
        args={"text": "active"},
        preview="active",
        idempotency_key=f"active:{uuid4().hex}",
    )
    await db_session.commit()
    capture = _TelegramCapture()

    await telegram_routes._handle_account_command(
        db_session,
        capture,
        message={"message_id": 304, "chat": {"id": 84}},
        account=account,
        intent="approvals",
    )

    assert str(active.id) in capture.messages[-1]["text"]
    assert str(expired.id) not in capture.messages[-1]["text"]
    await db_session.refresh(expired)
    assert expired.status == "expired"


@pytest.mark.asyncio
async def test_telegram_rejects_agent_approval_for_terminal_run(
    db_session: AsyncSession,
):
    user = await _user(db_session, "telegram-terminal-agent-approval@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=85, telegram_chat_id=85)
    agent = Agent(
        user_id=user.id,
        name="Terminal",
        kind="message",
        trigger_type="manual",
        config={"steps": [{"tool": "note", "args": {"text": "done"}}]},
    )
    db_session.add_all([account, agent])
    await db_session.flush()
    run = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{agent.id}:terminal-approval",
        trigger_kind="manual",
        status="done",
    )
    db_session.add(run)
    await db_session.flush()
    row = await ca.propose_action(
        db_session,
        user_id=user.id,
        conversation_id=None,
        agent_run_id=run.id,
        agent_step_idx=1,
        kind="send",
        tool_name="send_message_telegram",
        args={"text": "too late"},
        preview="Send too late",
        idempotency_key=f"terminal:{uuid4().hex}",
    )
    await db_session.commit()
    capture = _TelegramCapture()

    await telegram_routes._handle_account_command(
        db_session,
        capture,
        message={"message_id": 307, "chat": {"id": 85}},
        account=account,
        intent="approve",
        arg=str(row.id),
    )

    assert "запуск уже завершен" in capture.messages[-1]["text"]
    await db_session.refresh(row)
    assert row.status == "pending"


@pytest.mark.asyncio
async def test_telegram_can_reject_agent_pending_action(
    db_session: AsyncSession,
):
    user = await _user(db_session, "telegram-agent-reject@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=80, telegram_chat_id=80)
    agent = Agent(
        user_id=user.id,
        name="Messenger",
        kind="message",
        trigger_type="manual",
        config={
            "steps": [
                {
                    "tool": "propose_action",
                    "args": {
                        "kind": "send",
                        "tool_name": "send_message_telegram",
                        "action_args": {"text": "hello"},
                        "preview": "Send to you: hello",
                    },
                }
            ]
        },
    )
    db_session.add_all([account, agent])
    await db_session.flush()
    run = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{agent.id}:telegram-reject",
        trigger_kind="manual",
    )
    db_session.add(run)
    await db_session.flush()
    await telegram_routes.run_job(
        db_session,
        run.id,
        planner=static_config_planner,
        executor=telegram_routes.execute_agent_step,
    )
    row = (
        await db_session.execute(
            select(CompanionPendingAction).where(
                CompanionPendingAction.agent_run_id == run.id
            )
        )
    ).scalar_one()
    capture = _TelegramCapture()

    await telegram_routes._handle_account_command(
        db_session,
        capture,
        message={"message_id": 304, "chat": {"id": 80}},
        account=account,
        intent="reject",
        arg=str(row.id),
    )

    assert "Отклонил действие" in capture.messages[-1]["text"]
    await db_session.refresh(row)
    await db_session.refresh(run)
    assert row.status == "rejected"
    assert run.status == "failed"


@pytest.mark.asyncio
async def test_telegram_desktop_approval_dispatches_to_mac_edge(
    db_session: AsyncSession,
):
    user = await _user(db_session, "telegram-desktop-approval@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=81, telegram_chat_id=81)
    db_session.add(account)
    await db_session.flush()
    row = await ca.propose_action(
        db_session,
        user_id=user.id,
        conversation_id=None,
        kind="desktop_action",
        tool_name="desktop_open",
        args={"target": "https://wai.computer"},
        preview="Open WaiComputer",
        idempotency_key=f"desktop:{uuid4().hex}",
        device_target=str(uuid4()),
    )
    await db_session.flush()
    capture = _TelegramCapture()

    await telegram_routes._handle_account_command(
        db_session,
        capture,
        message={"message_id": 305, "chat": {"id": 81}},
        account=account,
        intent="approve",
        arg=str(row.id),
    )

    assert "Mac edge" in capture.messages[-1]["text"]
    await db_session.refresh(row)
    assert row.status == "approved"


@pytest.mark.asyncio
async def test_telegram_approval_reports_actuation_error(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-actuation-error@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=82, telegram_chat_id=82)
    db_session.add(account)
    await db_session.flush()
    row = await ca.propose_action(
        db_session,
        user_id=user.id,
        conversation_id=None,
        kind="send",
        tool_name="send_message_telegram",
        args={"text": "hello"},
        preview="Send hello",
        idempotency_key=f"send:{uuid4().hex}",
    )
    await db_session.flush()
    capture = _TelegramCapture()

    async def fail_execute_action(*_args, **_kwargs):
        raise telegram_routes.ActuationError("blocked", "telegram blocked")

    monkeypatch.setattr(telegram_routes, "execute_action", fail_execute_action)

    await telegram_routes._handle_account_command(
        db_session,
        capture,
        message={"message_id": 306, "chat": {"id": 82}},
        account=account,
        intent="approve",
        arg=str(row.id),
    )

    assert "Действие не выполнено: telegram blocked" in capture.messages[-1]["text"]
    await db_session.refresh(row)
    assert row.status == "failed"


@pytest.mark.asyncio
async def test_handle_update_routes_obligation_question_to_wai_agent(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-obligation-question@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=62, telegram_chat_id=62)
    db_session.add(account)
    db_session.add(
        TelegramUpdate(
            update_id=207,
            status="accepted",
            received_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()
    capture = _TelegramCapture()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(telegram_routes, "TelegramBotClient", lambda: capture)
    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)
    _stub_telegram_turn(
        monkeypatch,
        "Пока не могу ответить из твоего Brain.\nNo matching sources yet.",
    )

    await telegram_routes._handle_update(
        {
            "update_id": 207,
            "message": {
                "message_id": 207,
                "from": {"id": 62, "username": "mik"},
                "chat": {"id": 62, "type": "private"},
                "text": "что я обещал",
            },
        }
    )

    assert "Пока не могу ответить из твоего Brain." in capture.messages[-1]["text"]
    assert "No matching sources yet." in capture.messages[-1]["text"]
    assert (await db_session.get(TelegramUpdate, 207)).status == "completed"
    conversation = (
        await db_session.execute(select(Conversation).where(Conversation.user_id == user.id))
    ).scalar_one()
    assert conversation.title == "Telegram"


@pytest.mark.asyncio
async def test_handle_update_rejects_unsupported_document_even_with_caption(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-unsupported-document@example.com")
    db_session.add(TelegramAccount(user_id=user.id, telegram_user_id=63, telegram_chat_id=63))
    db_session.add(
        TelegramUpdate(
            update_id=208,
            status="accepted",
            received_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()
    capture = _TelegramCapture()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(telegram_routes, "TelegramBotClient", lambda: capture)
    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)

    await telegram_routes._handle_update(
        {
            "update_id": 208,
            "message": {
                "message_id": 208,
                "from": {"id": 63, "username": "mik"},
                "chat": {"id": 63, "type": "private"},
                "caption": "summarize this",
                "document": {
                    "file_id": "zip-id",
                    "file_name": "archive.zip",
                    "mime_type": "application/zip",
                },
            },
        }
    )

    assert "Не могу извлечь текст" in capture.messages[-1]["text"]
    assert (await db_session.get(TelegramUpdate, 208)).status == "completed"


@pytest.mark.asyncio
async def test_handle_update_rejects_private_data_in_group_chat(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-group@example.com")
    db_session.add(TelegramAccount(user_id=user.id, telegram_user_id=61, telegram_chat_id=61))
    db_session.add(
        TelegramUpdate(
            update_id=206,
            status="accepted",
            received_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()
    capture = _TelegramCapture()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(telegram_routes, "TelegramBotClient", lambda: capture)
    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)

    await telegram_routes._handle_update(
        {
            "update_id": 206,
            "message": {
                "message_id": 206,
                "from": {"id": 61, "username": "mik"},
                "chat": {"id": -10061, "type": "group"},
                "text": "покажи встречи",
            },
        }
    )

    assert "личный чат" in capture.messages[-1]["text"]
    assert (await db_session.get(TelegramUpdate, 206)).status == "completed"


@pytest.mark.asyncio
async def test_handle_start_command_consumes_pairing_and_ignores_invalid_messages(
    db_session: AsyncSession,
):
    user = await _user(db_session)
    raw_token = "pair-from-start"
    db_session.add(
        TelegramPairing(
            user_id=user.id,
            token_hash=telegram_routes._token_hash(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
    )
    await db_session.commit()
    capture = _TelegramCapture()

    await telegram_routes._handle_start_command(
        db_session,
        capture,
        message={
            "message_id": 8,
            "from": {"id": 321, "first_name": "Mik"},
            "chat": {"id": 321},
        },
        arg=f"{telegram_routes.PAIRING_PREFIX}{raw_token}",
    )
    await telegram_routes._handle_start_command(
        db_session,
        capture,
        message={"from": {"id": 321}},
        arg="",
    )
    await telegram_routes._handle_start_command(
        db_session,
        capture,
        message={"from": {"id": "bad"}, "chat": {"id": 321}},
        arg="",
    )

    assert "Готово" in capture.messages[0]["text"]
    assert await telegram_routes._load_account(db_session, 321) is not None


@pytest.mark.asyncio
async def test_bot_link_code_claims_telegram_account(
    db_session: AsyncSession,
    monkeypatch,
):
    monkeypatch.setattr(telegram_routes.settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(telegram_routes.settings, "telegram_webhook_secret_token", "secret")
    user = await _user(db_session)
    raw_code = "ABCD2345"
    db_session.add(
        TelegramBotLinkCode(
            token_hash=telegram_routes._token_hash(raw_code),
            telegram_user_id=444,
            telegram_chat_id=444,
            username="anna",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
    )
    await db_session.commit()

    status = await telegram_routes.claim_link_code(
        telegram_routes.TelegramLinkCodeClaimRequest(code="ABCD-2345"),
        user,
        db_session,
    )

    assert status.linked is True
    assert status.telegram_user_id == 444
    assert status.username == "anna"
    account = await telegram_routes._load_account(db_session, 444)
    assert account is not None
    code = (
        await db_session.execute(
            select(TelegramBotLinkCode).where(TelegramBotLinkCode.telegram_user_id == 444)
        )
    ).scalar_one()
    assert code.consumed_at is not None


@pytest.mark.asyncio
async def test_handle_text_message_reuses_wai_conversation(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session)
    account = TelegramAccount(user_id=user.id, telegram_user_id=42, telegram_chat_id=42)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()
    _stub_telegram_turn(
        monkeypatch,
        "Пока не могу ответить из твоего Brain.\nNo matching sources yet.",
    )

    await telegram_routes._handle_text_message(
        db_session,
        capture,
        message={"message_id": 10, "chat": {"id": 42}},
        account=account,
        text="Что я обещал?",
    )

    assert "Пока не могу ответить из твоего Brain." in capture.messages[-1]["text"]
    assert "No matching sources yet." in capture.messages[-1]["text"]
    conversation = (
        await db_session.execute(select(Conversation).where(Conversation.user_id == user.id))
    ).scalar_one()
    assert conversation.title == "Telegram"
    assert account.companion_conversation_id == conversation.id
    reused = await telegram_routes._ensure_telegram_conversation(db_session, account)
    assert reused.id == conversation.id


@pytest.mark.asyncio
async def test_ensure_telegram_conversation_refreshes_expired_account_columns(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session, "telegram-expired-account@example.com")
    conversation = Conversation(user_id=user.id, title="Telegram", scope={"source": "telegram"})
    db_session.add(conversation)
    await db_session.flush()
    account = TelegramAccount(
        user_id=user.id,
        telegram_user_id=4301,
        telegram_chat_id=4301,
        companion_conversation_id=conversation.id,
    )
    db_session.add(account)
    await db_session.commit()
    db_session.expire(account, ["user_id", "companion_conversation_id"])

    reused = await telegram_routes._ensure_telegram_conversation(db_session, account)

    assert reused.id == conversation.id


@pytest.mark.asyncio
async def test_handle_text_message_renders_action_proposals(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-action-event@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=67, telegram_chat_id=67)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()
    action_id = str(uuid4())

    async def fake_run_turn(*args, **kwargs):
        yield telegram_routes.TokenEvent(text="Могу сделать это.")
        yield telegram_routes.ActionProposedEvent(
            action_id=action_id,
            kind="send",
            tool="send_message_telegram",
            preview="Send to you: hello",
            recipient="you",
        )

    monkeypatch.setattr(telegram_routes, "run_turn", fake_run_turn)

    await telegram_routes._handle_text_message(
        db_session,
        capture,
        message={"message_id": 17, "chat": {"id": 67}},
        account=account,
        text="отправь сообщение",
    )

    # The answer is sent first, then the action arrives as an inline-button card
    # (no copy-paste "/approve <uuid>" command).
    assert "Могу сделать это." in capture.messages[0]["text"]
    proposal = capture.messages[-1]
    assert "Нужно подтверждение" in proposal["text"]
    assert "Send to you: hello" in proposal["text"]
    callbacks = {
        button["callback_data"]
        for button in proposal["reply_markup"]["inline_keyboard"][0]
    }
    assert callbacks == {
        f"act:once:{action_id}",
        f"act:always:{action_id}",
        f"act:reject:{action_id}",
    }


@pytest.mark.asyncio
async def test_handle_text_message_uses_active_recording_context(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-active-context@example.com")
    recording = Recording(
        user_id=user.id,
        title="Telegram Voice",
        type="note",
        status=RecordingStatus.READY.value,
    )
    db_session.add(recording)
    await db_session.flush()
    db_session.add(
        Summary(
            recording_id=recording.id,
            summary="Это саммари последнего голосового сообщения.",
        )
    )
    account = TelegramAccount(
        user_id=user.id,
        telegram_user_id=68,
        telegram_chat_id=68,
        active_context={
            "ref_type": "recording",
            "ref_id": str(recording.id),
            "title": recording.title,
            "source": "telegram",
        },
    )
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()
    contexts: list[Any] = []
    _stub_telegram_turn(
        monkeypatch,
        "Это саммари последнего голосового сообщения.",
        contexts,
    )

    await telegram_routes._handle_text_message(
        db_session,
        capture,
        message={"message_id": 18, "chat": {"id": 68}},
        account=account,
        text="?",
    )

    assert "Это саммари последнего голосового сообщения" in capture.messages[-1]["text"]
    assert contexts[0].viewing_recording_title == "Telegram Voice"
    conversation = (
        await db_session.execute(select(Conversation).where(Conversation.user_id == user.id))
    ).scalar_one()
    assert conversation.scope["recording_ids"] == [str(recording.id)]


@pytest.mark.asyncio
async def test_handle_text_message_does_not_route_ambiguous_prompt_without_context(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-ambiguous@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=69, telegram_chat_id=69)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()
    contexts: list[Any] = []
    _stub_telegram_turn(monkeypatch, "unexpected", contexts)

    await telegram_routes._handle_text_message(
        db_session,
        capture,
        message={"message_id": 19, "chat": {"id": 69}},
        account=account,
        text="?",
    )

    assert contexts == []
    assert "Напиши вопрос полностью" in capture.messages[-1]["text"]
    assert (
        await db_session.execute(select(AgentRun).where(AgentRun.user_id == user.id))
    ).all() == []


@pytest.mark.asyncio
async def test_handle_text_message_reports_pending_telegram_recording_context(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-pending-recording@example.com")
    account = TelegramAccount(
        user_id=user.id,
        telegram_user_id=70,
        telegram_chat_id=70,
        active_context={
            "ref_type": "pending_recording",
            "source": "telegram",
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()
    contexts: list[Any] = []
    _stub_telegram_turn(monkeypatch, "unexpected", contexts)

    await telegram_routes._handle_text_message(
        db_session,
        capture,
        message={"message_id": 20, "chat": {"id": 70}},
        account=account,
        text="?",
    )

    assert contexts == []
    assert "еще расшифровывается" in capture.messages[-1]["text"]
    assert (
        await db_session.execute(select(AgentRun).where(AgentRun.user_id == user.id))
    ).all() == []


def test_action_callback_parse_and_keyboard_roundtrip():
    aid = str(uuid4())
    keyboard = telegram_routes._action_inline_keyboard(aid)
    row = keyboard["inline_keyboard"][0]
    assert {b["callback_data"] for b in row} == {
        f"act:once:{aid}",
        f"act:always:{aid}",
        f"act:reject:{aid}",
    }
    # callback_data must stay under Telegram's 64-byte cap.
    for button in row:
        assert len(button["callback_data"].encode("utf-8")) <= 64
    assert telegram_routes._parse_action_callback(f"act:once:{aid}") == ("once", aid)
    assert telegram_routes._parse_action_callback(f"act:reject:{aid}") == ("reject", aid)
    assert telegram_routes._parse_action_callback("act:bogus:x") is None
    assert telegram_routes._parse_action_callback("nope:once:x") is None
    assert telegram_routes._parse_action_callback("act:once") is None


@pytest.mark.asyncio
async def test_handle_callback_query_approves_action(db_session: AsyncSession, monkeypatch):
    from app.core import companion_actuators
    from app.core.companion_actions import propose_action
    from app.models.companion import Conversation

    class _FakeTG:
        def __init__(self, *args, **kwargs):
            pass

        async def send_message(self, chat_id, text, **kwargs):
            return {"message_id": 1}

    monkeypatch.setattr(companion_actuators, "TelegramBotClient", _FakeTG)

    user = await _user(db_session, "telegram-callback-approve@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=991, telegram_chat_id=991)
    db_session.add(account)
    conv = Conversation(user_id=user.id)
    db_session.add(conv)
    await db_session.flush()
    row = await propose_action(
        db_session,
        user_id=user.id,
        conversation_id=conv.id,
        kind="send",
        tool_name="send_message_telegram",
        args={"text": "ping"},
        preview="Send to you: ping",
        idempotency_key=f"cb-{uuid4().hex}",
        recipient_display="you",
    )
    await db_session.flush()

    capture = _TelegramCapture()
    await telegram_routes._handle_callback_query(
        db_session,
        capture,
        callback_query={
            "id": "cbq-1",
            "from": {"id": 991},
            "data": f"act:once:{row.id}",
            "message": {"message_id": 55, "chat": {"id": 991}},
        },
    )

    assert capture.callback_answers[-1]["text"] == "Готово"
    assert "Готово" in capture.edited_messages[-1]["text"]
    await db_session.refresh(row)
    assert row.status == "executed"


@pytest.mark.asyncio
async def test_handle_callback_query_rejects_action(db_session: AsyncSession):
    from app.core.companion_actions import propose_action
    from app.models.companion import Conversation

    user = await _user(db_session, "telegram-callback-reject@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=992, telegram_chat_id=992)
    db_session.add(account)
    conv = Conversation(user_id=user.id)
    db_session.add(conv)
    await db_session.flush()
    row = await propose_action(
        db_session,
        user_id=user.id,
        conversation_id=conv.id,
        kind="send",
        tool_name="send_message_telegram",
        args={"text": "x"},
        preview="Send to you: x",
        idempotency_key=f"cbr-{uuid4().hex}",
        recipient_display="you",
    )
    await db_session.flush()

    capture = _TelegramCapture()
    await telegram_routes._handle_callback_query(
        db_session,
        capture,
        callback_query={
            "id": "cbq-2",
            "from": {"id": 992},
            "data": f"act:reject:{row.id}",
            "message": {"message_id": 56, "chat": {"id": 992}},
        },
    )

    assert capture.callback_answers[-1]["text"] == "Отклонено"
    await db_session.refresh(row)
    assert row.status == "rejected"


@pytest.mark.asyncio
async def test_telegram_client_builds_inline_button_payloads(monkeypatch):
    client = telegram_routes.TelegramBotClient(token="test-token")
    calls: list[tuple[str, dict]] = []

    async def fake_post(method, payload):
        calls.append((method, payload))
        return {"message_id": 1}

    monkeypatch.setattr(client, "_post", fake_post)

    keyboard = {"inline_keyboard": [[{"text": "A", "callback_data": "act:once:x"}]]}
    await client.send_message(5, "hi", reply_markup=keyboard)
    await client.answer_callback_query("cbq-9", text="Готово")
    await client.edit_message_text(5, 9, "done", reply_markup={"inline_keyboard": []})

    by_method = {method: payload for method, payload in calls}
    assert by_method["sendMessage"]["reply_markup"] == keyboard
    assert by_method["answerCallbackQuery"] == {
        "callback_query_id": "cbq-9",
        "text": "Готово",
    }
    assert by_method["editMessageText"]["message_id"] == 9
    assert by_method["editMessageText"]["reply_markup"] == {"inline_keyboard": []}


@pytest.mark.asyncio
async def test_handle_callback_query_handles_edge_cases(db_session: AsyncSession):
    capture = _TelegramCapture()
    # Unknown telegram user → prompt to link, no resolution.
    await telegram_routes._handle_callback_query(
        db_session,
        capture,
        callback_query={
            "id": "c1",
            "from": {"id": 424242},
            "data": "act:once:00000000-0000-0000-0000-000000000000",
            "message": {"chat": {"id": 1}, "message_id": 1},
        },
    )
    assert capture.callback_answers[-1]["text"] == "Сначала привяжи Telegram."

    user = await _user(db_session, "tg-cb-edge@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=4243, telegram_chat_id=4243)
    db_session.add(account)
    await db_session.flush()

    # Malformed callback data → silent ack (no crash, no resolution).
    await telegram_routes._handle_callback_query(
        db_session,
        capture,
        callback_query={
            "id": "c2",
            "from": {"id": 4243},
            "data": "garbage",
            "message": {"chat": {"id": 4243}, "message_id": 2},
        },
    )
    assert capture.callback_answers[-1] == {"id": "c2", "text": None}

    # Well-formed prefix but non-UUID id → silent ack.
    await telegram_routes._handle_callback_query(
        db_session,
        capture,
        callback_query={
            "id": "c3",
            "from": {"id": 4243},
            "data": "act:once:not-a-uuid",
            "message": {"chat": {"id": 4243}, "message_id": 3},
        },
    )
    assert capture.callback_answers[-1] == {"id": "c3", "text": None}

    # Missing data field entirely → silent ack.
    await telegram_routes._handle_callback_query(
        db_session,
        capture,
        callback_query={"id": "c4", "from": {"id": 4243}, "message": {"chat": {"id": 4243}}},
    )
    assert capture.callback_answers[-1] == {"id": "c4", "text": None}


@pytest.mark.asyncio
async def test_handle_callback_query_surfaces_expired_action(db_session: AsyncSession):
    from app.core.companion_actions import propose_action
    from app.models.companion import Conversation

    user = await _user(db_session, "tg-cb-expired@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=4244, telegram_chat_id=4244)
    db_session.add(account)
    conv = Conversation(user_id=user.id)
    db_session.add(conv)
    await db_session.flush()
    row = await propose_action(
        db_session,
        user_id=user.id,
        conversation_id=conv.id,
        kind="send",
        tool_name="send_message_telegram",
        args={"text": "x"},
        preview="Send to you: x",
        idempotency_key=f"exp-{uuid4().hex}",
        recipient_display="you",
        ttl_seconds=-10,  # already past TTL → timeout == deny
    )
    await db_session.flush()

    capture = _TelegramCapture()
    await telegram_routes._handle_callback_query(
        db_session,
        capture,
        callback_query={
            "id": "c5",
            "from": {"id": 4244},
            "data": f"act:once:{row.id}",
            "message": {"chat": {"id": 4244}, "message_id": 5},
        },
    )
    assert capture.callback_answers[-1]["text"] == "Не удалось"
    assert "Не смог" in capture.edited_messages[-1]["text"]


@pytest.mark.asyncio
async def test_handle_callback_query_reports_actuation_error(db_session: AsyncSession, monkeypatch):
    from app.core import companion_resolve
    from app.core.companion_actions import propose_action
    from app.core.companion_actuators import ActuationError
    from app.models.companion import Conversation

    async def boom(*args, **kwargs):
        raise ActuationError("send_failed", "boom")

    monkeypatch.setattr(companion_resolve, "execute_action", boom)

    user = await _user(db_session, "tg-cb-actuation@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=4245, telegram_chat_id=4245)
    db_session.add(account)
    conv = Conversation(user_id=user.id)
    db_session.add(conv)
    await db_session.flush()
    row = await propose_action(
        db_session,
        user_id=user.id,
        conversation_id=conv.id,
        kind="send",
        tool_name="send_message_telegram",
        args={"text": "x"},
        preview="Send to you: x",
        idempotency_key=f"act-{uuid4().hex}",
        recipient_display="you",
    )
    await db_session.flush()

    capture = _TelegramCapture()
    await telegram_routes._handle_callback_query(
        db_session,
        capture,
        callback_query={
            "id": "c6",
            "from": {"id": 4245},
            "data": f"act:once:{row.id}",
            "message": {"chat": {"id": 4245}, "message_id": 6},
        },
    )
    assert capture.callback_answers[-1]["text"] == "Ошибка"
    await db_session.refresh(row)
    assert row.status == "failed"


@pytest.mark.asyncio
async def test_handle_callback_query_dispatches_desktop_action(db_session: AsyncSession):
    from app.core.companion_actions import propose_action
    from app.models.companion import Conversation

    user = await _user(db_session, "tg-cb-desktop@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=4246, telegram_chat_id=4246)
    db_session.add(account)
    conv = Conversation(user_id=user.id)
    db_session.add(conv)
    await db_session.flush()
    row = await propose_action(
        db_session,
        user_id=user.id,
        conversation_id=conv.id,
        kind="desktop_action",
        tool_name="desktop_open",
        args={"target": "https://wai.computer"},
        preview="Open WaiComputer",
        idempotency_key=f"desk-{uuid4().hex}",
    )
    await db_session.flush()

    capture = _TelegramCapture()
    await telegram_routes._handle_callback_query(
        db_session,
        capture,
        callback_query={
            "id": "c7",
            "from": {"id": 4246},
            "data": f"act:once:{row.id}",
            "message": {"chat": {"id": 4246}, "message_id": 7},
        },
    )
    assert capture.callback_answers[-1]["text"] == "Отправлено на Mac"
    await db_session.refresh(row)
    assert row.status == "approved"  # dispatched to the Mac edge, awaiting report


@pytest.mark.asyncio
async def test_handle_text_message_empty_answer_and_missing_chat(
    db_session: AsyncSession,
):
    user = await _user(db_session)
    account = TelegramAccount(user_id=user.id, telegram_user_id=47, telegram_chat_id=47)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()

    await telegram_routes._handle_text_message(
        db_session,
        capture,
        message={"message_id": 15, "chat": {"id": 47}},
        account=account,
        text="пусто",
    )
    message_count = len(capture.messages)
    await telegram_routes._handle_text_message(
        db_session,
        capture,
        message={"message_id": 16},
        account=account,
        text="без чата",
    )

    assert len(capture.messages) == message_count
    assert capture.messages[-1]["text"]


@pytest.mark.asyncio
async def test_handle_text_message_reports_wai_errors(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session)
    account = TelegramAccount(user_id=user.id, telegram_user_id=43, telegram_chat_id=43)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()

    async def fail_wai_run(*args, **kwargs):
        raise RuntimeError("boom")
        if False:
            yield telegram_routes.TokenEvent(text="")

    monkeypatch.setattr(telegram_routes, "run_turn", fail_wai_run)
    await telegram_routes._handle_text_message(
        db_session,
        capture,
        message={"message_id": 11, "chat": {"id": 43}},
        account=account,
        text="сломайся",
    )

    assert "Не получилось обработать" in capture.messages[-1]["text"]


@pytest.mark.asyncio
async def test_handle_text_message_reports_retryable_provider_errors(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-retryable-turn@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=44, telegram_chat_id=44)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()

    async def fail_wai_run(*args, **kwargs):
        raise httpx.TimeoutException("provider timeout")
        if False:
            yield telegram_routes.TokenEvent(text="")

    monkeypatch.setattr(telegram_routes, "run_turn", fail_wai_run)
    await telegram_routes._handle_text_message(
        db_session,
        capture,
        message={"message_id": 12, "chat": {"id": 44}},
        account=account,
        text="привет",
    )

    assert "временный лимит провайдера" in capture.messages[-1]["text"]
    assert "Не получилось обработать" not in capture.messages[-1]["text"]


@pytest.mark.asyncio
async def test_format_wai_run_reply_surfaces_retrying_state(
    db_session: AsyncSession,
):
    user = await _user(db_session, "telegram-retrying-run@example.com")
    agent = Agent(
        user_id=user.id,
        name="Wai",
        kind="wai",
        trigger_type="chat",
    )
    db_session.add(agent)
    await db_session.flush()
    run = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"telegram:retry:{uuid4().hex}",
        trigger_kind="telegram",
        status="pending",
        error=f"{RETRYABLE_AGENT_ERROR_PREFIX}: RateLimitError",
    )
    db_session.add(run)
    await db_session.flush()

    text = await telegram_routes._format_wai_run_reply(db_session, run)

    assert "продолжает задачу" in text
    assert "RateLimitError" not in text
    assert "Не получилось выполнить" not in text


@pytest.mark.asyncio
async def test_handle_url_message_saves_links_and_reports_processing_edges(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-url@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=84, telegram_chat_id=84)
    db_session.add(account)
    await db_session.commit()

    missing_chat_capture = _TelegramCapture()
    await telegram_routes._handle_url_message(
        db_session,
        missing_chat_capture,
        message={"message_id": 601},
        account=account,
        url="https://example.com/missing-chat",
    )
    assert missing_chat_capture.messages == []

    async def fake_ingest_error(*_args, **_kwargs):
        return (
            SimpleNamespace(
                id=uuid4(),
                title="Broken link",
                state="raw",
                metadata_={},
            ),
            True,
        )

    async def fail_process(*_args, **_kwargs):
        raise RuntimeError("processor unavailable")

    capture = _TelegramCapture()
    monkeypatch.setattr(telegram_routes, "ingest_item", fake_ingest_error)
    monkeypatch.setattr(telegram_routes, "process_item", fail_process)
    await telegram_routes._handle_url_message(
        db_session,
        capture,
        message={"message_id": 602, "chat": {"id": 84}},
        account=account,
        url="https://example.com/broken",
    )
    assert "Сохранил ссылку, но не смог" in capture.messages[-1]["text"]

    async def fake_ingest_fetch_error(*_args, **_kwargs):
        return (
            SimpleNamespace(
                id=uuid4(),
                title="Private link",
                state="promoted",
                metadata_={"fetch_error": {"message": "Private post"}},
            ),
            False,
        )

    capture = _TelegramCapture()
    monkeypatch.setattr(telegram_routes, "ingest_item", fake_ingest_fetch_error)
    await telegram_routes._handle_url_message(
        db_session,
        capture,
        message={"message_id": 603, "chat": {"id": 84}},
        account=account,
        url="https://example.com/private",
    )
    assert capture.messages[-1]["text"] == "Private post"
    assert capture.messages[-1]["parse_mode"] == "HTML"

    async def fake_ingest_success(*_args, **_kwargs):
        return (
            SimpleNamespace(
                id=uuid4(),
                title="Saved link",
                state="promoted",
                metadata_={},
            ),
            False,
        )

    capture = _TelegramCapture()
    monkeypatch.setattr(telegram_routes, "ingest_item", fake_ingest_success)
    await telegram_routes._handle_url_message(
        db_session,
        capture,
        message={"message_id": 604, "chat": {"id": 84}},
        account=account,
        url="https://example.com/saved",
    )
    assert "<b>Saved link</b>" in capture.messages[-1]["text"]


@pytest.mark.asyncio
async def test_handle_media_message_imports_and_replies(
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    user = await _user(db_session)
    account = TelegramAccount(user_id=user.id, telegram_user_id=44, telegram_chat_id=44)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()
    pending = _wire_eager_media_enqueue(monkeypatch, db_session, capture, tmp_path)

    async def fake_import(**kwargs):
        assert kwargs["filename"] == "voice/file.ogg"
        assert kwargs["title"] is None
        assert kwargs["duration_seconds"] is None
        assert kwargs["source_label"] == "telegram"
        assert kwargs["source_path"] is not None and kwargs["source_path"].exists()
        for _ in range(20):
            if capture.actions:
                break
            await asyncio.sleep(0.01)
        assert capture.actions == [{"chat_id": 44, "action": "typing"}]
        return SimpleNamespace(
            recording=SimpleNamespace(title="Рефлексия 21 неделя 17 23 мая"),
            summary=SimpleNamespace(
                summary=(
                    "Что понравилось / достижения:\n"
                    "- Первый пункт\n\n"
                    "Что не понравилось / проблемы недели:\n"
                    "- Второй пункт"
                ),
                key_points=["Первый пункт", "Второй пункт"],
                decisions=[],
                topics=[],
                people_mentioned=[],
                sentiment="neutral",
            ),
            transcript="Полная расшифровка",
            transcript_document=(
                "00:00:00 Мик\nПолная расшифровка\n"
            ),
            speaker_names={"speaker_0": "Мик"},
        )

    monkeypatch.setattr(telegram_routes, "import_media_as_recording", fake_import)
    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 12, "chat": {"id": 44}},
        account=account,
        media={"kind": "voice", "file_id": "file-id"},
    )
    await asyncio.gather(*pending)

    assert "Расшифровываю" in capture.messages[0]["text"]
    assert capture.deleted_messages == [{"chat_id": 44, "message_id": 1}]
    assert capture.documents == [
        {
            "chat_id": 44,
            "filename": "refleksiya-21-nedelya-17-23-maya.txt",
            "data": "00:00:00 Мик\nПолная расшифровка\n".encode("utf-8"),
            "caption": None,
            "reply_to_message_id": 12,
        }
    ]
    assert capture.messages[-1]["text"].startswith("<b>Рефлексия 21 неделя 17 23 мая</b>")
    assert capture.messages[-1]["parse_mode"] == "HTML"
    assert "<b>Что понравилось / достижения:</b>" in capture.messages[-1]["text"]
    assert "Первый пункт" in capture.messages[-1]["text"]
    assert "Саммари" not in capture.messages[-1]["text"]
    assert "Расшифровка" not in capture.messages[-1]["text"]


@pytest.mark.asyncio
async def test_handle_media_message_marks_pending_context_before_import(
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    user = await _user(db_session, "telegram-media-pending@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=52, telegram_chat_id=52)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()
    pending = _wire_eager_media_enqueue(monkeypatch, db_session, capture, tmp_path)
    recording_id = uuid4()
    seen_contexts: list[dict[str, Any] | None] = []

    async def fake_import(**kwargs):
        seen_contexts.append(account.active_context)
        return SimpleNamespace(
            recording=SimpleNamespace(id=recording_id, title="Telegram Voice"),
            summary=None,
            transcript="",
        )

    monkeypatch.setattr(telegram_routes, "import_media_as_recording", fake_import)

    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 22, "chat": {"id": 52}},
        account=account,
        media={"kind": "voice", "file_id": "file-id"},
    )
    await asyncio.gather(*pending)

    assert seen_contexts[0]["ref_type"] == "pending_recording"
    assert seen_contexts[0]["source"] == "telegram"
    assert account.active_context["ref_type"] == "recording"
    assert account.active_context["ref_id"] == str(recording_id)


@pytest.mark.asyncio
async def test_handle_media_message_surfaces_unexpected_import_crash(
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    user = await _user(db_session, "telegram-media-crash@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=57, telegram_chat_id=57)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()
    pending = _wire_eager_media_enqueue(monkeypatch, db_session, capture, tmp_path)

    async def broken_import(**kwargs):
        raise RuntimeError("provider worker crashed")

    monkeypatch.setattr(telegram_routes, "import_media_as_recording", broken_import)

    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 23, "chat": {"id": 57}},
        account=account,
        media={"kind": "voice", "file_id": "file-id"},
    )
    await asyncio.gather(*pending)

    assert "Расшифровываю" in capture.messages[0]["text"]
    assert capture.messages[-1]["text"] == telegram_routes.TELEGRAM_RECORDING_IMPORT_ERROR_REPLY
    assert capture.messages[-1]["reply_to_message_id"] == 23
    assert capture.deleted_messages == [{"chat_id": 57, "message_id": 1}]
    assert account.active_context["ref_type"] == "recording_import_error"
    assert (
        account.active_context["message"]
        == telegram_routes.TELEGRAM_RECORDING_IMPORT_ERROR_REPLY
    )


@pytest.mark.asyncio
async def test_handle_document_message_imports_html_material_and_replies(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-doc@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=54, telegram_chat_id=54)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()
    capture.data = (
        b"<html><head><title>STT Benchmarks</title></head>"
        b"<body><h1>STT Benchmarks</h1>"
        b"<p>Deepgram and Whisper latency comparison.</p></body></html>"
    )
    capture.file = TelegramFile("file-id", "documents/stt-benchmarks-2026.html", len(capture.data))

    async def fake_embeddings(texts: list[str], **_: object) -> list[list[float]]:
        return [[0.03] * 1536 for _ in texts]

    async def fake_summarize(text, **kwargs):
        assert kwargs["content_kind"] == "article"
        assert "Deepgram and Whisper" in text
        return SummaryResult(
            title="STT Benchmarks 2026",
            summary="Сравнение моделей распознавания речи.",
            key_points=["Deepgram and Whisper are compared"],
            decisions=[],
            action_items=[],
            topics=["speech recognition"],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
            highlights=[],
        )

    async def fake_moments(text, **kwargs):
        return []

    monkeypatch.setattr("app.core.item_ingest.generate_embeddings", fake_embeddings)
    monkeypatch.setattr("app.core.item_processing.generate_embeddings", fake_embeddings)
    monkeypatch.setattr("app.core.item_summary.summarize_content", fake_summarize)
    monkeypatch.setattr("app.core.item_summary.extract_key_moments", fake_moments)

    await telegram_routes._handle_document_message(
        db_session,
        capture,
        message={"message_id": 23, "chat": {"id": 54}},
        account=account,
        document={
            "kind": "document",
            "file_id": "file-id",
            "file_unique_id": "unique-html",
            "file_name": "stt-benchmarks-2026.html",
            "mime_type": "text/html",
            "file_size": len(capture.data),
        },
    )

    item = (
        await db_session.execute(
            select(Item).where(Item.user_id == user.id, Item.source == "telegram")
        )
    ).scalar_one()
    assert item.kind == "article"
    assert item.title == "stt-benchmarks-2026"
    assert item.source_ref == "unique-html"
    summary = (
        await db_session.execute(select(ItemSummary).where(ItemSummary.item_id == item.id))
    ).scalar_one()
    assert summary.summary == "Сравнение моделей распознавания речи."
    assert "Извлекаю текст" in capture.messages[0]["text"]
    assert capture.deleted_messages == [{"chat_id": 54, "message_id": 1}]
    assert "<b>stt-benchmarks-2026</b>" in capture.messages[-1]["text"]
    assert "Сравнение моделей" in capture.messages[-1]["text"]


@pytest.mark.asyncio
async def test_handle_document_message_summarizes_every_supported_document_extension(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _user(db_session, "telegram-all-docs@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=5401, telegram_chat_id=5401)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()
    capture.data = b"converted document bytes"
    extracted: list[str] = []
    summarized: list[str] = []

    async def fake_embeddings(texts: list[str], **_: object) -> list[list[float]]:
        return [[0.03] * 1536 for _ in texts]

    async def fake_extract_document_text(ext: str, data: bytes) -> str:
        extracted.append(ext)
        assert data == capture.data
        return f"Readable {ext} document body"

    async def fake_summarize_and_embed_item(db: AsyncSession, item: Item) -> ItemSummary:
        ext = str((item.metadata_ or {})["telegram"]["ext"])
        summarized.append(ext)
        summary = ItemSummary(
            item_id=item.id,
            summary=f"Summary for {ext}",
            key_points=[],
            decisions=[],
            action_items=[],
            topics=[],
            people_mentioned=[],
            highlights=[],
            key_moments=[],
            sentiment="neutral",
        )
        db.add(summary)
        return summary

    monkeypatch.setattr("app.core.item_ingest.generate_embeddings", fake_embeddings)
    monkeypatch.setattr(telegram_routes, "extract_document_text", fake_extract_document_text)
    monkeypatch.setattr(
        telegram_routes,
        "summarize_and_embed_item",
        fake_summarize_and_embed_item,
    )

    for index, ext in enumerate(sorted(telegram_routes.SUPPORTED_DOCUMENT_EXTENSIONS), start=1):
        capture.file = TelegramFile("file-id", f"documents/sample-{index}.{ext}", len(capture.data))
        await telegram_routes._handle_document_message(
            db_session,
            capture,
            message={"message_id": index, "chat": {"id": 5401}},
            account=account,
            document={
                "kind": "document",
                "file_id": "file-id",
                "file_unique_id": f"unique-{ext}",
                "file_name": f"sample-{index}.{ext}",
                "mime_type": "application/octet-stream",
                "file_size": len(capture.data),
            },
        )

    expected_exts = sorted(telegram_routes.SUPPORTED_DOCUMENT_EXTENSIONS)
    assert extracted == expected_exts
    assert summarized == expected_exts
    assert "Summary for" in capture.messages[-1]["text"]
    assert "Не могу извлечь текст" not in "\n".join(message["text"] for message in capture.messages)


@pytest.mark.asyncio
async def test_handle_media_message_rejects_too_large_file(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session)
    account = TelegramAccount(user_id=user.id, telegram_user_id=45, telegram_chat_id=45)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()
    monkeypatch.setattr(telegram_routes.settings, "telegram_download_max_bytes", 2)

    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 13, "chat": {"id": 45}},
        account=account,
        media={"kind": "voice", "file_id": "file-id", "file_size": 3},
    )

    assert "слишком большой" in capture.messages[-1]["text"]


@pytest.mark.asyncio
async def test_handle_media_message_download_size_user_and_import_errors(
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    capture = _TelegramCapture()
    account = TelegramAccount(user_id=uuid4(), telegram_user_id=48, telegram_chat_id=48)
    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 17, "chat": {"id": 48}},
        account=account,
        media={"kind": "voice", "file_id": "file-id"},
    )
    assert "Аккаунт WaiComputer не найден" in capture.messages[-1]["text"]

    user = await _user(db_session, "media-errors@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=49, telegram_chat_id=49)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()
    pending = _wire_eager_media_enqueue(monkeypatch, db_session, capture, tmp_path)
    capture.file = TelegramFile("file-id", "voice/file.ogg", 999)
    monkeypatch.setattr(telegram_routes.settings, "telegram_download_max_bytes", 100)
    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 18, "chat": {"id": 49}},
        account=account,
        media={"kind": "voice", "file_id": "file-id"},
    )
    await asyncio.gather(*pending)
    assert "слишком большой" in capture.messages[-1]["text"]

    capture = _TelegramCapture()
    pending = _wire_eager_media_enqueue(monkeypatch, db_session, capture, tmp_path)
    capture.data = b"x" * 101
    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 19, "chat": {"id": 49}},
        account=account,
        media={"kind": "voice", "file_id": "file-id"},
    )
    await asyncio.gather(*pending)
    assert "слишком большой" in capture.messages[-1]["text"]

    async def broken_import(**kwargs):
        raise RecordingImportError("bad_media", "Не удалось импортировать.")

    capture = _TelegramCapture()
    pending = _wire_eager_media_enqueue(monkeypatch, db_session, capture, tmp_path)
    monkeypatch.setattr(telegram_routes.settings, "telegram_download_max_bytes", 1_000)
    monkeypatch.setattr(telegram_routes, "import_media_as_recording", broken_import)
    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 20, "chat": {"id": 49}, "caption": "Заголовок"},
        account=account,
        media={"kind": "voice", "file_id": "file-id", "file_name": "voice.ogg"},
    )
    await asyncio.gather(*pending)
    assert capture.messages[-1]["text"] == "Не удалось импортировать."


@pytest.mark.asyncio
async def test_handle_media_message_reports_hosted_telegram_file_limit(
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    user = await _user(db_session, "media-getfile-limit@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=50, telegram_chat_id=50)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()
    pending = _wire_eager_media_enqueue(monkeypatch, db_session, capture, tmp_path)

    async def get_file_too_big(file_id: str) -> TelegramFile:
        assert file_id == "file-id"
        raise TelegramClientError("Telegram getFile failed: Bad Request: file is too big")

    capture.get_file = get_file_too_big

    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 21, "chat": {"id": 50}},
        account=account,
        media={"kind": "audio", "file_id": "file-id", "file_name": "lecture.mp3"},
    )
    await asyncio.gather(*pending)

    assert "слишком большой" in capture.messages[-1]["text"]
    assert capture.deleted_messages == [{"chat_id": 50, "message_id": 1}]
    assert account.active_context["ref_type"] == "recording_import_error"


@pytest.mark.asyncio
async def test_handle_media_message_passes_telegram_duration_to_import(
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    user = await _user(db_session, "media-duration@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=51, telegram_chat_id=51)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()
    pending = _wire_eager_media_enqueue(monkeypatch, db_session, capture, tmp_path)
    seen: dict[str, Any] = {}

    async def fake_import(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            recording=SimpleNamespace(title=""),
            summary=None,
            transcript="",
        )

    monkeypatch.setattr(telegram_routes, "import_media_as_recording", fake_import)

    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 21, "chat": {"id": 51}},
        account=account,
        media={"kind": "audio", "file_id": "file-id", "duration": 3600},
    )
    await asyncio.gather(*pending)

    assert seen["duration_seconds"] == 3600
    # No transcript came back -> the bot says so instead of pretending success.
    assert "не слышно речи" in capture.messages[-1]["text"]


@pytest.mark.asyncio
async def test_handle_document_message_reports_streaming_size_limit(
    db_session: AsyncSession,
):
    user = await _user(db_session, "telegram-doc-large@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=55, telegram_chat_id=55)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()
    capture.download_file = AsyncMock(
        side_effect=TelegramFileTooLargeError("Telegram file exceeds configured limit")
    )

    await telegram_routes._handle_document_message(
        db_session,
        capture,
        message={"message_id": 24, "chat": {"id": 55}},
        account=account,
        document={
            "kind": "document",
            "file_id": "file-id",
            "file_unique_id": "unique-pdf",
            "file_name": "large.pdf",
            "mime_type": "application/pdf",
        },
    )

    assert "слишком большой" in capture.messages[-1]["text"]


@pytest.mark.asyncio
async def test_handle_document_message_reports_validation_extraction_and_processing_edges(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "telegram-doc-edges@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=56, telegram_chat_id=56)
    db_session.add(account)
    await db_session.commit()
    message = {"message_id": 25, "chat": {"id": 56}}

    capture = _TelegramCapture()
    await telegram_routes._handle_document_message(
        db_session,
        capture,
        message={"message_id": 26},
        account=account,
        document={"file_id": "file-id", "document_ext": "pdf"},
    )
    await telegram_routes._handle_document_message(
        db_session,
        capture,
        message=message,
        account=account,
        document={"file_id": 42, "document_ext": "pdf"},
    )
    assert capture.messages == []

    capture = _TelegramCapture()
    await telegram_routes._handle_document_message(
        db_session,
        capture,
        message=message,
        account=account,
        document={"file_id": "file-id", "document_ext": "zip", "file_name": "archive.zip"},
    )
    assert "Не могу извлечь текст" in capture.messages[-1]["text"]

    capture = _TelegramCapture()
    monkeypatch.setattr(telegram_routes.settings, "telegram_download_max_bytes", 2)
    await telegram_routes._handle_document_message(
        db_session,
        capture,
        message=message,
        account=account,
        document={
            "file_id": "file-id",
            "document_ext": "pdf",
            "file_name": "large.pdf",
            "file_size": 3,
        },
    )
    assert "слишком большой" in capture.messages[-1]["text"]

    capture = _TelegramCapture()
    capture.file = TelegramFile("file-id", "large.pdf", 3)
    await telegram_routes._handle_document_message(
        db_session,
        capture,
        message=message,
        account=account,
        document={"file_id": "file-id", "document_ext": "pdf", "file_name": "large.pdf"},
    )
    assert "слишком большой" in capture.messages[-1]["text"]

    capture = _TelegramCapture()
    capture.file = TelegramFile("file-id", "large.pdf", 1)

    async def over_limit_download(*_args, **_kwargs):
        return b"abc"

    capture.download_file = over_limit_download
    await telegram_routes._handle_document_message(
        db_session,
        capture,
        message=message,
        account=account,
        document={"file_id": "file-id", "document_ext": "pdf", "file_name": "large.pdf"},
    )
    assert "слишком большой" in capture.messages[-1]["text"]

    monkeypatch.setattr(telegram_routes.settings, "telegram_download_max_bytes", 1_000)

    async def fail_extract(_ext: str, _data: bytes) -> str:
        raise telegram_routes.DocumentExtractionError("bad_pdf", "PDF is encrypted.")

    capture = _TelegramCapture()
    monkeypatch.setattr(telegram_routes, "extract_document_text", fail_extract)
    await telegram_routes._handle_document_message(
        db_session,
        capture,
        message=message,
        account=account,
        document={"file_id": "file-id", "document_ext": "pdf", "file_name": "locked.pdf"},
    )
    assert "PDF is encrypted" in capture.messages[-1]["text"]

    async def extract_text(_ext: str, _data: bytes) -> str:
        return "Readable document"

    async def fail_ingest(*_args, **_kwargs):
        raise RuntimeError("db unavailable")

    capture = _TelegramCapture()
    monkeypatch.setattr(telegram_routes, "extract_document_text", extract_text)
    monkeypatch.setattr(telegram_routes, "ingest_item", fail_ingest)
    await telegram_routes._handle_document_message(
        db_session,
        capture,
        message=message,
        account=account,
        document={"file_id": "file-id", "document_ext": "pdf", "file_name": "save.pdf"},
    )
    assert "Не смог сохранить файл" in capture.messages[-1]["text"]

    async def fake_ingest(*_args, **_kwargs):
        return (
            SimpleNamespace(
                id=uuid4(),
                title="Saved document",
                state="raw",
                metadata_={},
            ),
            True,
        )

    async def fail_summary(*_args, **_kwargs):
        raise RuntimeError("summary unavailable")

    capture = _TelegramCapture()
    monkeypatch.setattr(telegram_routes, "ingest_item", fake_ingest)
    monkeypatch.setattr(telegram_routes, "summarize_and_embed_item", fail_summary)
    await telegram_routes._handle_document_message(
        db_session,
        capture,
        message=message,
        account=account,
        document={"file_id": "file-id", "document_ext": "pdf", "file_name": "summary.pdf"},
    )
    assert "не смог сделать краткое содержание" in capture.messages[-1]["text"]


@pytest.mark.asyncio
async def test_handle_media_message_ignores_missing_chat_or_file_id(
    db_session: AsyncSession,
):
    user = await _user(db_session, "media-ignore@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=50, telegram_chat_id=50)
    capture = _TelegramCapture()

    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 21},
        account=account,
        media={"kind": "voice", "file_id": "file-id"},
    )
    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 22, "chat": {"id": 50}},
        account=account,
        media={"kind": "voice"},
    )

    assert capture.messages == []


@pytest.mark.asyncio
async def test_handle_update_processes_linked_text_message(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session)
    db_session.add(TelegramAccount(user_id=user.id, telegram_user_id=46, telegram_chat_id=46))
    db_session.add(
        TelegramUpdate(
            update_id=100,
            status="accepted",
            received_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()
    capture = _TelegramCapture()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(telegram_routes, "TelegramBotClient", lambda: capture)
    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)
    _stub_telegram_turn(
        monkeypatch,
        "Пока не могу ответить из твоего Brain.\nNo matching sources yet.",
    )

    await telegram_routes._handle_update(
        {
            "update_id": 100,
            "message": {
                "message_id": 14,
                "from": {"id": 46, "username": "mik"},
                "chat": {"id": 46},
                "text": "вопрос",
            },
        }
    )

    assert "Пока не могу ответить из твоего Brain." in capture.messages[-1]["text"]
    assert "No matching sources yet." in capture.messages[-1]["text"]
    assert (
        await db_session.execute(select(Conversation).where(Conversation.user_id == user.id))
    ).scalar_one()
    update = await db_session.get(TelegramUpdate, 100)
    assert update.status == "completed"


# --- cross-modal voice intent routing (via _handle_update) ---


def _fake_transcribed(text: str):
    from pathlib import Path

    from app.core.recording_import import TranscribedMedia

    return TranscribedMedia(
        transcript_results=[
            TranscriptResult(
                text=text, speaker=None, is_final=True, start_ms=0, end_ms=1000, confidence=0.9
            )
        ],
        # discard() tolerates an already-missing file, so no fixture needed.
        media_path=Path("/tmp/telegram-intent-test.ogg"),
        media_content_type="audio/ogg",
        media_ext="ogg",
    )


def _wire_eager_media_enqueue(monkeypatch, db_session, capture, tmp_path):
    """Run the real Telegram media-import worker coroutine inline when the
    webhook enqueues it (Celery eager mode), using the test's capture client
    and DB session. Returns the list of scheduled tasks — await them after the
    handler returns."""

    from app.tasks import telegram_media_import as tmi
    from app.tasks.celery_app import celery_app as real_celery_app

    pending: list = []

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    real_settings = telegram_routes.settings
    monkeypatch.setattr(tmi, "get_db_context", fake_db_context)
    monkeypatch.setattr(tmi, "TelegramBotClient", lambda: capture)
    monkeypatch.setattr(
        tmi,
        "get_settings",
        lambda: SimpleNamespace(
            upload_staging_dir=str(tmp_path),
            telegram_download_max_bytes=real_settings.telegram_download_max_bytes,
        ),
    )

    def fake_send_task(name, kwargs=None, **_):
        assert name == "app.tasks.telegram_media_import.import_telegram_media"
        # Unscheduled coroutine: the test awaits it AFTER the webhook handler
        # finishes, so the shared test session never sees concurrent use.
        pending.append(tmi._run(**kwargs))

    monkeypatch.setattr(real_celery_app, "send_task", fake_send_task)
    return pending


def _wire_voice_routing(
    monkeypatch,
    db_session,
    capture,
    tmp_path=None,
    *,
    transcript="сколько будет один плюс два",
    decision=None,
    classify_raises=False,
):
    """Stub the heavy steps so _route_media_message can be driven end-to-end:
    transcription, classification, recording import, and the agent turn. The
    metadata file route enqueues the media-import worker; run it eagerly so
    those tests still observe the import."""
    import tempfile

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(telegram_routes, "TelegramBotClient", lambda: capture)
    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)

    transcribe_mock = AsyncMock(return_value=_fake_transcribed(transcript))
    monkeypatch.setattr(telegram_routes, "transcribe_media_bytes", transcribe_mock)

    import_mock = AsyncMock(
        return_value=SimpleNamespace(
            recording=SimpleNamespace(id=uuid4(), title="Запись"),
            summary=None,
            transcript="",
        )
    )
    monkeypatch.setattr(telegram_routes, "import_media_as_recording", import_mock)

    async def fake_classify(_transcript, **_kwargs):
        if classify_raises:
            raise AssertionError("classifier must not be called")
        return decision or telegram_routes.VoiceRouteDecision("message", "assistant_high")

    classify_mock = AsyncMock(side_effect=fake_classify)
    monkeypatch.setattr(telegram_routes, "classify_voice_transcript", classify_mock)

    from pathlib import Path as _Path

    pending = _wire_eager_media_enqueue(
        monkeypatch,
        db_session,
        capture,
        _Path(tmp_path) if tmp_path is not None else _Path(tempfile.mkdtemp()),
    )

    return SimpleNamespace(
        transcribe=transcribe_mock,
        import_=import_mock,
        classify=classify_mock,
        pending=pending,
    )


def _voice_update(update_id: int, *, tid: int = 51, extra=None):
    message = {
        "message_id": update_id,
        "from": {"id": tid},
        "chat": {"id": tid, "type": "private"},
        "voice": {"file_id": "file-id"},
    }
    if extra:
        message.update(extra)
    return {"update_id": update_id, "message": message}


def _accepted_update(update_id: int) -> TelegramUpdate:
    return TelegramUpdate(
        update_id=update_id, status="accepted", received_at=datetime.now(timezone.utc)
    )


async def _voice_account(db_session, telegram_user_id=51):
    user = await _user(db_session, f"voice-{telegram_user_id}@example.com")
    db_session.add(
        TelegramAccount(
            user_id=user.id, telegram_user_id=telegram_user_id, telegram_chat_id=telegram_user_id
        )
    )
    return user


@pytest.mark.asyncio
async def test_short_voice_command_routes_to_agent_not_library(db_session, monkeypatch):
    await _voice_account(db_session)
    db_session.add(_accepted_update(300))
    await db_session.commit()
    capture = _TelegramCapture()
    contexts: list[Any] = []
    mocks = _wire_voice_routing(monkeypatch, db_session, capture)
    _stub_telegram_turn(monkeypatch, "1 + 2 = 3", contexts)

    await telegram_routes._handle_update(_voice_update(300))

    # Answered by the agent, NOT filed as a recording.
    mocks.import_.assert_not_called()
    assert any("1 + 2 = 3" in m["text"] for m in capture.messages)
    # The transcript is echoed back for transparency.
    assert any(m["text"].startswith("🎙") for m in capture.messages)
    # The agent is told the message arrived as a voice note.
    assert contexts and contexts[0].input_modality == "voice"
    assert (await db_session.get(TelegramUpdate, 300)).status == "completed"


@pytest.mark.asyncio
async def test_short_voice_note_is_filed_as_recording(db_session, monkeypatch):
    await _voice_account(db_session, 52)
    db_session.add(_accepted_update(301))
    await db_session.commit()
    capture = _TelegramCapture()
    mocks = _wire_voice_routing(
        monkeypatch,
        db_session,
        capture,
        transcript="сегодня обсудили роадмап и решили перенести релиз",
        decision=telegram_routes.VoiceRouteDecision("file", "library_high"),
    )
    _stub_telegram_turn(monkeypatch, "should not run")

    await telegram_routes._handle_update(_voice_update(301, tid=52))

    # Filed, reusing the transcript we already produced (precomputed passed through).
    mocks.import_.assert_awaited_once()
    assert mocks.import_.await_args.kwargs["precomputed"] is not None


@pytest.mark.asyncio
async def test_forwarded_voice_is_filed_without_classification(db_session, monkeypatch):
    await _voice_account(db_session, 53)
    db_session.add(_accepted_update(302))
    await db_session.commit()
    capture = _TelegramCapture()
    mocks = _wire_voice_routing(monkeypatch, db_session, capture, classify_raises=True)

    await telegram_routes._handle_update(
        _voice_update(302, tid=53, extra={"forward_origin": {"type": "user"}})
    )
    await asyncio.gather(*mocks.pending)

    mocks.classify.assert_not_called()
    mocks.transcribe.assert_not_called()  # metadata alone decided: file
    mocks.import_.assert_awaited_once()
    assert mocks.import_.await_args.kwargs.get("precomputed") is None


@pytest.mark.asyncio
async def test_long_voice_is_filed_without_classification(db_session, monkeypatch):
    await _voice_account(db_session, 54)
    db_session.add(_accepted_update(303))
    await db_session.commit()
    capture = _TelegramCapture()
    mocks = _wire_voice_routing(monkeypatch, db_session, capture, classify_raises=True)

    await telegram_routes._handle_update(
        _voice_update(303, tid=54, extra={"voice": {"file_id": "file-id", "duration": 600}})
    )
    await asyncio.gather(*mocks.pending)

    mocks.classify.assert_not_called()
    mocks.import_.assert_awaited_once()


@pytest.mark.asyncio
async def test_voice_reply_to_bot_routes_to_agent(db_session, monkeypatch):
    await _voice_account(db_session, 55)
    db_session.add(_accepted_update(304))
    await db_session.commit()
    capture = _TelegramCapture()
    contexts: list[Any] = []
    mocks = _wire_voice_routing(monkeypatch, db_session, capture, classify_raises=True)
    _stub_telegram_turn(monkeypatch, "ответ", contexts)

    await telegram_routes._handle_update(
        _voice_update(
            304,
            tid=55,
            extra={"reply_to_message": {"message_id": 9, "from": {"id": 1, "is_bot": True}}},
        )
    )

    # Reply to the bot is conversational by metadata alone — no classifier call.
    mocks.classify.assert_not_called()
    mocks.import_.assert_not_called()
    assert contexts and contexts[0].is_reply_to_assistant is True


@pytest.mark.asyncio
async def test_recent_assistant_text_returns_last_bot_message(db_session: AsyncSession):
    user = await _user(db_session, "recent-asst@example.com")
    conv = Conversation(user_id=user.id, title="Telegram", scope={"source": "telegram"})
    db_session.add(conv)
    await db_session.flush()
    account = TelegramAccount(
        user_id=user.id,
        telegram_user_id=70,
        telegram_chat_id=70,
        companion_conversation_id=conv.id,
    )
    db_session.add(account)
    base = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    db_session.add(
        ChatMessage(
            conversation_id=conv.id,
            role="assistant",
            content="first answer",
            created_at=base,
        )
    )
    db_session.add(
        ChatMessage(
            conversation_id=conv.id,
            role="user",
            content="a question",
            created_at=base + timedelta(minutes=1),
        )
    )
    db_session.add(
        ChatMessage(
            conversation_id=conv.id,
            role="assistant",
            content="Which meeting — yesterday's or today's?",
            created_at=base + timedelta(minutes=2),
        )
    )
    await db_session.commit()

    text = await telegram_routes._recent_assistant_text(db_session, account)
    assert text == "Which meeting — yesterday's or today's?"


@pytest.mark.asyncio
async def test_recent_assistant_text_none_without_conversation(db_session: AsyncSession):
    user = await _user(db_session, "recent-asst-none@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=71, telegram_chat_id=71)
    db_session.add(account)
    await db_session.flush()
    assert await telegram_routes._recent_assistant_text(db_session, account) is None


@pytest.mark.asyncio
async def test_handle_update_branches_and_failures(db_session: AsyncSession, monkeypatch):
    user = await _user(db_session, "update-branches@example.com")
    db_session.add(TelegramAccount(user_id=user.id, telegram_user_id=51, telegram_chat_id=51))
    for update_id in (101, 102, 103, 104, 105, 106, 107):
        db_session.add(
            TelegramUpdate(
                update_id=update_id,
                status="accepted",
                received_at=datetime.now(timezone.utc),
            )
        )
    await db_session.commit()
    capture = _TelegramCapture()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    async def fake_media(*args, **kwargs):
        raise TelegramClientError("telegram failed")

    monkeypatch.setattr(telegram_routes, "TelegramBotClient", lambda: capture)
    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)
    # _handle_update dispatches media through _route_media_message (the intent gate).
    monkeypatch.setattr(telegram_routes, "_route_media_message", fake_media)

    await telegram_routes._handle_update({"update_id": "bad"})
    await telegram_routes._handle_update({"update_id": 101})
    await telegram_routes._handle_update({"update_id": 102, "message": {"chat": {"id": 51}}})
    await telegram_routes._handle_update(
        {"update_id": 103, "message": {"from": {"id": "bad"}, "chat": {"id": 51}}}
    )
    await telegram_routes._handle_update(
        {
            "update_id": 104,
            "message": {
                "message_id": 23,
                "from": {"id": 999},
                "chat": {"id": 999},
                "text": "unlinked",
            },
        }
    )
    await telegram_routes._handle_update(
        {
            "update_id": 105,
            "message": {
                "message_id": 24,
                "from": {"id": 51},
                "chat": {"id": 51},
                "text": "/unknown",
            },
        }
    )
    await telegram_routes._handle_update(
        {
            "update_id": 106,
            "message": {
                "message_id": 25,
                "from": {"id": 51},
                "chat": {"id": 51},
                "voice": {"file_id": "file-id"},
            },
        }
    )
    monkeypatch.setattr(
        telegram_routes,
        "_route_media_message",
        AsyncMock(side_effect=ValueError("boom")),
    )
    await telegram_routes._handle_update(
        {
            "update_id": 107,
            "message": {
                "message_id": 26,
                "from": {"id": 51},
                "chat": {"id": 51},
                "voice": {"file_id": "file-id"},
            },
        }
    )

    assert (await db_session.get(TelegramUpdate, 101)).status == "completed"
    assert (await db_session.get(TelegramUpdate, 102)).status == "completed"
    assert (await db_session.get(TelegramUpdate, 103)).status == "completed"
    # Unlinked user's first message -> Telegram-only signup consent prompt.
    assert "Условия" in capture.messages[0]["text"]
    assert "/meetings" in capture.messages[1]["text"]
    failed = await db_session.get(TelegramUpdate, 106)
    assert failed.status == "failed"
    assert failed.error_code == "TelegramClientError"
    internal_failed = await db_session.get(TelegramUpdate, 107)
    assert internal_failed.status == "failed"
    assert internal_failed.error_code == "internal_error"
    assert capture.messages[-1]["chat_id"] == 51
    assert capture.messages[-1]["reply_to_message_id"] == 26
    assert capture.messages[-1]["text"] == telegram_routes.TELEGRAM_RECORDING_IMPORT_ERROR_REPLY


@pytest.mark.asyncio
async def test_handle_update_deletes_pending_media_status_on_internal_error(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "media-internal-error@example.com")
    account = TelegramAccount(
        user_id=user.id,
        telegram_user_id=72,
        telegram_chat_id=72,
        active_context={
            "ref_type": "pending_recording",
            "status_message_id": 44,
        },
    )
    db_session.add(account)
    db_session.add(
        TelegramUpdate(
            update_id=400,
            status="accepted",
            received_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()
    capture = _TelegramCapture()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(telegram_routes, "TelegramBotClient", lambda: capture)
    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)
    monkeypatch.setattr(
        telegram_routes,
        "_route_media_message",
        AsyncMock(side_effect=ValueError("boom")),
    )

    await telegram_routes._handle_update(
        {
            "update_id": 400,
            "message": {
                "message_id": 40,
                "from": {"id": 72},
                "chat": {"id": 72},
                "voice": {"file_id": "file-id"},
            },
        }
    )

    update = await db_session.get(TelegramUpdate, 400)
    await db_session.refresh(account)
    assert update.status == "failed"
    assert update.error_code == "internal_error"
    assert capture.messages[-1]["chat_id"] == 72
    assert capture.messages[-1]["reply_to_message_id"] == 40
    assert capture.messages[-1]["text"] == telegram_routes.TELEGRAM_RECORDING_IMPORT_ERROR_REPLY
    assert capture.deleted_messages == [{"chat_id": 72, "message_id": 44}]
    assert account.active_context["ref_type"] == "recording_import_error"


@pytest.mark.asyncio
async def test_notify_telegram_internal_error_helper_guards_and_failures(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "notify-internal-error@example.com")
    account = TelegramAccount(
        user_id=user.id,
        telegram_user_id=73,
        telegram_chat_id=73,
        active_context={"ref_type": "recording", "status_message_id": 55},
    )
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()

    assert telegram_routes._pending_recording_status_message_id(None) is None
    assert telegram_routes._pending_recording_status_message_id(account) is None

    await telegram_routes._notify_telegram_internal_error(
        db_session,
        capture,
        message=None,
        account=account,
        status_message_id=55,
    )
    await telegram_routes._notify_telegram_internal_error(
        db_session,
        capture,
        message={"message_id": 41},
        account=account,
        status_message_id=55,
    )
    assert capture.messages == []
    assert capture.deleted_messages == []

    async def fail_context(*args, **kwargs):
        raise RuntimeError("context failed")

    monkeypatch.setattr(telegram_routes, "_set_telegram_import_error_context", fail_context)
    await telegram_routes._notify_telegram_internal_error(
        db_session,
        capture,
        message={"message_id": 42, "chat": {"id": 73}},
        account=account,
        status_message_id=55,
    )
    assert capture.messages[-1]["text"] == telegram_routes.TELEGRAM_RECORDING_IMPORT_ERROR_REPLY
    assert capture.deleted_messages == [{"chat_id": 73, "message_id": 55}]

    class TelegramSendFailure(_TelegramCapture):
        async def send_message(self, *args, **kwargs):
            raise TelegramClientError("send failed")

    failed_send = TelegramSendFailure()
    await telegram_routes._notify_telegram_internal_error(
        db_session,
        failed_send,
        message={"message_id": 43, "chat": {"id": 73}},
        account=None,
        status_message_id=56,
    )
    assert failed_send.deleted_messages == [{"chat_id": 73, "message_id": 56}]

    class TelegramSendCrash(_TelegramCapture):
        async def send_message(self, *args, **kwargs):
            raise RuntimeError("send crashed")

    crashed_send = TelegramSendCrash()
    await telegram_routes._notify_telegram_internal_error(
        db_session,
        crashed_send,
        message={"message_id": 44, "chat": {"id": 73}},
        account=None,
        status_message_id=57,
    )
    assert crashed_send.deleted_messages == [{"chat_id": 73, "message_id": 57}]


@pytest.mark.asyncio
async def test_handle_update_internal_error_rolls_back_inactive_session(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "inactive-error@example.com")
    db_session.add(TelegramAccount(user_id=user.id, telegram_user_id=74, telegram_chat_id=74))
    db_session.add(
        TelegramUpdate(
            update_id=401,
            status="accepted",
            received_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()
    capture = _TelegramCapture()

    class InactiveSessionProxy:
        is_active = False

        def __init__(self, session: AsyncSession) -> None:
            self.session = session
            self.rollback_called = False

        def __getattr__(self, name: str):
            return getattr(self.session, name)

        async def rollback(self) -> None:
            self.rollback_called = True
            await self.session.rollback()

    proxy = InactiveSessionProxy(db_session)

    @asynccontextmanager
    async def fake_db_context():
        yield proxy

    monkeypatch.setattr(telegram_routes, "TelegramBotClient", lambda: capture)
    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)
    monkeypatch.setattr(
        telegram_routes,
        "_route_media_message",
        AsyncMock(side_effect=ValueError("boom")),
    )

    await telegram_routes._handle_update(
        {
            "update_id": 401,
            "message": {
                "message_id": 45,
                "from": {"id": 74},
                "chat": {"id": 74},
                "voice": {"file_id": "file-id"},
            },
        }
    )

    update = await db_session.get(TelegramUpdate, 401)
    assert proxy.rollback_called is True
    assert update.status == "failed"
    assert update.error_code == "internal_error"
    assert capture.messages[-1]["text"] == telegram_routes.TELEGRAM_RECORDING_IMPORT_ERROR_REPLY

    await telegram_routes._mark_update(db_session, 999_999, "failed")


@pytest.mark.asyncio
async def test_handle_update_internal_text_error_does_not_send_recording_import_reply(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "text-internal-error@example.com")
    db_session.add(TelegramAccount(user_id=user.id, telegram_user_id=75, telegram_chat_id=75))
    db_session.add(
        TelegramUpdate(
            update_id=402,
            status="accepted",
            received_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()
    capture = _TelegramCapture()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(telegram_routes, "TelegramBotClient", lambda: capture)
    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)
    monkeypatch.setattr(
        telegram_routes,
        "_route_text_like",
        AsyncMock(side_effect=ValueError("text boom")),
    )

    await telegram_routes._handle_update(
        {
            "update_id": 402,
            "message": {
                "message_id": 46,
                "from": {"id": 75},
                "chat": {"id": 75},
                "text": "find this",
            },
        }
    )

    update = await db_session.get(TelegramUpdate, 402)
    assert update.status == "failed"
    assert update.error_code == "internal_error"
    assert capture.messages == []
    assert capture.deleted_messages == []


@pytest.mark.asyncio
async def test_webhook_accepts_valid_secret_once(client, db_session: AsyncSession, monkeypatch):
    calls: list[int] = []

    async def fake_handle_update(update: dict[str, Any]) -> None:
        calls.append(update["update_id"])

    monkeypatch.setattr(telegram_routes.settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(telegram_routes.settings, "telegram_webhook_secret_token", "secret")
    monkeypatch.setattr(telegram_routes, "_handle_update", fake_handle_update)

    for _ in range(2):
        response = await client.post(
            "/api/telegram/webhook",
            json={"update_id": 200},
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    update = await db_session.get(TelegramUpdate, 200)
    assert update.status == "accepted"
    assert calls == [200]


@pytest.mark.asyncio
async def test_webhook_rejects_unconfigured_and_bad_payload(client, monkeypatch):
    monkeypatch.setattr(telegram_routes.settings, "telegram_bot_token", "")
    monkeypatch.setattr(telegram_routes.settings, "telegram_webhook_secret_token", "")
    response = await client.post("/api/telegram/webhook", json={"update_id": 300})
    assert response.status_code == 503

    monkeypatch.setattr(telegram_routes.settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(telegram_routes.settings, "telegram_webhook_secret_token", "secret")
    response = await client.post(
        "/api/telegram/webhook",
        content="not json",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
    )
    assert response.status_code == 422
    response = await client.post(
        "/api/telegram/webhook",
        json=[],
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
    )
    assert response.status_code == 422
    response = await client.post(
        "/api/telegram/webhook",
        json={"message": {}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_import_media_no_speech_marks_recording_failed(
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    user = await _user(db_session)
    monkeypatch.setattr("app.core.recording_import.settings.upload_staging_dir", str(tmp_path))

    async def fake_transcribe(*args, **kwargs):
        return [
            TranscriptResult(
                text="[no speech detected]",
                speaker=None,
                is_final=True,
                start_ms=0,
                end_ms=500,
                confidence=None,
            )
        ]

    monkeypatch.setattr("app.core.recording_import.transcribe_audio_file", fake_transcribe)
    result = await import_media_as_recording(
        db=db_session,
        user=user,
        data=b"audio",
        filename="voice.wav",
        content_type="audio/wav",
        title="Пусто",
        source_label="telegram",
        language="auto",
    )

    assert result.recording.status == RecordingStatus.FAILED.value
    assert result.recording.failure_code == "transcript_empty"
    assert result.transcript == ""
    assert result.summary is None


@pytest.mark.asyncio
async def test_import_media_marks_recording_failed_on_processing_error(
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    user = await _user(db_session)
    monkeypatch.setattr("app.core.recording_import.settings.upload_staging_dir", str(tmp_path))

    async def fake_transcribe(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.core.recording_import.transcribe_audio_file", fake_transcribe)

    with pytest.raises(RecordingImportError, match="Не получилось обработать файл"):
        await import_media_as_recording(
            db=db_session,
            user=user,
            data=b"audio",
            filename="voice.wav",
            content_type="audio/wav",
            title="Ошибка",
            source_label="telegram",
            language="ru",
        )

    recording = (
        await db_session.execute(select(Recording).where(Recording.title == "Ошибка"))
    ).scalar_one()
    assert recording.status == RecordingStatus.FAILED.value
    assert recording.failure_code == "processing_failed"


@pytest.mark.asyncio
async def test_import_media_marks_failed_on_domain_processing_error(
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    user = await _user(db_session)
    monkeypatch.setattr("app.core.recording_import.settings.upload_staging_dir", str(tmp_path))

    async def fake_transcribe(*args, **kwargs):
        raise RecordingImportError("bad_audio", "Аудио не читается.")

    monkeypatch.setattr("app.core.recording_import.transcribe_audio_file", fake_transcribe)

    with pytest.raises(RecordingImportError, match="Аудио не читается"):
        await import_media_as_recording(
            db=db_session,
            user=user,
            data=b"audio",
            filename="voice.wav",
            content_type="audio/wav",
            title="Плохое аудио",
            source_label="telegram",
            language="ru",
        )

    recording = (
        await db_session.execute(select(Recording).where(Recording.title == "Плохое аудио"))
    ).scalar_one()
    assert recording.status == RecordingStatus.FAILED.value
    assert recording.failure_code == "bad_audio"


@pytest.mark.asyncio
async def test_import_media_uses_summary_title_without_separate_title_generation(
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    user = await _user(db_session)
    user.default_language = "multi"
    user.summary_language = "auto"
    db_session.add(user)
    await db_session.commit()
    monkeypatch.setattr("app.core.recording_import.settings.upload_staging_dir", str(tmp_path))

    async def fake_transcribe(*args, **kwargs):
        return [
            TranscriptResult(
                text="Текст без заголовка",
                speaker=None,
                is_final=True,
                start_ms=0,
                end_ms=1000,
                confidence=0.9,
            )
        ]

    async def fake_summary(*args, **kwargs):
        return SummaryResult(
            title="Fallback title",
            summary="Саммари",
            key_points=[],
            decisions=[],
            action_items=[],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
            highlights=[],
        )

    monkeypatch.setattr("app.core.recording_import.transcribe_audio_file", fake_transcribe)
    monkeypatch.setattr(
        "app.core.recording_import.generate_embedding",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr("app.core.recording_import.summarize_transcript", fake_summary)

    result = await import_media_as_recording(
        db=db_session,
        user=user,
        data=b"audio",
        filename="voice.wav",
        content_type="audio/wav",
        title=None,
        source_label="telegram",
        language=None,
    )

    assert result.recording.status == RecordingStatus.READY.value
    assert result.recording.title == "Fallback title"
    assert result.recording.language == "auto"


@pytest.mark.asyncio
async def test_telegram_ogg_audio_import_normalizes_before_transcription(
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    user = await _user(db_session)
    monkeypatch.setattr("app.core.recording_import.settings.upload_staging_dir", str(tmp_path))

    async def fake_extract(source, dest):
        # ffmpeg runs file→file: the ogg source stays on disk, FLAC comes out.
        assert source.suffix == ".oga"
        assert source.read_bytes() == b"telegram ogg"
        dest.write_bytes(b"flac from telegram")
        return dest

    monkeypatch.setattr("app.core.recording_import.extract_audio_to_flac", fake_extract)

    async def fake_transcribe(media_path, **kwargs):
        assert media_path.read_bytes() == b"flac from telegram"
        assert kwargs["content_type"] == "audio/flac"
        return [
            TranscriptResult(
                text="Голосовое расшифровано",
                speaker=None,
                is_final=True,
                start_ms=0,
                end_ms=1000,
                confidence=0.9,
            )
        ]

    async def fake_summary(*args, **kwargs):
        return SummaryResult(
            title="Голосовое",
            summary="Саммари голосового",
            key_points=[],
            decisions=[],
            action_items=[],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
            highlights=[],
        )

    monkeypatch.setattr("app.core.recording_import.transcribe_audio_file", fake_transcribe)
    monkeypatch.setattr(
        "app.core.recording_import.generate_embedding",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr("app.core.recording_import.summarize_transcript", fake_summary)

    result = await import_media_as_recording(
        db=db_session,
        user=user,
        data=b"telegram ogg",
        filename="voice.oga",
        content_type="audio/ogg",
        title=None,
        source_label="telegram",
        language="ru",
    )

    assert result.recording.title == "Голосовое"
    assert result.transcript == "Голосовое расшифровано"


@pytest.mark.asyncio
async def test_video_import_normalizes_audio_before_transcription(
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    user = await _user(db_session)
    monkeypatch.setattr("app.core.recording_import.settings.upload_staging_dir", str(tmp_path))

    async def fake_extract(source, dest):
        assert source.suffix == ".mp4"
        assert source.read_bytes() == b"mp4"
        dest.write_bytes(b"flac audio")
        return dest

    monkeypatch.setattr("app.core.recording_import.extract_audio_to_flac", fake_extract)

    async def fake_transcribe(media_path, **kwargs):
        assert media_path.read_bytes() == b"flac audio"
        assert kwargs["content_type"] == "audio/flac"
        return [
            TranscriptResult(
                text="Видео расшифровано",
                speaker=None,
                is_final=True,
                start_ms=0,
                end_ms=1000,
                confidence=0.9,
            )
        ]

    async def fake_summary(*args, **kwargs):
        instructions = kwargs["instructions"]
        assert instructions is not None
        assert "Overall overview" in instructions
        assert "Timestamps and section summaries" in instructions
        assert kwargs["style"] == "structured"
        return SummaryResult(
            title="Видео",
            summary="Видео саммари",
            key_points=[],
            decisions=[],
            action_items=[],
            topics=[],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
            highlights=[],
        )

    monkeypatch.setattr("app.core.recording_import.transcribe_audio_file", fake_transcribe)
    monkeypatch.setattr(
        "app.core.recording_import.generate_embedding",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr("app.core.recording_import.summarize_transcript", fake_summary)

    result = await import_media_as_recording(
        db=db_session,
        user=user,
        data=b"mp4",
        filename="clip.mp4",
        content_type="video/mp4",
        title=None,
        source_label="telegram",
        language="ru",
    )

    assert result.recording.title == "Видео"
    assert result.transcript == "Видео расшифровано"


@pytest.mark.asyncio
async def test_video_import_surfaces_audio_extract_failure(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session)

    def broken_from_file(*args, **kwargs):
        raise RuntimeError("ffmpeg failed")

    monkeypatch.setattr("pydub.AudioSegment.from_file", broken_from_file)
    with pytest.raises(RecordingImportError, match="Не получилось извлечь звук"):
        await import_media_as_recording(
            db=db_session,
            user=user,
            data=b"video",
            filename="clip.mp4",
            content_type="video/mp4",
            title=None,
            source_label="telegram",
            language="ru",
        )


def test_import_extension_resolution_and_rejections():
    assert resolve_import_extension(None, "audio/mpeg") == "mp3"
    assert resolve_import_extension("voice.OGA", None) == "oga"
    assert resolve_import_extension("clip.MOV", None) == "mov"
    with pytest.raises(RecordingImportError):
        resolve_import_extension("file.pdf", "application/pdf")


@pytest.mark.asyncio
async def test_import_media_rejects_empty_file(db_session: AsyncSession):
    user = await _user(db_session)
    with pytest.raises(RecordingImportError, match="Файл пустой"):
        await import_media_as_recording(
            db=db_session,
            user=user,
            data=b"",
            filename="voice.wav",
            content_type="audio/wav",
            title=None,
            source_label="telegram",
            language="ru",
        )


def _mock_response(status_code: int, body: Any, content: bytes = b"") -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json = MagicMock(return_value=body)
    response.content = content

    async def aiter_bytes():
        if content:
            yield content

    response.aiter_bytes = aiter_bytes
    return response


class _MockHttpxStream:
    def __init__(self, response: MagicMock) -> None:
        self.response = response

    async def __aenter__(self) -> MagicMock:
        return self.response

    async def __aexit__(self, *_args: object) -> None:
        return None


class _MockUrllibResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def __enter__(self) -> "_MockUrllibResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _patch_telegram_httpx(
    *,
    post_responses: list[MagicMock],
    get_response: MagicMock | None = None,
):
    client_mock = MagicMock()
    client_mock.post = AsyncMock(side_effect=post_responses)
    if get_response is not None:
        client_mock.stream = MagicMock(return_value=_MockHttpxStream(get_response))
    async_ctx = MagicMock()
    async_ctx.__aenter__ = AsyncMock(return_value=client_mock)
    async_ctx.__aexit__ = AsyncMock(return_value=None)
    return patch("app.core.telegram_client.httpx.AsyncClient", return_value=async_ctx), client_mock


@pytest.mark.asyncio
async def test_telegram_client_send_get_and_download():
    patcher, client_mock = _patch_telegram_httpx(
        post_responses=[
            _mock_response(200, {"ok": True, "result": True}),
            _mock_response(
                200,
                {
                    "ok": True,
                    "result": {
                        "file_id": "file-id",
                        "file_path": "voice/file.ogg",
                        "file_size": 12,
                    },
                },
            ),
        ],
        get_response=_mock_response(200, {"ok": True}, content=b"audio"),
    )

    with patcher:
        client = TelegramBotClient("token")
        await client.send_message(123, "hello", reply_to_message_id=9, parse_mode="HTML")
        tg_file = await client.get_file("file-id")
        data = await client.download_file(tg_file)

    assert tg_file.file_path == "voice/file.ogg"
    assert data == b"audio"
    assert client_mock.post.await_args_list[0].args[0].endswith("/sendMessage")
    assert client_mock.post.await_args_list[0].kwargs["json"]["reply_parameters"] == {
        "message_id": 9,
        "allow_sending_without_reply": True,
    }
    assert client_mock.post.await_args_list[0].kwargs["json"]["parse_mode"] == "HTML"
    assert client_mock.stream.call_args.args[1].endswith("/voice/file.ogg")


@pytest.mark.asyncio
async def test_telegram_client_uses_configurable_bot_api_base_urls():
    patcher, client_mock = _patch_telegram_httpx(
        post_responses=[
            _mock_response(200, {"ok": True, "result": True}),
        ],
    )

    with patcher:
        client = TelegramBotClient(
            "token",
            bot_api_base_url="http://telegram-bot-api:8081",
            file_base_url="http://telegram-bot-api:8081/file",
        )
        await client.send_message(123, "hello")

    assert client_mock.post.await_args.args[0] == "http://telegram-bot-api:8081/bottoken/sendMessage"


@pytest.mark.asyncio
async def test_telegram_client_reads_local_bot_api_file_with_limit(tmp_path: Path):
    token = "123456:ABC"
    file_path = tmp_path / token / "voice" / "file.ogg"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"local audio")

    client = TelegramBotClient("123456:ABC", local_file_root=str(tmp_path))

    data = await client.download_file(TelegramFile("file-id", "voice/file.ogg", None))

    assert data == b"local audio"


@pytest.mark.asyncio
async def test_telegram_client_rejects_local_file_path_traversal(tmp_path: Path):
    client = TelegramBotClient("123456:ABC", local_file_root=str(tmp_path))

    with pytest.raises(TelegramClientError, match="invalid local file path"):
        await client.download_file(TelegramFile("file-id", "../secret.txt", None))


@pytest.mark.asyncio
async def test_telegram_client_enforces_download_limit_for_local_files(tmp_path: Path):
    token = "123456:ABC"
    file_path = tmp_path / token / "documents" / "big.pdf"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"abc")

    client = TelegramBotClient(token, local_file_root=str(tmp_path))

    with pytest.raises(TelegramFileTooLargeError):
        await client.download_file(
            TelegramFile("file-id", "documents/big.pdf", None),
            max_bytes=2,
        )


@pytest.mark.asyncio
async def test_telegram_client_can_send_document_bytes():
    patcher, client_mock = _patch_telegram_httpx(
        post_responses=[
            _mock_response(200, {"ok": True, "result": {"message_id": 77}}),
        ],
    )

    with patcher:
        result = await TelegramBotClient("token").send_document(
            123,
            filename="reflection.txt",
            data=b"transcript",
            caption="Transcript",
            reply_to_message_id=9,
        )

    assert result == {"message_id": 77}
    assert client_mock.post.await_args.args[0].endswith("/sendDocument")
    assert client_mock.post.await_args.kwargs["data"] == {
        "chat_id": "123",
        "caption": "Transcript",
        # Tolerant reply shape: the document still sends when the original
        # message is gone (allow_sending_without_reply).
        "reply_parameters": json.dumps(
            {"message_id": 9, "allow_sending_without_reply": True}
        ),
    }
    assert client_mock.post.await_args.kwargs["files"] == {
        "document": ("reflection.txt", b"transcript", "text/plain; charset=utf-8")
    }


@pytest.mark.asyncio
async def test_telegram_client_send_document_network_error_is_token_safe():
    client_mock = MagicMock()
    client_mock.post = AsyncMock(side_effect=httpx.ConnectError("network"))
    async_ctx = MagicMock()
    async_ctx.__aenter__ = AsyncMock(return_value=client_mock)
    async_ctx.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("app.core.telegram_client.httpx.AsyncClient", return_value=async_ctx),
        patch("app.core.telegram_client.urllib.request.urlopen", side_effect=OSError("offline")),
        pytest.raises(TelegramClientError) as exc,
    ):
        await TelegramBotClient("secret-token").send_document(
            1,
            filename="reflection.txt",
            data=b"transcript",
        )
    assert "secret-token" not in str(exc.value)


@pytest.mark.asyncio
async def test_telegram_client_send_message_recovers_from_httpx_network_error():
    client_mock = MagicMock()
    client_mock.post = AsyncMock(side_effect=httpx.ConnectError("dns failed"))
    async_ctx = MagicMock()
    async_ctx.__aenter__ = AsyncMock(return_value=client_mock)
    async_ctx.__aexit__ = AsyncMock(return_value=None)
    urlopen = MagicMock(
        return_value=_MockUrllibResponse(
            200,
            b'{"ok": true, "result": {"message_id": 42}}',
        )
    )

    with (
        patch("app.core.telegram_client.httpx.AsyncClient", return_value=async_ctx),
        patch("app.core.telegram_client.urllib.request.urlopen", urlopen),
    ):
        result = await TelegramBotClient("secret-token").send_message(1, "hello")

    request = urlopen.call_args.args[0]
    assert result == {"message_id": 42}
    assert request.full_url.endswith("/sendMessage")
    assert "secret-token" in request.full_url
    assert json.loads(request.data.decode("utf-8")) == {
        "chat_id": 1,
        "text": "hello",
        "disable_web_page_preview": True,
    }


@pytest.mark.asyncio
async def test_telegram_client_send_chat_action():
    patcher, client_mock = _patch_telegram_httpx(
        post_responses=[
            _mock_response(200, {"ok": True, "result": True}),
        ],
    )

    with patcher:
        await TelegramBotClient("token").send_chat_action(123)

    assert client_mock.post.await_args.args[0].endswith("/sendChatAction")
    assert client_mock.post.await_args.kwargs["json"] == {
        "chat_id": 123,
        "action": "typing",
    }


@pytest.mark.asyncio
async def test_telegram_client_can_delete_message():
    patcher, client_mock = _patch_telegram_httpx(
        post_responses=[
            _mock_response(200, {"ok": True, "result": True}),
        ],
    )

    with patcher:
        await TelegramBotClient("token").delete_message(123, 456)

    assert client_mock.post.await_args.args[0].endswith("/deleteMessage")
    assert client_mock.post.await_args.kwargs["json"] == {
        "chat_id": 123,
        "message_id": 456,
    }


@pytest.mark.asyncio
async def test_telegram_client_can_clear_bot_commands():
    patcher, client_mock = _patch_telegram_httpx(
        post_responses=[
            _mock_response(200, {"ok": True, "result": True}),
        ],
    )

    with patcher:
        await TelegramBotClient("token").delete_my_commands()

    assert client_mock.post.await_args.args[0].endswith("/deleteMyCommands")
    assert client_mock.post.await_args.kwargs["json"] == {}


@pytest.mark.asyncio
async def test_telegram_client_can_set_bot_commands():
    patcher, client_mock = _patch_telegram_httpx(
        post_responses=[
            _mock_response(200, {"ok": True, "result": True}),
        ],
    )

    commands = [
        {"command": "start", "description": "Start"},
        {"command": "help", "description": "Help"},
    ]
    with patcher:
        await TelegramBotClient("token").set_my_commands(commands, language_code="en")

    assert client_mock.post.await_args.args[0].endswith("/setMyCommands")
    assert client_mock.post.await_args.kwargs["json"] == {
        "commands": commands,
        "language_code": "en",
    }


@pytest.mark.asyncio
async def test_telegram_client_errors_do_not_include_token(monkeypatch):
    monkeypatch.setattr("app.core.telegram_client.settings.telegram_bot_token", "")
    with pytest.raises(TelegramClientError, match="not configured"):
        TelegramBotClient()

    patcher, _ = _patch_telegram_httpx(
        post_responses=[_mock_response(500, {"ok": False, "description": "bad"})]
    )
    with patcher, pytest.raises(TelegramClientError) as exc:
        await TelegramBotClient("secret-token").send_message(1, "hello")
    assert "secret-token" not in str(exc.value)

    patcher, _ = _patch_telegram_httpx(
        post_responses=[_mock_response(200, {"ok": False, "description": "blocked"})]
    )
    with patcher, pytest.raises(TelegramClientError, match="blocked"):
        await TelegramBotClient("secret-token").get_file("file-id")


@pytest.mark.asyncio
async def test_telegram_client_network_and_file_errors_do_not_include_token():
    client_mock = MagicMock()
    client_mock.post = AsyncMock(side_effect=httpx.ConnectError("network"))
    async_ctx = MagicMock()
    async_ctx.__aenter__ = AsyncMock(return_value=client_mock)
    async_ctx.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("app.core.telegram_client.httpx.AsyncClient", return_value=async_ctx),
        patch("app.core.telegram_client.urllib.request.urlopen", side_effect=OSError("offline")),
        pytest.raises(TelegramClientError) as exc,
    ):
        await TelegramBotClient("secret-token").send_message(1, "hello")
    assert "secret-token" not in str(exc.value)

    patcher, _ = _patch_telegram_httpx(
        post_responses=[_mock_response(200, {"ok": True, "result": {}})]
    )
    with patcher, pytest.raises(TelegramClientError, match="no file_path"):
        await TelegramBotClient("secret-token").get_file("file-id")

    patcher, _ = _patch_telegram_httpx(
        post_responses=[],
        get_response=_mock_response(500, {"ok": False}),
    )
    with patcher, pytest.raises(TelegramClientError, match="HTTP 500"):
        await TelegramBotClient("secret-token").download_file(
            TelegramFile("file-id", "voice/file.ogg", None)
        )

    client_mock = MagicMock()
    client_mock.stream = MagicMock(side_effect=httpx.ConnectError("network"))
    async_ctx = MagicMock()
    async_ctx.__aenter__ = AsyncMock(return_value=client_mock)
    async_ctx.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("app.core.telegram_client.httpx.AsyncClient", return_value=async_ctx),
        pytest.raises(TelegramClientError, match="download failed"),
    ):
        await TelegramBotClient("secret-token").download_file(
            TelegramFile("file-id", "voice/file.ogg", None)
        )


def test_telegram_chunks_splits_long_messages():
    text = "a" * 3901 + "\n" + "tail"
    chunks = telegram_chunks(text)

    assert len(chunks) == 2
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")
    assert telegram_chunks("   ") == []


# ---------------------------------------------------------------------------
# Rich recording replies: meta line, page button, honest summary failure, retry
# ---------------------------------------------------------------------------


def test_format_recording_summary_message_has_title_meta_and_body() -> None:
    recording = SimpleNamespace(
        title="Созвон по Сколково",
        duration_seconds=74 * 60 + 19,
    )
    summary = SimpleNamespace(
        summary="**Формат встречи:** еженедельный созвон.\n- Оценка `60-70 млрд руб.`"
    )
    text = telegram_routes._format_recording_summary_message(
        recording,
        summary,
        speaker_names={"speaker_0": "Дмитрий Рубин", "speaker_1": "Мик"},
    )

    lines = text.split("\n")
    assert lines[0] == "<b>Созвон по Сколково</b>"
    assert lines[1] == "<i>1 ч 14 мин · Дмитрий Рубин, Мик</i>"
    assert "<b>Формат встречи:</b>" in text
    assert "<code>60-70 млрд руб.</code>" in text


def test_format_recording_meta_line_skips_short_or_solo() -> None:
    solo = SimpleNamespace(title="Заметка", duration_seconds=42)
    assert (
        telegram_routes._format_recording_meta_line(solo, {"speaker_0": "Мик"}) is None
    )
    duo = SimpleNamespace(title="Звонок", duration_seconds=125)
    assert telegram_routes._format_recording_meta_line(duo, None) == "<i>2 мин</i>"


def test_transcript_document_filename_gets_date_prefix() -> None:
    recording = SimpleNamespace(
        title="Обсуждение стратегии Сколково",
        created_at=datetime(2026, 7, 8, 11, 20, tzinfo=timezone.utc),
    )
    assert (
        telegram_routes._transcript_document_filename(recording, media_kind="audio")
        == "2026-07-08-obsuzhdenie-strategii-skolkovo.txt"
    )


@pytest.mark.asyncio
async def test_media_reply_attaches_page_button(db_session, monkeypatch, tmp_path):
    user = await _user(db_session, "telegram-page-button@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=91, telegram_chat_id=91)
    recording = Recording(
        user_id=user.id,
        title="Созвон",
        type="meeting",
        status=RecordingStatus.READY.value,
        duration_seconds=600,
    )
    db_session.add_all([account, recording])
    await db_session.commit()
    capture = _TelegramCapture()
    pending = _wire_eager_media_enqueue(monkeypatch, db_session, capture, tmp_path)

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)

    async def fake_import(**kwargs):
        return SimpleNamespace(
            recording=recording,
            summary=SimpleNamespace(summary="**Итог:** всё решили"),
            transcript="всё решили",
            transcript_document="00:00:00 Мик\nвсё решили\n",
            speaker_names={"speaker_0": "Мик"},
        )

    monkeypatch.setattr(telegram_routes, "import_media_as_recording", fake_import)
    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 5, "chat": {"id": 91}},
        account=account,
        media={"kind": "voice", "file_id": "file-id"},
    )
    await asyncio.gather(*pending)

    final = capture.messages[-1]
    assert final["parse_mode"] == "HTML"
    markup = final["reply_markup"]
    assert markup is not None
    button = markup["inline_keyboard"][0][0]
    assert button["text"] == "🌐 Открыть страницу"
    assert "/share/" in button["url"]

    share_count = (
        await db_session.execute(
            select(func.count()).select_from(RecordingShare).where(
                RecordingShare.recording_id == recording.id
            )
        )
    ).scalar_one()
    assert share_count == 1


@pytest.mark.asyncio
async def test_media_reply_summary_failure_offers_retry(db_session, monkeypatch, tmp_path):
    user = await _user(db_session, "telegram-retry-offer@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=92, telegram_chat_id=92)
    recording = Recording(
        user_id=user.id,
        title=None,
        type="meeting",
        status=RecordingStatus.READY.value,
    )
    db_session.add_all([account, recording])
    await db_session.commit()
    capture = _TelegramCapture()
    pending = _wire_eager_media_enqueue(monkeypatch, db_session, capture, tmp_path)

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)

    async def fake_import(**kwargs):
        return SimpleNamespace(
            recording=recording,
            summary=None,
            transcript="длинная расшифровка",
            transcript_document="00:00:00\nдлинная расшифровка\n",
            speaker_names={},
        )

    monkeypatch.setattr(telegram_routes, "import_media_as_recording", fake_import)
    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 6, "chat": {"id": 92}},
        account=account,
        media={"kind": "audio", "file_id": "file-id"},
    )
    await asyncio.gather(*pending)

    final = capture.messages[-1]
    assert "Саммари сгенерировать не получилось" in final["text"]
    rows = final["reply_markup"]["inline_keyboard"]
    assert rows[0][0]["callback_data"] == f"sumretry:{recording.id}"
    assert rows[1][0]["text"] == "🌐 Открыть страницу"


@pytest.mark.asyncio
async def test_summary_retry_callback_regenerates_and_replies(db_session, monkeypatch):
    user = await _user(db_session, "telegram-retry-run@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=93, telegram_chat_id=93)
    recording = Recording(
        user_id=user.id,
        title="Restored",
        type="meeting",
        status=RecordingStatus.READY.value,
        duration_seconds=300,
    )
    db_session.add_all([account, recording])
    await db_session.commit()
    capture = _TelegramCapture()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)

    async def fake_regenerate(db, *, recording, user, source_label="telegram"):
        return (
            SimpleNamespace(summary="**Итог:** восстановлено `100%`"),
            {"speaker_0": "Мик", "speaker_1": "Рома"},
        )

    monkeypatch.setattr(telegram_routes, "regenerate_recording_summary", fake_regenerate)

    await telegram_routes._handle_callback_query(
        db_session,
        capture,
        callback_query={
            "id": "cb-1",
            "from": {"id": 93},
            "data": f"sumretry:{recording.id}",
            "message": {"message_id": 77, "chat": {"id": 93}},
        },
    )

    assert capture.callback_answers[0]["text"] == "Пишу саммари…"
    final = capture.messages[-1]
    assert "<b>Restored</b>" in final["text"]
    assert "<code>100%</code>" in final["text"]
    assert "Мик, Рома" in final["text"]
    assert final["reply_markup"]["inline_keyboard"][0][0]["text"] == "🌐 Открыть страницу"


@pytest.mark.asyncio
async def test_summary_retry_callback_rejects_foreign_recording(db_session, monkeypatch):
    owner = await _user(db_session, "telegram-retry-owner@example.com")
    stranger = await _user(db_session, "telegram-retry-stranger@example.com")
    stranger_account = TelegramAccount(
        user_id=stranger.id, telegram_user_id=94, telegram_chat_id=94
    )
    recording = Recording(
        user_id=owner.id,
        title="Private",
        type="meeting",
        status=RecordingStatus.READY.value,
    )
    db_session.add_all([stranger_account, recording])
    await db_session.commit()
    capture = _TelegramCapture()

    async def fail_regenerate(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("regeneration must not run for a foreign recording")

    monkeypatch.setattr(telegram_routes, "regenerate_recording_summary", fail_regenerate)

    await telegram_routes._handle_callback_query(
        db_session,
        capture,
        callback_query={
            "id": "cb-2",
            "from": {"id": 94},
            "data": f"sumretry:{recording.id}",
            "message": {"message_id": 78, "chat": {"id": 94}},
        },
    )

    assert capture.callback_answers[0]["text"] == "Запись не найдена."
    assert capture.messages == []


@pytest.mark.asyncio
async def test_media_status_message_updates_on_summarizing_stage(
    db_session, monkeypatch, tmp_path
):
    user = await _user(db_session, "telegram-stage-edit@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=95, telegram_chat_id=95)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()
    pending = _wire_eager_media_enqueue(monkeypatch, db_session, capture, tmp_path)

    async def fake_import(**kwargs):
        await kwargs["on_stage"]("transcribing")  # ignored stage
        await kwargs["on_stage"]("summarizing")
        return SimpleNamespace(
            recording=SimpleNamespace(title="Stage Test"),
            summary=SimpleNamespace(summary="**Итог:** ок"),
            transcript="ок",
            transcript_document="00:00:00\nок\n",
            speaker_names={},
        )

    monkeypatch.setattr(telegram_routes, "import_media_as_recording", fake_import)
    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 7, "chat": {"id": 95}},
        account=account,
        media={"kind": "voice", "file_id": "file-id"},
    )
    await asyncio.gather(*pending)

    assert any(
        "Пишу саммари" in edit["text"] for edit in capture.edited_messages
    )


@pytest.mark.asyncio
async def test_summary_retry_callback_reports_failure_with_retry_button(
    db_session, monkeypatch
):
    user = await _user(db_session, "telegram-retry-fail@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=96, telegram_chat_id=96)
    recording = Recording(
        user_id=user.id,
        title="Broken",
        type="meeting",
        status=RecordingStatus.READY.value,
    )
    db_session.add_all([account, recording])
    await db_session.commit()
    recording_id = recording.id  # capture before the handler's rollback expires it
    capture = _TelegramCapture()

    async def fail_regenerate(db, *, recording, user, source_label="telegram"):
        raise RuntimeError("llm exploded")

    monkeypatch.setattr(telegram_routes, "regenerate_recording_summary", fail_regenerate)

    await telegram_routes._handle_callback_query(
        db_session,
        capture,
        callback_query={
            "id": "cb-3",
            "from": {"id": 96},
            "data": f"sumretry:{recording_id}",
            "message": {"message_id": 79, "chat": {"id": 96}},
        },
    )

    final = capture.messages[-1]
    assert "Саммари снова не получилось" in final["text"]
    assert (
        final["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        == f"sumretry:{recording_id}"
    )
