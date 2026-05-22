"""Telegram bot linking and webhook routes."""

from __future__ import annotations

import logging
import secrets
import string
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, Database
from app.config import get_settings
from app.core.companion import CompanionError, ErrorEvent, TokenEvent, TurnContext, run_turn
from app.core.recording_import import RecordingImportError, import_media_as_recording
from app.core.telegram_client import (
    TelegramBotClient,
    TelegramClientError,
    telegram_chunks,
)
from app.db.session import get_db_context
from app.models.companion import Conversation
from app.models.telegram import (
    TelegramAccount,
    TelegramBotLinkCode,
    TelegramPairing,
    TelegramUpdate,
)
from app.models.user import User

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/telegram", tags=["telegram"])

PAIRING_TTL = timedelta(minutes=15)
PAIRING_PREFIX = "link_"
BOT_LINK_CODE_TTL = timedelta(minutes=15)
BOT_LINK_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
BOT_LINK_CODE_LENGTH = 8


class TelegramLinkStatus(BaseModel):
    linked: bool
    bot_username: str
    telegram_user_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    linked_at: datetime | None = None


class TelegramPairingResponse(BaseModel):
    bot_username: str
    deep_link: str
    web_link: str
    expires_at: datetime


class TelegramLinkCodeClaimRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


def _token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _bot_username() -> str:
    username = settings.telegram_bot_username.strip().lstrip("@")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot username is not configured",
        )
    return username


def _require_bot_runtime() -> None:
    if not settings.telegram_bot_token or not settings.telegram_webhook_secret_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot is not configured",
        )


def _message_text(message: dict[str, Any]) -> str:
    return str(message.get("text") or message.get("caption") or "").strip()


def _message_command(message: dict[str, Any]) -> tuple[str, str] | None:
    text = _message_text(message)
    if not text.startswith("/"):
        return None
    first, _, rest = text.partition(" ")
    command = first.split("@", 1)[0].lower()
    return command, rest.strip()


def _normalize_bot_link_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch in string.ascii_uppercase + string.digits)


def _format_bot_link_code(code: str) -> str:
    normalized = _normalize_bot_link_code(code)
    return f"{normalized[:4]}-{normalized[4:]}"


async def _load_account(db: AsyncSession, telegram_user_id: int) -> TelegramAccount | None:
    result = await db.execute(
        select(TelegramAccount).where(TelegramAccount.telegram_user_id == telegram_user_id)
    )
    return result.scalar_one_or_none()


def _status_from_account(account: TelegramAccount | None) -> TelegramLinkStatus:
    return TelegramLinkStatus(
        linked=account is not None,
        bot_username=_bot_username(),
        telegram_user_id=account.telegram_user_id if account else None,
        username=account.username if account else None,
        first_name=account.first_name if account else None,
        last_name=account.last_name if account else None,
        linked_at=account.created_at if account else None,
    )


async def _send_chunks(
    client: TelegramBotClient,
    chat_id: int,
    text: str,
    *,
    reply_to_message_id: int | None = None,
) -> None:
    for idx, chunk in enumerate(telegram_chunks(text)):
        await client.send_message(
            chat_id,
            chunk,
            reply_to_message_id=reply_to_message_id if idx == 0 else None,
        )


@router.get("/link", response_model=TelegramLinkStatus)
async def get_link_status(user: CurrentUser, db: Database) -> TelegramLinkStatus:
    result = await db.execute(
        select(TelegramAccount).where(TelegramAccount.user_id == user.id)
    )
    account = result.scalar_one_or_none()
    return _status_from_account(account)


@router.post("/link/start", response_model=TelegramPairingResponse)
async def start_link(user: CurrentUser, db: Database) -> TelegramPairingResponse:
    _require_bot_runtime()
    bot_username = _bot_username()
    token = secrets.token_urlsafe(32)
    start_payload = f"{PAIRING_PREFIX}{token}"
    expires_at = datetime.now(timezone.utc) + PAIRING_TTL
    pairing = TelegramPairing(
        user_id=user.id,
        token_hash=_token_hash(token),
        expires_at=expires_at,
    )
    db.add(pairing)
    await db.flush()
    return TelegramPairingResponse(
        bot_username=bot_username,
        deep_link=f"tg://resolve?domain={bot_username}&start={start_payload}",
        web_link=f"https://t.me/{bot_username}?start={start_payload}",
        expires_at=expires_at,
    )


