"""Telegram bot linking and import tests."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import telegram as telegram_routes
from app.core import companion_actions as ca
from app.core import companion_actuators
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
from app.models.companion import Conversation
from app.models.companion_pending_action import CompanionPendingAction
from app.models.item import Item, ItemChunk, ItemSummary
from app.models.recording import ActionItem, Highlight, Recording, RecordingStatus, Segment, Summary
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
        assert "overrides the normal STYLE brevity" in kwargs["instructions"]
        assert kwargs["style"] == "detailed"
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
        self.file = TelegramFile("file-id", "voice/file.ogg", 12)
        self.data = b"telegram audio"

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_to_message_id: int | None = None,
        parse_mode: str | None = None,
    ) -> None:
        message_id = len(self.messages) + 1
        self.messages.append(
            {
                "message_id": message_id,
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
                "parse_mode": parse_mode,
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
    assert "код" in capture.messages[1]["text"]
    assert (
        await db_session.execute(
            select(TelegramBotLinkCode).where(TelegramBotLinkCode.telegram_user_id == 999)
        )
    ).scalar_one()


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
    monkeypatch.setattr(
        "app.core.unified_search.generate_embedding",
        AsyncMock(return_value=[0.02] * 1536),
    )

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
        intent="runs",
    )
    await telegram_routes._handle_account_command(
        db_session,
        capture,
        message=message,
        account=account,
        intent="run_status",
        arg=str(run.id)[:8],
    )
    await telegram_routes._handle_account_command(
        db_session,
        capture,
        message=message,
        account=account,
        intent="cancel_run",
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
        planner=telegram_routes.static_config_planner,
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
        intent="approve",
        arg=str(row.id),
    )

    assert str(row.id) in capture.messages[0]["text"]
    assert "Выполнил действие" in capture.messages[1]["text"]
    await db_session.refresh(row)
    await db_session.refresh(run)
    assert row.status == "executed"
    assert run.status == "done"


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
        planner=telegram_routes.static_config_planner,
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
async def test_handle_update_routes_obligation_question_to_companion(
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

    async def fake_run_turn(*args, **kwargs):
        assert args[3] == "что я обещал"
        yield telegram_routes.TokenEvent(text="Ответ Wai")

    monkeypatch.setattr(telegram_routes, "TelegramBotClient", lambda: capture)
    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)
    monkeypatch.setattr(telegram_routes, "run_turn", fake_run_turn)

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

    assert capture.messages[-1]["text"] == "Ответ Wai"
    assert (await db_session.get(TelegramUpdate, 207)).status == "completed"


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

    async def fail_run_turn(*args, **kwargs):
        raise AssertionError("unsupported document captions must not route to Wai chat")

    monkeypatch.setattr(telegram_routes, "TelegramBotClient", lambda: capture)
    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)
    monkeypatch.setattr(telegram_routes, "run_turn", fail_run_turn)

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

    async def fake_run_turn(*args, **kwargs):
        assert kwargs["turn_context"].client_timezone is None
        for _ in range(20):
            if capture.actions:
                break
            await asyncio.sleep(0.01)
        assert capture.actions == [{"chat_id": 42, "action": "typing"}]
        yield telegram_routes.TokenEvent(text="Ответ ")
        yield telegram_routes.TokenEvent(text="Wai")

    monkeypatch.setattr(telegram_routes, "run_turn", fake_run_turn)
    await telegram_routes._handle_text_message(
        db_session,
        capture,
        message={"message_id": 10, "chat": {"id": 42}},
        account=account,
        text="Что я обещал?",
    )

    assert capture.messages[-1]["text"] == "Ответ Wai"
    conversation = (
        await db_session.execute(select(Conversation).where(Conversation.user_id == user.id))
    ).scalar_one()
    assert conversation.title == "Telegram"
    assert account.companion_conversation_id == conversation.id
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

    text = capture.messages[-1]["text"]
    assert "Могу сделать это." in text
    assert "Нужно подтверждение" in text
    assert f"/approve {action_id}" in text
    assert f"/reject {action_id}" in text


@pytest.mark.asyncio
async def test_handle_text_message_empty_answer_and_missing_chat(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session)
    account = TelegramAccount(user_id=user.id, telegram_user_id=47, telegram_chat_id=47)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()

    async def empty_run_turn(*args, **kwargs):
        if False:
            yield telegram_routes.TokenEvent(text="")

    monkeypatch.setattr(telegram_routes, "run_turn", empty_run_turn)
    await telegram_routes._handle_text_message(
        db_session,
        capture,
        message={"message_id": 15, "chat": {"id": 47}},
        account=account,
        text="пусто",
    )
    await telegram_routes._handle_text_message(
        db_session,
        capture,
        message={"message_id": 16},
        account=account,
        text="без чата",
    )

    assert capture.messages[-1]["text"] == "Wai не вернул ответ."


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

    async def fake_run_turn(*args, **kwargs):
        yield telegram_routes.ErrorEvent(code="model_error", message="boom")

    monkeypatch.setattr(telegram_routes, "run_turn", fake_run_turn)
    await telegram_routes._handle_text_message(
        db_session,
        capture,
        message={"message_id": 11, "chat": {"id": 43}},
        account=account,
        text="сломайся",
    )

    assert "Не получилось обработать" in capture.messages[-1]["text"]


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
):
    user = await _user(db_session)
    account = TelegramAccount(user_id=user.id, telegram_user_id=44, telegram_chat_id=44)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()

    async def fake_import(**kwargs):
        assert kwargs["filename"] == "voice/file.ogg"
        assert kwargs["title"] is None
        assert kwargs["duration_seconds"] is None
        assert kwargs["source_label"] == "telegram"
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
        )

    monkeypatch.setattr(telegram_routes, "import_media_as_recording", fake_import)
    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 12, "chat": {"id": 44}},
        account=account,
        media={"kind": "voice", "file_id": "file-id"},
    )

    assert "Расшифровываю" in capture.messages[0]["text"]
    assert capture.deleted_messages == [{"chat_id": 44, "message_id": 1}]
    assert capture.documents == [
        {
            "chat_id": 44,
            "filename": "refleksiya-21-nedelya-17-23-maya.txt",
            "data": "Полная расшифровка".encode("utf-8"),
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
    capture.file = TelegramFile("file-id", "voice/file.ogg", 999)
    monkeypatch.setattr(telegram_routes.settings, "telegram_download_max_bytes", 100)
    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 18, "chat": {"id": 49}},
        account=account,
        media={"kind": "voice", "file_id": "file-id"},
    )
    assert "слишком большой" in capture.messages[-1]["text"]

    capture = _TelegramCapture()
    capture.data = b"x" * 101
    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 19, "chat": {"id": 49}},
        account=account,
        media={"kind": "voice", "file_id": "file-id"},
    )
    assert "слишком большой" in capture.messages[-1]["text"]

    async def broken_import(**kwargs):
        raise RecordingImportError("bad_media", "Не удалось импортировать.")

    capture = _TelegramCapture()
    monkeypatch.setattr(telegram_routes.settings, "telegram_download_max_bytes", 1_000)
    monkeypatch.setattr(telegram_routes, "import_media_as_recording", broken_import)
    await telegram_routes._handle_media_message(
        db_session,
        capture,
        message={"message_id": 20, "chat": {"id": 49}, "caption": "Заголовок"},
        account=account,
        media={"kind": "voice", "file_id": "file-id", "file_name": "voice.ogg"},
    )
    assert capture.messages[-1]["text"] == "Не удалось импортировать."


@pytest.mark.asyncio
async def test_handle_media_message_passes_telegram_duration_to_import(
    db_session: AsyncSession,
    monkeypatch,
):
    user = await _user(db_session, "media-duration@example.com")
    account = TelegramAccount(user_id=user.id, telegram_user_id=51, telegram_chat_id=51)
    db_session.add(account)
    await db_session.commit()
    capture = _TelegramCapture()
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

    assert seen["duration_seconds"] == 3600
    assert "Готово. Запись сохранена" in capture.messages[-1]["text"]


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
    monkeypatch.setattr(telegram_routes, "generate_item_summary", fail_summary)
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

    async def fake_run_turn(*args, **kwargs):
        yield telegram_routes.TokenEvent(text="ответ")

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(telegram_routes, "run_turn", fake_run_turn)
    monkeypatch.setattr(telegram_routes, "TelegramBotClient", lambda: capture)
    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)

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

    assert capture.messages[-1]["text"] == "ответ"
    update = await db_session.get(TelegramUpdate, 100)
    assert update.status == "completed"


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
    monkeypatch.setattr(telegram_routes, "_handle_media_message", fake_media)

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
        "_handle_media_message",
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
    assert "Сначала привяжи" in capture.messages[0]["text"]
    assert "/meetings" in capture.messages[1]["text"]
    failed = await db_session.get(TelegramUpdate, 106)
    assert failed.status == "failed"
    assert failed.error_code == "TelegramClientError"
    internal_failed = await db_session.get(TelegramUpdate, 107)
    assert internal_failed.status == "failed"
    assert internal_failed.error_code == "internal_error"


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

    class FakeSegment:
        def set_frame_rate(self, value):
            assert value == 16_000
            return self

        def set_channels(self, value):
            assert value == 1
            return self

        def set_sample_width(self, value):
            assert value == 2
            return self

        def export(self, output, format):
            assert format == "wav"
            output.write(b"wav from telegram")

    def fake_from_file(file_obj, *, format=None):
        assert format == "ogg"
        return FakeSegment()

    monkeypatch.setattr("pydub.AudioSegment.from_file", fake_from_file)

    async def fake_transcribe(data: bytes, **kwargs):
        assert data == b"wav from telegram"
        assert kwargs["content_type"] == "audio/wav"
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

    class FakeSegment:
        def set_frame_rate(self, value):
            assert value == 16_000
            return self

        def set_channels(self, value):
            assert value == 1
            return self

        def set_sample_width(self, value):
            assert value == 2
            return self

        def export(self, output, format):
            assert format == "wav"
            output.write(b"wav audio")

    monkeypatch.setattr("pydub.AudioSegment.from_file", lambda *args, **kwargs: FakeSegment())

    async def fake_transcribe(data: bytes, **kwargs):
        assert data == b"wav audio"
        assert kwargs["content_type"] == "audio/wav"
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
    assert client_mock.post.await_args_list[0].kwargs["json"]["reply_to_message_id"] == 9
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
        "reply_to_message_id": "9",
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
        pytest.raises(TelegramClientError) as exc,
    ):
        await TelegramBotClient("secret-token").send_document(
            1,
            filename="reflection.txt",
            data=b"transcript",
        )
    assert "secret-token" not in str(exc.value)


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
