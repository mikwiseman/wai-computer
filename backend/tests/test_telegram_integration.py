"""Telegram bot linking and import tests."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import telegram as telegram_routes
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
    telegram_chunks,
)
from app.core.transcript_utils import TranscriptResult
from app.models.billing import UsageWeek
from app.models.companion import Conversation
from app.models.recording import ActionItem, Highlight, Recording, RecordingStatus, Segment, Summary
from app.models.telegram import (
    TelegramAccount,
    TelegramBotLinkCode,
    TelegramPairing,
    TelegramUpdate,
)
from app.models.user import User


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
        await db_session.execute(
            select(TelegramAccount).where(TelegramAccount.user_id == user.id)
        )
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
        telegram_routes._extract_media(
            {"document": {"file_id": "doc-id", "file_name": "x.pdf"}}
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

    async def fake_embedding(text: str):
        raise RuntimeError("embedding offline")

    async def fake_identify(**kwargs):
        raise RuntimeError("voice id offline")

    async def fake_title(transcript: str, *, language: str):
        return "Telegram запись"

    async def fake_summary(transcript: str, **kwargs):
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
    monkeypatch.setattr("app.core.recording_import.generate_title", fake_title)
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
        await db_session.execute(select(Segment).where(Segment.recording_id == recording.id))
    ).scalars().all()
    summary = (
        await db_session.execute(select(Summary).where(Summary.recording_id == recording.id))
    ).scalar_one()
    action_items = (
        await db_session.execute(select(ActionItem).where(ActionItem.recording_id == recording.id))
    ).scalars().all()
    highlights = (
        await db_session.execute(select(Highlight).where(Highlight.recording_id == recording.id))
    ).scalars().all()
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


class _TelegramCapture:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []
        self.file = TelegramFile("file-id", "voice/file.ogg", 12)
        self.data = b"telegram audio"

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_to_message_id: int | None = None,
    ) -> None:
        self.messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
            }
        )

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        self.actions.append({"chat_id": chat_id, "action": action})

    async def get_file(self, file_id: str) -> TelegramFile:
        assert file_id == "file-id"
        return self.file

    async def download_file(self, file: TelegramFile) -> bytes:
        assert file.file_path == self.file.file_path
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

    assert "уже привязан" in capture.messages[0]["text"]
    assert "код" in capture.messages[1]["text"]
    assert (
        await db_session.execute(
            select(TelegramBotLinkCode).where(TelegramBotLinkCode.telegram_user_id == 999)
        )
    ).scalar_one()


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
        await db_session.execute(
            select(Conversation).where(Conversation.user_id == user.id)
        )
    ).scalar_one()
    assert conversation.title == "Telegram"
    assert account.companion_conversation_id == conversation.id


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
        assert kwargs["source_label"] == "telegram"
        for _ in range(20):
            if capture.actions:
                break
            await asyncio.sleep(0.01)
        assert capture.actions == [{"chat_id": 44, "action": "typing"}]
        return SimpleNamespace(
            recording=SimpleNamespace(title="Telegram запись"),
            summary=SimpleNamespace(summary="Короткое саммари"),
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
    assert "Саммари" in capture.messages[-1]["text"]
    assert "Расшифровка" in capture.messages[-1]["text"]


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
    assert "Команды в боте не нужны" in capture.messages[1]["text"]
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
async def test_import_media_no_speech_marks_recording_ready(
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

    assert result.recording.status == RecordingStatus.READY.value
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
async def test_import_media_continues_when_title_generation_fails(
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

    async def fake_title(*args, **kwargs):
        raise RuntimeError("title down")

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
    monkeypatch.setattr("app.core.recording_import.generate_title", fake_title)
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
    assert result.recording.title is None
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
    monkeypatch.setattr(
        "app.core.recording_import.generate_title",
        AsyncMock(return_value="Голосовое"),
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
    monkeypatch.setattr("app.core.recording_import.generate_title", AsyncMock(return_value="Видео"))
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
    return response


def _patch_telegram_httpx(
    *,
    post_responses: list[MagicMock],
    get_response: MagicMock | None = None,
):
    client_mock = MagicMock()
    client_mock.post = AsyncMock(side_effect=post_responses)
    if get_response is not None:
        client_mock.get = AsyncMock(return_value=get_response)
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
        await client.send_message(123, "hello", reply_to_message_id=9)
        tg_file = await client.get_file("file-id")
        data = await client.download_file(tg_file)

    assert tg_file.file_path == "voice/file.ogg"
    assert data == b"audio"
    assert client_mock.post.await_args_list[0].args[0].endswith("/sendMessage")
    assert client_mock.post.await_args_list[0].kwargs["json"]["reply_to_message_id"] == 9
    assert client_mock.get.await_args.args[0].endswith("/voice/file.ogg")


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
    client_mock.get = AsyncMock(side_effect=httpx.ConnectError("network"))
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