@router.delete("/link", status_code=status.HTTP_204_NO_CONTENT)
async def unlink(user: CurrentUser, db: Database) -> Response:
    result = await db.execute(
        select(TelegramAccount).where(TelegramAccount.user_id == user.id)
    )
    account = result.scalar_one_or_none()
    if account is not None:
        await db.delete(account)
        await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _apply_telegram_link(
    db: AsyncSession,
    *,
    user_id: Any,
    telegram_user_id: int,
    telegram_chat_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
) -> TelegramAccount:
    now = datetime.now(timezone.utc)
    existing_result = await db.execute(
        select(TelegramAccount).where(
            TelegramAccount.telegram_user_id == telegram_user_id
        )
    )
    existing_by_telegram = existing_result.scalar_one_or_none()
    if existing_by_telegram is not None and existing_by_telegram.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Этот Telegram уже привязан к другому аккаунту WaiComputer.",
        )

    account_result = await db.execute(
        select(TelegramAccount).where(TelegramAccount.user_id == user_id)
    )
    account = account_result.scalar_one_or_none()
    if account is None:
        account = TelegramAccount(
            user_id=user_id,
            telegram_user_id=telegram_user_id,
        )
        db.add(account)

    account.telegram_user_id = telegram_user_id
    account.telegram_chat_id = telegram_chat_id
    account.username = username
    account.first_name = first_name
    account.last_name = last_name
    account.last_seen_at = now
    await db.flush()
    return account


async def _consume_pairing(
    db: AsyncSession,
    *,
    token: str,
    telegram_user_id: int,
    telegram_chat_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
) -> str:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(TelegramPairing).where(
            and_(
                TelegramPairing.token_hash == _token_hash(token),
                TelegramPairing.consumed_at.is_(None),
                TelegramPairing.expires_at > now,
            )
        )
    )
    pairing = result.scalar_one_or_none()
    if pairing is None:
        return (
            "Код привязки устарел или уже использован. "
            "Создай новую ссылку в настройках WaiComputer."
        )

    try:
        await _apply_telegram_link(
            db,
            user_id=pairing.user_id,
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
    except HTTPException as exc:
        if exc.status_code != status.HTTP_409_CONFLICT:
            raise
        return "Этот Telegram уже привязан к другому аккаунту WaiComputer."
    pairing.telegram_user_id = telegram_user_id
    pairing.consumed_at = now
    await db.commit()
    return (
        "Готово. Telegram привязан к WaiComputer. "
        "Теперь можно присылать голосовые, видео и вопросы текстом."
    )


async def _create_bot_link_code(
    db: AsyncSession,
    *,
    telegram_user_id: int,
    telegram_chat_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
) -> str:
    expires_at = datetime.now(timezone.utc) + BOT_LINK_CODE_TTL
    for _ in range(10):
        code = "".join(secrets.choice(BOT_LINK_CODE_ALPHABET) for _ in range(BOT_LINK_CODE_LENGTH))
        existing = (
            await db.execute(
                select(TelegramBotLinkCode).where(
                    TelegramBotLinkCode.token_hash == _token_hash(code)
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        db.add(
            TelegramBotLinkCode(
                token_hash=_token_hash(code),
                telegram_user_id=telegram_user_id,
                telegram_chat_id=telegram_chat_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                expires_at=expires_at,
            )
        )
        await db.commit()
        return code
    raise TelegramClientError("Telegram link code collision")


async def _send_bot_link_code(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    intro: str,
) -> None:
    from_user = _telegram_user(message)
    chat_id = _telegram_chat_id(message)
    if from_user is None or chat_id is None:
        return
    telegram_user_id = from_user.get("id")
    if not isinstance(telegram_user_id, int):
        return
    code = await _create_bot_link_code(
        db,
        telegram_user_id=telegram_user_id,
        telegram_chat_id=chat_id,
        username=from_user.get("username"),
        first_name=from_user.get("first_name"),
        last_name=from_user.get("last_name"),
    )
    await client.send_message(
        chat_id,
        (
            f"{intro}\n\n"
            "Открой WaiComputer -> Настройки -> Telegram и введи код:\n"
            f"{_format_bot_link_code(code)}\n\n"
            "Код действует 15 минут."
        ),
        reply_to_message_id=message.get("message_id"),
    )


async def _consume_bot_link_code(
    db: AsyncSession,
    *,
    code: str,
    user_id: Any,
) -> TelegramAccount:
    normalized = _normalize_bot_link_code(code)
    if len(normalized) != BOT_LINK_CODE_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Код привязки неверный или устарел.",
        )
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(TelegramBotLinkCode).where(
            and_(
                TelegramBotLinkCode.token_hash == _token_hash(normalized),
                TelegramBotLinkCode.consumed_at.is_(None),
                TelegramBotLinkCode.expires_at > now,
            )
        )
    )
    link_code = result.scalar_one_or_none()
    if link_code is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Код привязки неверный или устарел.",
        )

    account = await _apply_telegram_link(
        db,
        user_id=user_id,
        telegram_user_id=link_code.telegram_user_id,
        telegram_chat_id=link_code.telegram_chat_id,
        username=link_code.username,
        first_name=link_code.first_name,
        last_name=link_code.last_name,
    )
    link_code.user_id = user_id
    link_code.consumed_at = now
    await db.commit()
    return account


@router.post("/link/claim", response_model=TelegramLinkStatus)
async def claim_link_code(
    request: TelegramLinkCodeClaimRequest,
    user: CurrentUser,
    db: Database,
) -> TelegramLinkStatus:
    _require_bot_runtime()
    account = await _consume_bot_link_code(db, code=request.code, user_id=user.id)
    return _status_from_account(account)


def _telegram_user(message: dict[str, Any]) -> dict[str, Any] | None:
    user = message.get("from")
    return user if isinstance(user, dict) else None


def _telegram_chat_id(message: dict[str, Any]) -> int | None:
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return None
    chat_id = chat.get("id")
    return chat_id if isinstance(chat_id, int) else None


def _extract_media(message: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("voice", "audio", "video", "video_note"):
        obj = message.get(key)
        if isinstance(obj, dict) and obj.get("file_id"):
            return {"kind": key, **obj}
    document = message.get("document")
    if isinstance(document, dict) and document.get("file_id"):
        mime_type = str(document.get("mime_type") or "").lower()
        file_name = str(document.get("file_name") or "").lower()
        audio_ext = (".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac", ".aac", ".webm")
        video_ext = (".mp4", ".mov", ".mkv", ".webm")
        if (
            mime_type.startswith("audio/")
            or mime_type.startswith("video/")
            or file_name.endswith(audio_ext + video_ext)
        ):
            return {"kind": "document", **document}
    return None


async def _handle_start_command(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    arg: str,
) -> None:
    from_user = _telegram_user(message)
    chat_id = _telegram_chat_id(message)
    if from_user is None or chat_id is None:
        return
    telegram_user_id = from_user.get("id")
    if not isinstance(telegram_user_id, int):
        return

    if arg.startswith(PAIRING_PREFIX):
        text = await _consume_pairing(
            db,
            token=arg.removeprefix(PAIRING_PREFIX),
            telegram_user_id=telegram_user_id,
            telegram_chat_id=chat_id,
            username=from_user.get("username"),
            first_name=from_user.get("first_name"),
            last_name=from_user.get("last_name"),
        )
    elif await _load_account(db, telegram_user_id):
        text = "WaiComputer уже привязан. Пришли голосовое, видео или вопрос текстом."
    else:
        await _send_bot_link_code(
            db,
            client,
            message=message,
            intro=(
                "Чтобы привязать Telegram к WaiComputer, введи этот код в настройках."
            ),
        )
        return
    await client.send_message(chat_id, text, reply_to_message_id=message.get("message_id"))


async def _ensure_telegram_conversation(
    db: AsyncSession,
    account: TelegramAccount,
) -> Conversation:
    if account.companion_conversation_id is not None:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == account.companion_conversation_id,
                Conversation.user_id == account.user_id,
                Conversation.deleted_at.is_(None),
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation is not None:
            return conversation

    conversation = Conversation(
        user_id=account.user_id,
        title="Telegram",
        scope={"source": "telegram"},
    )
    db.add(conversation)
    await db.flush()
    account.companion_conversation_id = conversation.id
    await db.commit()
    return conversation


async def _handle_text_message(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    text: str,
) -> None:
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    conversation = await _ensure_telegram_conversation(db, account)
    chunks: list[str] = []
    try:
        async for event in run_turn(
            db,
            account.user_id,
            conversation.id,
            text,
            turn_context=TurnContext(),
        ):
            if isinstance(event, TokenEvent):
                chunks.append(event.text)
            elif isinstance(event, ErrorEvent):
                raise CompanionError(event.code, event.message)
    except CompanionError as exc:
        logger.warning("telegram Wai turn failed code=%s", exc.code)
        await client.send_message(
            chat_id,
            "Не получилось обработать запрос к Wai. Попробуй еще раз.",
            reply_to_message_id=message.get("message_id"),
        )
        return

    answer = "".join(chunks).strip()
    if not answer:
        answer = "Wai не вернул ответ."
    await _send_chunks(
        client,
        chat_id,
        answer,
        reply_to_message_id=message.get("message_id"),
    )


async def _handle_media_message(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    media: dict[str, Any],
) -> None:
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return

    file_id = media.get("file_id")
    if not isinstance(file_id, str):
        return
    file_size = media.get("file_size")
    if isinstance(file_size, int) and file_size > settings.telegram_download_max_bytes:
        await client.send_message(
            chat_id,
            "Файл слишком большой для Telegram-импорта. Лимит бота — 20 MB.",
            reply_to_message_id=message.get("message_id"),
        )
        return

    await client.send_message(
        chat_id,
        "Принял. Расшифровываю и сохраняю в библиотеку WaiComputer.",
        reply_to_message_id=message.get("message_id"),
    )

    tg_file = await client.get_file(file_id)
    if tg_file.file_size is not None and tg_file.file_size > settings.telegram_download_max_bytes:
        await client.send_message(chat_id, "Файл слишком большой для Telegram-импорта.")
        return
    data = await client.download_file(tg_file)
    if len(data) > settings.telegram_download_max_bytes:
        await client.send_message(chat_id, "Файл слишком большой для Telegram-импорта.")
        return

    user = await db.get(User, account.user_id)
    if user is None:
        await client.send_message(
            chat_id,
            "Аккаунт WaiComputer не найден. Привяжи Telegram заново.",
        )
        return
    caption = str(message.get("caption") or "").strip()
    title = caption[:500] if caption else f"Telegram {media.get('kind', 'media')}"
    try:
        result = await import_media_as_recording(
            db=db,
            user=user,
            data=data,
            filename=media.get("file_name") or tg_file.file_path,
            content_type=media.get("mime_type"),
            title=title,
            source_label="telegram",
            language=user.default_language,
        )
    except RecordingImportError as exc:
        logger.warning(
            "telegram media import failed code=%s kind=%s",
            exc.code,
            media.get("kind"),
        )
        await client.send_message(chat_id, exc.message)
        return

    summary_text = result.summary.summary if result.summary else None
    parts = [f"Готово. Запись сохранена в библиотеку: {result.recording.title or 'Без названия'}"]
    if summary_text:
        parts.append(f"Саммари:\n{summary_text}")
    if result.transcript:
        transcript = result.transcript
        if len(transcript) > 1800:
            transcript = f"{transcript[:1800].rstrip()}..."
        parts.append(f"Расшифровка:\n{transcript}")
    await _send_chunks(client, chat_id, "\n\n".join(parts))


async def _handle_update(update: dict[str, Any]) -> None:
    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        return
    client = TelegramBotClient()
    async with get_db_context() as db:
        try:
            message = update.get("message")
            if not isinstance(message, dict):
                await _mark_update(db, update_id, "completed")
                return

            from_user = _telegram_user(message)
            chat_id = _telegram_chat_id(message)
            if from_user is None or chat_id is None:
                await _mark_update(db, update_id, "completed")
                return
            telegram_user_id = from_user.get("id")
            if not isinstance(telegram_user_id, int):
                await _mark_update(db, update_id, "completed")
                return

            command = _message_command(message)
            if command and command[0] in {"/start", "/link"}:
                await _handle_start_command(
                    db,
                    client,
                    message=message,
                    arg=command[1],
                )
                await _mark_update(db, update_id, "completed")
                return

            account = await _load_account(db, telegram_user_id)
            if account is None:
                await _send_bot_link_code(
                    db,
                    client,
                    message=message,
                    intro="Сначала привяжи Telegram к WaiComputer.",
                )
                await _mark_update(db, update_id, "completed")
                return
            account.telegram_chat_id = chat_id
            account.username = from_user.get("username")
            account.first_name = from_user.get("first_name")
            account.last_name = from_user.get("last_name")
            account.last_seen_at = datetime.now(timezone.utc)
            await db.flush()

            media = _extract_media(message)
            if media is not None:
                await _handle_media_message(
                    db,
                    client,
                    message=message,
                    account=account,
                    media=media,
                )
            elif command:
                await client.send_message(
                    chat_id,
                    (
                        "Команды в боте не нужны. Просто пришли голосовое, "
                        "видео или текстовый вопрос."
                    ),
                    reply_to_message_id=message.get("message_id"),
                )
            else:
                text = _message_text(message)
                if not text:
                    await client.send_message(
                        chat_id,
                        "Пришли голосовое, видео или вопрос текстом.",
                        reply_to_message_id=message.get("message_id"),
                    )
                else:
                    await _handle_text_message(
                        db,
                        client,
                        message=message,
                        account=account,
                        text=text,
                    )
            await _mark_update(db, update_id, "completed")
        except (TelegramClientError, RecordingImportError) as exc:
            logger.warning(
                "telegram update failed update_id=%s code=%s",
                update_id,
                type(exc).__name__,
            )
            await _mark_update(
                db,
                update_id,
                "failed",
                type(exc).__name__,
                "Telegram update failed",
            )
        except Exception:
            logger.exception("telegram update failed update_id=%s", update_id)
            await _mark_update(db, update_id, "failed", "internal_error", "Telegram update failed")


async def _mark_update(
    db: AsyncSession,
    update_id: int,
    status_value: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    update = await db.get(TelegramUpdate, update_id)
    if update is None:
        return
    update.status = status_value
    update.error_code = error_code
    update.error_message = error_message
    update.processed_at = datetime.now(timezone.utc)
    await db.flush()


async def _accept_update(db: AsyncSession, update: dict[str, Any]) -> bool:
    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid Telegram update_id",
        )
    stmt = (
        pg_insert(TelegramUpdate)
        .values(
            update_id=update_id,
            status="accepted",
            received_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(index_elements=["update_id"])
    )
    result = await db.execute(stmt)
    await db.flush()
    return bool(result.rowcount)


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Database,
) -> dict[str, bool]:
    _require_bot_runtime()
    header_secret = request.headers.get("x-telegram-bot-api-secret-token")
    if not secrets.compare_digest(header_secret or "", settings.telegram_webhook_secret_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook secret")

    try:
        update = await request.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid Telegram update payload",
        ) from exc
    if not isinstance(update, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid Telegram update payload",
        )

    try:
        accepted = await _accept_update(db, update)
    except IntegrityError:
        accepted = False
    await db.commit()
    if accepted:
        background_tasks.add_task(_handle_update, update)
    return {"ok": True}
