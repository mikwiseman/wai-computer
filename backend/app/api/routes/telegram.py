"""Telegram bot linking and webhook routes."""

from __future__ import annotations

import asyncio
import logging
import secrets
import string
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import escape
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, Database
from app.config import get_settings
from app.core.agent_dispatch import AgentDispatchError, enqueue_agent_run
from app.core.agent_runtime import cancel_run, execute_agent_step, run_job, static_config_planner
from app.core.companion import (
    ActionProposedEvent,
    CompanionError,
    ErrorEvent,
    TokenEvent,
    TurnContext,
    run_turn,
)
from app.core.companion_actions import (
    ApprovalError,
    mark_executed,
    mark_failed,
    resolve_action,
    verify_committable,
)
from app.core.companion_actuators import ActuationError, execute_action
from app.core.document_extract import (
    SUPPORTED_DOCUMENT_EXTENSIONS,
    DocumentExtractionError,
    document_kind_for_extension,
    extract_document_text,
    resolve_document_extension,
)
from app.core.item_ingest import ingest_item
from app.core.item_processing import process_item
from app.core.item_summary import generate_item_summary
from app.core.item_telegram import format_fetch_error_reply, format_item_reply
from app.core.item_titles import clean_title, title_from_filename
from app.core.mcp_tools import (
    list_recordings_for_mcp,
)
from app.core.recording_import import RecordingImportError, import_media_as_recording
from app.core.source_fetch import classify_url, find_first_url
from app.core.telegram_client import (
    TelegramBotClient,
    TelegramClientError,
    TelegramFileTooLargeError,
    telegram_chunks,
)
from app.core.unified_search import UnifiedHit, unified_search
from app.db.session import get_db_context
from app.models.agent import Agent, AgentRun, AgentStep
from app.models.companion import Conversation
from app.models.companion_pending_action import CompanionPendingAction
from app.models.item import ItemSummary
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
CHAT_ACTION_INTERVAL_SECONDS = 4.0
TELEGRAM_BOT_COMMANDS = [
    {"command": "start", "description": "Привязать Telegram и показать статус"},
    {"command": "help", "description": "Что умеет WaiComputer в Telegram"},
    {"command": "link", "description": "Получить новый код привязки"},
    {"command": "agents", "description": "Показать доступных агентов"},
    {"command": "run", "description": "Запустить агента"},
    {"command": "runs", "description": "Последние запуски агентов"},
    {"command": "run_status", "description": "Статус запуска агента"},
    {"command": "cancel_run", "description": "Остановить запуск агента"},
    {"command": "approvals", "description": "Действия, ожидающие подтверждения"},
    {"command": "approve", "description": "Подтвердить действие один раз"},
    {"command": "reject", "description": "Отклонить действие"},
    {"command": "meetings", "description": "Последние встречи"},
    {"command": "search", "description": "Поиск по записям и расшифровкам"},
    {"command": "settings", "description": "Статус привязки и настройки"},
]
CYRILLIC_SLUG_MAP = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


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


def _is_private_chat(message: dict[str, Any]) -> bool:
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return False
    chat_type = chat.get("type")
    return chat_type is None or chat_type == "private"


def _telegram_help_text(*, linked: bool) -> str:
    if linked:
        status_line = "Telegram привязан к WaiComputer."
    else:
        status_line = "Сначала привяжи Telegram к WaiComputer."
    return (
        f"{status_line}\n\n"
        "Что можно делать:\n"
        "/agents — список агентов\n"
        "/run <агент> <задача> — запустить агента\n"
        "/runs — последние запуски\n"
        "/run_status <run_id> — статус запуска\n"
        "/cancel_run <run_id> — остановить запуск\n"
        "/approvals — действия на подтверждение\n"
        "/approve <action_id> — подтвердить один раз\n"
        "/reject <action_id> — отклонить действие\n"
        "/meetings — последние встречи\n"
        "/search <запрос> — поиск по записям, саммари и расшифровкам\n"
        "/link — получить новый код привязки\n"
        "/settings — где управлять привязкой\n\n"
        "Можно без команд: «покажи последние встречи», «найди дорожная карта». "
        "Голосовые, аудио и видео сохраняю как записи. PDF, DOCX, DOC, HTML, "
        "TXT, Markdown, RTF, CSV, JSON, PPTX и XLSX добавляю в материалы."
    )


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "длительность неизвестна"
    if seconds < 60:
        return f"{seconds} сек"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}:{secs:02d}"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def _format_created_at(value: str | None) -> str:
    if not value:
        return "дата неизвестна"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M")


def _extract_search_query(text: str) -> str:
    stripped = text.strip()
    lower = stripped.lower()
    prefixes = (
        "/search",
        "/find",
        "найди",
        "поищи",
        "найти",
        "поиск",
        "search",
        "find",
    )
    for prefix in prefixes:
        if lower == prefix:
            return ""
        if lower.startswith(prefix + " "):
            return stripped[len(prefix) :].strip()
    return stripped


def _text_intent(text: str) -> tuple[str, str] | None:
    stripped = text.strip()
    if not stripped:
        return None
    lower = stripped.lower()

    if lower in {"help", "помощь", "команды", "что ты умеешь"}:
        return "help", ""

    search_prefixes = ("найди", "поищи", "найти", "поиск", "search", "find")
    search_questions = (
        "что обсуждали",
        "о чем говорили",
        "где обсуждали",
        "когда обсуждали",
        "what did we discuss",
        "what did i discuss",
        "where did we discuss",
    )
    if lower.startswith(search_prefixes) or any(marker in lower for marker in search_questions):
        return "search", _extract_search_query(stripped)

    meeting_markers = ("встреч", "meeting", "meetings")
    list_markers = (
        "покажи",
        "показать",
        "список",
        "последн",
        "мои",
        "list",
        "show",
        "recent",
        "latest",
    )
    if any(marker in lower for marker in meeting_markers) and (
        any(marker in lower for marker in list_markers) or lower in {"встречи", "meetings"}
    ):
        return "meetings", ""

    return None


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
    parse_mode: str | None = None,
) -> None:
    for idx, chunk in enumerate(telegram_chunks(text)):
        await client.send_message(
            chat_id,
            chunk,
            reply_to_message_id=reply_to_message_id if idx == 0 else None,
            parse_mode=parse_mode,
        )


async def _send_private_chat_required(
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
) -> None:
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    await client.send_message(
        chat_id,
        (
            "Открой личный чат с ботом WaiComputer. "
            "Встречи, расшифровки и задачи не показываю в группах."
        ),
        reply_to_message_id=message.get("message_id"),
    )


def _safe_transcript_filename(title: str | None, *, media_kind: str | None = None) -> str:
    source = (title or "").strip() or f"telegram-{media_kind or 'media'}"
    transliterated = source.lower().translate(CYRILLIC_SLUG_MAP)
    chars: list[str] = []
    previous_dash = False
    for char in transliterated:
        if char in string.ascii_lowercase or char in string.digits:
            chars.append(char)
            previous_dash = False
        elif not previous_dash:
            chars.append("-")
            previous_dash = True
    slug = "".join(chars).strip("-")[:60].strip("-")
    if not slug:
        slug = f"telegram-{media_kind or 'media'}"
    return f"{slug}.txt"


def _safe_display_filename(filename: str | None) -> str:
    base = (filename or "").strip().rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return base[:120] if base else "файл"


def _telegram_file_too_large_message() -> str:
    limit_mb = max(1, settings.telegram_download_max_bytes // (1024 * 1024))
    return f"Файл слишком большой для Telegram-импорта. Лимит бота — {limit_mb} MB."


def _telegram_media_duration_seconds(media: dict[str, Any]) -> float | None:
    duration = media.get("duration")
    if isinstance(duration, int | float) and duration > 0:
        return float(duration)
    return None


async def _send_unsupported_document_message(
    client: TelegramBotClient,
    *,
    chat_id: int,
    reply_to_message_id: Any,
) -> None:
    await client.send_message(
        chat_id,
        (
            "Не могу извлечь текст из этого типа файла. Поддерживаются PDF, "
            "DOCX, DOC, HTML, TXT, Markdown, RTF, CSV, JSON, PPTX и XLSX. "
            "Аудио и видео сохраняю как записи."
        ),
        reply_to_message_id=reply_to_message_id,
    )


def _format_import_summary_message(result: Any) -> str:
    title = str(getattr(result.recording, "title", "") or "").strip()
    summary = getattr(result, "summary", None)
    summary_text = str(getattr(summary, "summary", "") or "").strip()

    sections: list[str] = []
    if title:
        sections.append(f"<b>{escape(title)}</b>")
    if summary_text:
        sections.append(_telegram_summary_html(summary_text))
    return "\n\n".join(sections).strip()


def _telegram_summary_html(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            lines.append("")
            continue
        escaped = escape(line)
        if not line.startswith(("-", "•")) and line.endswith(":"):
            lines.append(f"<b>{escaped}</b>")
        else:
            lines.append(escaped)
    return "\n".join(lines).strip()


def _sent_message_id(response: Any) -> int | None:
    if not isinstance(response, dict):
        return None
    message_id = response.get("message_id")
    return message_id if isinstance(message_id, int) else None


async def _delete_status_message(
    client: TelegramBotClient,
    *,
    chat_id: int,
    message_id: int | None,
) -> None:
    if message_id is None:
        return
    try:
        await client.delete_message(chat_id, message_id)
    except TelegramClientError as exc:
        logger.warning("telegram status delete failed error=%s", type(exc).__name__)


async def _send_chat_action_until_cancelled(
    client: TelegramBotClient,
    chat_id: int,
    *,
    action: str = "typing",
) -> None:
    while True:
        try:
            await client.send_chat_action(chat_id, action)
        except TelegramClientError as exc:
            logger.warning(
                "telegram chat action failed action=%s error=%s",
                action,
                type(exc).__name__,
            )
        except Exception:
            logger.exception("telegram chat action crashed action=%s", action)
            return
        await asyncio.sleep(CHAT_ACTION_INTERVAL_SECONDS)


async def _stop_chat_action_task(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@router.get("/link", response_model=TelegramLinkStatus)
async def get_link_status(user: CurrentUser, db: Database) -> TelegramLinkStatus:
    result = await db.execute(select(TelegramAccount).where(TelegramAccount.user_id == user.id))
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


@router.delete(
    "/link",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def unlink(user: CurrentUser, db: Database) -> Response:
    result = await db.execute(select(TelegramAccount).where(TelegramAccount.user_id == user.id))
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
        select(TelegramAccount).where(TelegramAccount.telegram_user_id == telegram_user_id)
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


def _extract_document(message: dict[str, Any]) -> dict[str, Any] | None:
    document = message.get("document")
    if not isinstance(document, dict) or not document.get("file_id"):
        return None
    ext = resolve_document_extension(
        str(document.get("file_name") or ""),
        str(document.get("mime_type") or ""),
    )
    if ext not in SUPPORTED_DOCUMENT_EXTENSIONS:
        return None
    return {"kind": "document", "document_ext": ext, **document}


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
        if text.startswith("Готово"):
            text = f"{text}\n\n{_telegram_help_text(linked=True)}"
    elif await _load_account(db, telegram_user_id):
        text = _telegram_help_text(linked=True)
    else:
        await _send_bot_link_code(
            db,
            client,
            message=message,
            intro=_telegram_help_text(linked=False),
        )
        return
    await client.send_message(chat_id, text, reply_to_message_id=message.get("message_id"))


async def _ensure_active_user(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
) -> User | None:
    user = await db.get(User, account.user_id)
    chat_id = _telegram_chat_id(message)
    if user is None:
        if chat_id is not None:
            await client.send_message(
                chat_id,
                "Аккаунт WaiComputer не найден. Привяжи Telegram заново.",
                reply_to_message_id=message.get("message_id"),
            )
        return None
    if getattr(user, "account_status", "active") != "active":
        if chat_id is not None:
            await client.send_message(
                chat_id,
                (
                    "Аккаунт WaiComputer сейчас не активен. "
                    "Открой приложение и проверь статус аккаунта."
                ),
                reply_to_message_id=message.get("message_id"),
            )
        return None
    return user


def _format_recording_list(results: list[dict[str, Any]], *, empty_text: str) -> str:
    if not results:
        return empty_text
    lines = ["Последние встречи:"]
    for index, item in enumerate(results, start=1):
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        title = str(item.get("title") or "Без названия")
        created = _format_created_at(metadata.get("created_at"))
        duration = _format_duration(metadata.get("duration_seconds"))
        url = str(item.get("url") or "")
        lines.append(f"{index}. {title}\n{created} · {duration}\n{url}".strip())
    return "\n\n".join(lines)


def _format_search_results(results: list[UnifiedHit], *, query: str) -> str:
    if not results:
        return f"Ничего не нашел по запросу: {query}"
    lines = [f"Нашел по запросу: {query}"]
    for index, item in enumerate(results, start=1):
        title = str(item.title or "Без названия")
        text = item.snippet.strip()
        created = _format_created_at(item.created_at)
        source = "запись" if item.source_kind == "recording" else "материал"
        lines.append(f"{index}. {title}\n{source} · {created}\n{text}".strip())
    return "\n\n".join(lines)


async def _handle_help_command(
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    linked: bool,
) -> None:
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    await client.send_message(
        chat_id,
        _telegram_help_text(linked=linked),
        reply_to_message_id=message.get("message_id"),
    )


async def _handle_meetings_command(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
) -> None:
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    if await _ensure_active_user(db, client, message=message, account=account) is None:
        return
    result = await list_recordings_for_mcp(
        db,
        account.user_id,
        recording_type="meeting",
        limit=10,
    )
    await _send_chunks(
        client,
        chat_id,
        _format_recording_list(
            result["results"],
            empty_text=(
                "Встреч пока нет. Запиши встречу в приложении WaiComputer, и она появится здесь."
            ),
        ),
        reply_to_message_id=message.get("message_id"),
    )


async def _handle_search_command(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    query: str,
) -> None:
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    if await _ensure_active_user(db, client, message=message, account=account) is None:
        return
    clean_query = query.strip()
    if not clean_query:
        await client.send_message(
            chat_id,
            "Напиши запрос после /search. Например: /search дорожная карта",
            reply_to_message_id=message.get("message_id"),
        )
        return
    results = await unified_search(db, account.user_id, clean_query, limit=5)
    await _send_chunks(
        client,
        chat_id,
        _format_search_results(results, query=clean_query),
        reply_to_message_id=message.get("message_id"),
    )


async def _handle_settings_command(
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    linked: bool,
) -> None:
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    status_text = "привязан" if linked else "не привязан"
    await client.send_message(
        chat_id,
        (
            f"Telegram сейчас {status_text}. Управление привязкой: "
            "открой Settings в приложении WaiComputer или веб-дашборде и найди блок Telegram."
        ),
        reply_to_message_id=message.get("message_id"),
    )


def _short_uuid(value: Any) -> str:
    return str(value)[:8]


async def _load_agent_ref(
    db: AsyncSession,
    *,
    user_id: Any,
    ref: str,
) -> Agent | None:
    clean = ref.strip()
    if not clean:
        return None
    try:
        agent_id = UUID(clean)
    except ValueError:
        agent_id = None
    if agent_id is not None:
        return (
            await db.execute(
                select(Agent).where(Agent.id == agent_id, Agent.user_id == user_id)
            )
        ).scalar_one_or_none()

    result = await db.execute(
        select(Agent).where(Agent.user_id == user_id).order_by(Agent.created_at.desc())
    )
    normalized = clean.casefold()
    agents = list(result.scalars().all())
    for agent in agents:
        if agent.name.casefold() == normalized:
            return agent
    if len(clean) >= 8:
        matches = [agent for agent in agents if str(agent.id).startswith(clean)]
        if len(matches) == 1:
            return matches[0]
    return None


async def _load_run_ref(
    db: AsyncSession,
    *,
    user_id: Any,
    ref: str,
) -> AgentRun | None:
    clean = ref.strip()
    try:
        run_id = UUID(clean)
    except ValueError:
        run_id = None
    if run_id is not None:
        return (
            await db.execute(
                select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id)
            )
        ).scalar_one_or_none()
    if len(clean) < 8:
        return None
    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.user_id == user_id)
        .order_by(AgentRun.created_at.desc())
        .limit(100)
    )
    matches = [run for run in result.scalars().all() if str(run.id).startswith(clean)]
    if len(matches) == 1:
        return matches[0]
    return None


async def _handle_agents_command(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
) -> None:
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    if await _ensure_active_user(db, client, message=message, account=account) is None:
        return
    result = await db.execute(
        select(Agent)
        .where(Agent.user_id == account.user_id)
        .order_by(Agent.created_at.desc())
        .limit(20)
    )
    agents = list(result.scalars().all())
    if not agents:
        text = "Агентов пока нет. Создай агента в WaiComputer Web или Mac."
    else:
        lines = ["Агенты:"]
        for agent in agents:
            state = "on" if agent.enabled else "off"
            lines.append(f"{_short_uuid(agent.id)} · {agent.name} · {agent.kind} · {state}")
        text = "\n".join(lines)
    await client.send_message(chat_id, text, reply_to_message_id=message.get("message_id"))


def _split_agent_run_arg(arg: str) -> tuple[str, str]:
    clean = arg.strip()
    if not clean:
        return "", ""
    ref, _, objective = clean.partition(" ")
    return ref.strip(), objective.strip()


async def _handle_run_command(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    arg: str,
) -> None:
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    if await _ensure_active_user(db, client, message=message, account=account) is None:
        return
    agent_ref, objective = _split_agent_run_arg(arg)
    if not agent_ref:
        await client.send_message(
            chat_id,
            "Формат: /run <agent_id или имя> <задача>",
            reply_to_message_id=message.get("message_id"),
        )
        return
    agent = await _load_agent_ref(db, user_id=account.user_id, ref=agent_ref)
    if agent is None:
        await client.send_message(
            chat_id,
            "Агент не найден. Посмотри /agents.",
            reply_to_message_id=message.get("message_id"),
        )
        return
    if not agent.enabled:
        await client.send_message(
            chat_id,
            "Агент выключен. Включи его в WaiComputer перед запуском.",
            reply_to_message_id=message.get("message_id"),
        )
        return

    message_id = message.get("message_id")
    trigger_suffix = f"{chat_id}:{message_id}" if isinstance(message_id, int) else uuid4().hex
    trigger_key = f"telegram:{agent.id}:{trigger_suffix}"
    existing = (
        await db.execute(
            select(AgentRun).where(
                AgentRun.user_id == account.user_id,
                AgentRun.trigger_key == trigger_key,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = AgentRun(
            agent_id=agent.id,
            user_id=account.user_id,
            trigger_key=trigger_key,
            trigger_kind="telegram",
            trigger_payload={
                "source": "telegram",
                "objective": objective,
                "telegram_message_id": message_id,
            },
        )
        db.add(existing)
        await db.flush()
        await db.commit()
        try:
            enqueue_agent_run(existing.id)
        except AgentDispatchError as exc:
            existing.status = "failed"
            existing.error = exc.message
            existing.finished_at = datetime.now(timezone.utc)
            await db.flush()
            await db.commit()
            await client.send_message(
                chat_id,
                f"Не смог запустить агента: {exc.message}",
                reply_to_message_id=message.get("message_id"),
            )
            return

    await client.send_message(
        chat_id,
        (
            f"Запустил: {agent.name}\n"
            f"run_id: {existing.id}\n"
            f"status: {existing.status}"
        ),
        reply_to_message_id=message.get("message_id"),
    )


async def _handle_runs_command(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
) -> None:
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    if await _ensure_active_user(db, client, message=message, account=account) is None:
        return
    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.user_id == account.user_id)
        .order_by(AgentRun.created_at.desc())
        .limit(10)
    )
    runs = list(result.scalars().all())
    if not runs:
        text = "Запусков агентов пока нет."
    else:
        lines = ["Последние запуски:"]
        for run in runs:
            run_label = (
                f"{_short_uuid(run.id)} · {run.status} · {run.trigger_kind} · "
                f"agent {_short_uuid(run.agent_id)}"
            )
            lines.append(
                run_label
            )
        text = "\n".join(lines)
    await client.send_message(chat_id, text, reply_to_message_id=message.get("message_id"))


async def _format_run_status(db: AsyncSession, run: AgentRun) -> str:
    steps_count = (
        await db.execute(select(AgentStep).where(AgentStep.run_id == run.id))
    ).scalars().all()
    pending_actions = (
        await db.execute(
            select(CompanionPendingAction).where(
                CompanionPendingAction.agent_run_id == run.id,
                CompanionPendingAction.status == "pending",
            )
        )
    ).scalars().all()
    lines = [
        f"run_id: {run.id}",
        f"status: {run.status}",
        f"trigger: {run.trigger_kind}",
        f"steps: {len(steps_count)}",
        f"pending approvals: {len(pending_actions)}",
    ]
    if run.error:
        lines.append(f"error: {run.error}")
    return "\n".join(lines)


async def _handle_run_status_command(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    arg: str,
) -> None:
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    run = await _load_run_ref(db, user_id=account.user_id, ref=arg)
    if run is None:
        await client.send_message(
            chat_id,
            "Запуск не найден. Посмотри /runs.",
            reply_to_message_id=message.get("message_id"),
        )
        return
    await client.send_message(
        chat_id,
        await _format_run_status(db, run),
        reply_to_message_id=message.get("message_id"),
    )


async def _handle_cancel_run_command(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    arg: str,
) -> None:
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    run = await _load_run_ref(db, user_id=account.user_id, ref=arg)
    if run is None:
        await client.send_message(
            chat_id,
            "Запуск не найден. Посмотри /runs.",
            reply_to_message_id=message.get("message_id"),
        )
        return
    await cancel_run(db, run, reason="cancelled from Telegram")
    await client.send_message(
        chat_id,
        f"Остановил запуск {run.id}. status: {run.status}",
        reply_to_message_id=message.get("message_id"),
    )


async def _handle_approvals_command(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
) -> None:
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    result = await db.execute(
        select(CompanionPendingAction)
        .where(
            CompanionPendingAction.user_id == account.user_id,
            CompanionPendingAction.status == "pending",
        )
        .order_by(CompanionPendingAction.created_at)
        .limit(10)
    )
    actions = list(result.scalars().all())
    if not actions:
        text = "Нет действий, ожидающих подтверждения."
    else:
        lines = ["Ожидают подтверждения:"]
        for action in actions:
            preview = str((action.action_manifest or {}).get("preview") or "").strip()
            lines.append(
                f"{action.id}\n{action.tool_name} · {action.kind}\n{preview}\n"
                f"/approve {action.id}\n/reject {action.id}"
            )
        text = "\n\n".join(lines)
    await _send_chunks(
        client,
        chat_id,
        text,
        reply_to_message_id=message.get("message_id"),
    )


async def _resume_agent_after_telegram_action(
    db: AsyncSession,
    action: CompanionPendingAction,
) -> None:
    if action.agent_run_id is None:
        return
    await run_job(
        db,
        action.agent_run_id,
        planner=static_config_planner,
        executor=execute_agent_step,
    )


async def _handle_approval_decision_command(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    arg: str,
    decision: str,
) -> None:
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    try:
        action_id = UUID(arg.strip())
    except ValueError:
        await client.send_message(
            chat_id,
            "Нужен action_id. Посмотри /approvals.",
            reply_to_message_id=message.get("message_id"),
        )
        return
    try:
        row = await resolve_action(
            db,
            action_id=action_id,
            user_id=account.user_id,
            decision=decision,
        )
    except ApprovalError as exc:
        await client.send_message(
            chat_id,
            f"Не смог обработать подтверждение: {exc.message}",
            reply_to_message_id=message.get("message_id"),
        )
        return

    if decision == "reject":
        await _resume_agent_after_telegram_action(db, row)
        await client.send_message(
            chat_id,
            f"Отклонил действие {action_id}.",
            reply_to_message_id=message.get("message_id"),
        )
        return

    try:
        verify_committable(row)
        if row.kind == "desktop_action":
            await _resume_agent_after_telegram_action(db, row)
            await client.send_message(
                chat_id,
                f"Подтвердил действие {action_id}. Оно отправлено на Mac edge.",
                reply_to_message_id=message.get("message_id"),
            )
            return
        args = (row.action_manifest or {}).get("args") or {}
        receipt = await execute_action(
            db,
            user_id=account.user_id,
            tool_name=row.tool_name,
            args=args,
        )
        await mark_executed(db, row=row, receipt=receipt)
        await _resume_agent_after_telegram_action(db, row)
    except (ApprovalError, ActuationError) as exc:
        await mark_failed(db, row=row, detail=exc.message)
        await _resume_agent_after_telegram_action(db, row)
        await client.send_message(
            chat_id,
            f"Действие не выполнено: {exc.message}",
            reply_to_message_id=message.get("message_id"),
        )
        return

    await client.send_message(
        chat_id,
        f"Выполнил действие {action_id}.",
        reply_to_message_id=message.get("message_id"),
    )


async def _handle_account_command(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    intent: str,
    arg: str = "",
) -> bool:
    if intent == "help":
        await _handle_help_command(client, message=message, linked=True)
        return True
    if await _ensure_active_user(db, client, message=message, account=account) is None:
        return True
    if intent == "agents":
        await _handle_agents_command(db, client, message=message, account=account)
        return True
    if intent == "run":
        await _handle_run_command(db, client, message=message, account=account, arg=arg)
        return True
    if intent == "runs":
        await _handle_runs_command(db, client, message=message, account=account)
        return True
    if intent == "run_status":
        await _handle_run_status_command(db, client, message=message, account=account, arg=arg)
        return True
    if intent == "cancel_run":
        await _handle_cancel_run_command(db, client, message=message, account=account, arg=arg)
        return True
    if intent == "approvals":
        await _handle_approvals_command(db, client, message=message, account=account)
        return True
    if intent == "approve":
        await _handle_approval_decision_command(
            db, client, message=message, account=account, arg=arg, decision="once"
        )
        return True
    if intent == "reject":
        await _handle_approval_decision_command(
            db, client, message=message, account=account, arg=arg, decision="reject"
        )
        return True
    if intent == "meetings":
        await _handle_meetings_command(db, client, message=message, account=account)
        return True
    if intent == "search":
        await _handle_search_command(db, client, message=message, account=account, query=arg)
        return True
    if intent == "settings":
        await _handle_settings_command(client, message=message, linked=True)
        return True
    return False


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


async def _handle_url_message(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    url: str,
) -> None:
    """Forward a link to the bot -> ingest it + reply with summary + key moments.

    The item is captured idempotently (re-forwarding the same link returns the
    existing item, no re-fetch). Fetch is run inline so the user gets the
    summary in the same reply; a clean fetch error (e.g. Instagram) is shown as
    a "share the file" message.
    """
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    if await _ensure_active_user(db, client, message=message, account=account) is None:
        return

    item, created = await ingest_item(
        db,
        account.user_id,
        source="telegram",
        kind=classify_url(url),
        url=url,
        dedup_key=url,
        body=None,
        embed=False,
    )
    await db.flush()

    action_task = asyncio.create_task(_send_chat_action_until_cancelled(client, chat_id))
    try:
        if created or item.state != "promoted":
            await process_item(db, item)
            await db.flush()
    except Exception:  # noqa: BLE001 — surface a friendly message, keep the saved item
        logger.exception("telegram url processing failed url_host=%s", classify_url(url))
        await _stop_chat_action_task(action_task)
        await client.send_message(
            chat_id,
            "Сохранил ссылку, но не смог её обработать. Попробуй позже.",
            reply_to_message_id=message.get("message_id"),
        )
        return
    finally:
        await _stop_chat_action_task(action_task)

    fetch_error = (item.metadata_ or {}).get("fetch_error")
    if fetch_error:
        await client.send_message(
            chat_id,
            format_fetch_error_reply(fetch_error.get("message", "Couldn't fetch that link.")),
            reply_to_message_id=message.get("message_id"),
            parse_mode="HTML",
        )
        return

    summary = await db.execute(
        select(ItemSummary).where(ItemSummary.item_id == item.id)
    )
    reply = format_item_reply(item, summary.scalar_one_or_none())
    await _send_chunks(
        client,
        chat_id,
        reply,
        reply_to_message_id=message.get("message_id"),
        parse_mode="HTML",
    )


def _format_action_proposals_for_telegram(actions: list[ActionProposedEvent]) -> str:
    if not actions:
        return ""
    lines = ["Нужно подтверждение:"]
    for action in actions:
        preview = action.preview.strip() or action.tool
        recipient = f" · {action.recipient}" if action.recipient else ""
        lines.append(
            f"{action.action_id}\n{action.tool} · {action.kind}{recipient}\n"
            f"{preview}\n/approve {action.action_id}\n/reject {action.action_id}"
        )
    return "\n\n".join(lines)


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
    if await _ensure_active_user(db, client, message=message, account=account) is None:
        return
    conversation = await _ensure_telegram_conversation(db, account)
    chunks: list[str] = []
    proposed_actions: list[ActionProposedEvent] = []
    action_task = asyncio.create_task(_send_chat_action_until_cancelled(client, chat_id))
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
            elif isinstance(event, ActionProposedEvent):
                proposed_actions.append(event)
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
    finally:
        await _stop_chat_action_task(action_task)

    answer = "".join(chunks).strip()
    approval_text = _format_action_proposals_for_telegram(proposed_actions)
    if approval_text:
        answer = f"{answer}\n\n{approval_text}".strip()
    if not answer:
        answer = "Wai не вернул ответ."
    await _send_chunks(
        client,
        chat_id,
        answer,
        reply_to_message_id=message.get("message_id"),
    )


async def _handle_document_message(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    document: dict[str, Any],
) -> None:
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    if await _ensure_active_user(db, client, message=message, account=account) is None:
        return

    file_id = document.get("file_id")
    if not isinstance(file_id, str):
        return
    ext = str(document.get("document_ext") or "").lower()
    if not ext:
        ext = resolve_document_extension(
            str(document.get("file_name") or ""),
            str(document.get("mime_type") or ""),
        )
    if ext not in SUPPORTED_DOCUMENT_EXTENSIONS:
        await _send_unsupported_document_message(
            client,
            chat_id=chat_id,
            reply_to_message_id=message.get("message_id"),
        )
        return

    file_size = document.get("file_size")
    if isinstance(file_size, int) and file_size > settings.telegram_download_max_bytes:
        await client.send_message(
            chat_id,
            _telegram_file_too_large_message(),
            reply_to_message_id=message.get("message_id"),
        )
        return

    filename = _safe_display_filename(str(document.get("file_name") or ""))
    status_response = await client.send_message(
        chat_id,
        f"Принял {filename}. Извлекаю текст и делаю краткое содержание.",
        reply_to_message_id=message.get("message_id"),
    )
    status_message_id = _sent_message_id(status_response)

    try:
        tg_file = await client.get_file(file_id)
        if (
            tg_file.file_size is not None
            and tg_file.file_size > settings.telegram_download_max_bytes
        ):
            await client.send_message(chat_id, _telegram_file_too_large_message())
            return
        data = await client.download_file(tg_file, max_bytes=settings.telegram_download_max_bytes)
        if len(data) > settings.telegram_download_max_bytes:
            await client.send_message(chat_id, _telegram_file_too_large_message())
            return
        body = await extract_document_text(ext, data)
    except TelegramFileTooLargeError:
        await client.send_message(
            chat_id,
            _telegram_file_too_large_message(),
            reply_to_message_id=message.get("message_id"),
        )
        return
    except DocumentExtractionError as exc:
        await client.send_message(
            chat_id,
            f"Не смог прочитать файл: {exc.message}",
            reply_to_message_id=message.get("message_id"),
        )
        return
    finally:
        await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)

    caption = str(message.get("caption") or "").strip()
    source_ref = str(document.get("file_unique_id") or file_id)
    try:
        item, created = await ingest_item(
            db,
            account.user_id,
            source="telegram",
            source_ref=source_ref,
            kind=document_kind_for_extension(ext),
            title=clean_title(caption) or title_from_filename(str(document.get("file_name") or "")),
            body=body,
            metadata={
                "telegram": {
                    "file_unique_id": document.get("file_unique_id"),
                    "mime_type": document.get("mime_type"),
                    "ext": ext,
                    "size": len(data),
                }
            },
            embed=True,
        )
        await db.flush()
    except Exception:  # noqa: BLE001 - failed import should be explicit to the sender.
        logger.exception("telegram document ingest failed ext=%s", ext)
        await client.send_message(
            chat_id,
            "Не смог сохранить файл в материалы. Попробуй позже.",
            reply_to_message_id=message.get("message_id"),
        )
        return

    summary = (
        await db.execute(select(ItemSummary).where(ItemSummary.item_id == item.id))
    ).scalar_one_or_none()
    if created or summary is None:
        action_task = asyncio.create_task(_send_chat_action_until_cancelled(client, chat_id))
        try:
            summary = await generate_item_summary(db, item)
            await db.flush()
        except Exception:  # noqa: BLE001 - keep the saved item and surface the failure.
            logger.exception("telegram document processing failed ext=%s", ext)
            await client.send_message(
                chat_id,
                "Сохранил файл в материалы, но не смог сделать краткое содержание. Попробуй позже.",
                reply_to_message_id=message.get("message_id"),
            )
            return
        finally:
            await _stop_chat_action_task(action_task)

    reply = format_item_reply(item, summary)
    await _send_chunks(
        client,
        chat_id,
        reply,
        reply_to_message_id=message.get("message_id"),
        parse_mode="HTML",
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
    if await _ensure_active_user(db, client, message=message, account=account) is None:
        return

    file_id = media.get("file_id")
    if not isinstance(file_id, str):
        return
    file_size = media.get("file_size")
    if isinstance(file_size, int) and file_size > settings.telegram_download_max_bytes:
        await client.send_message(
            chat_id,
            _telegram_file_too_large_message(),
            reply_to_message_id=message.get("message_id"),
        )
        return

    status_response = await client.send_message(
        chat_id,
        "Принял. Расшифровываю и сохраняю в библиотеку WaiComputer.",
        reply_to_message_id=message.get("message_id"),
    )
    status_message_id = _sent_message_id(status_response)

    tg_file = await client.get_file(file_id)
    if tg_file.file_size is not None and tg_file.file_size > settings.telegram_download_max_bytes:
        await client.send_message(chat_id, _telegram_file_too_large_message())
        return
    try:
        data = await client.download_file(tg_file, max_bytes=settings.telegram_download_max_bytes)
        if len(data) > settings.telegram_download_max_bytes:
            await client.send_message(chat_id, _telegram_file_too_large_message())
            return
    except TelegramFileTooLargeError:
        await client.send_message(
            chat_id,
            _telegram_file_too_large_message(),
            reply_to_message_id=message.get("message_id"),
        )
        return

    user = await db.get(User, account.user_id)
    if user is None:
        await client.send_message(
            chat_id,
            "Аккаунт WaiComputer не найден. Привяжи Telegram заново.",
        )
        return
    caption = str(message.get("caption") or "").strip()
    title = caption[:500] if caption else None
    action_task = asyncio.create_task(_send_chat_action_until_cancelled(client, chat_id))
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
            duration_seconds=_telegram_media_duration_seconds(media),
        )
    except RecordingImportError as exc:
        logger.warning(
            "telegram media import failed code=%s kind=%s",
            exc.code,
            media.get("kind"),
        )
        await client.send_message(chat_id, exc.message)
        return
    finally:
        await _stop_chat_action_task(action_task)

    if result.transcript:
        await client.send_document(
            chat_id,
            filename=_safe_transcript_filename(
                result.recording.title,
                media_kind=str(media.get("kind") or "media"),
            ),
            data=result.transcript.encode("utf-8"),
            reply_to_message_id=message.get("message_id"),
        )
    summary_message = _format_import_summary_message(result)
    if summary_message:
        await _send_chunks(
            client,
            chat_id,
            summary_message,
            reply_to_message_id=message.get("message_id"),
            parse_mode="HTML",
        )
    else:
        await client.send_message(
            chat_id,
            f"Готово. Запись сохранена в библиотеку: {result.recording.title or 'Без названия'}",
            reply_to_message_id=message.get("message_id"),
        )
    await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)


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

            if not _is_private_chat(message):
                await _send_private_chat_required(client, message=message)
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
            if command and command[0] == "/help":
                if account is None:
                    await _send_bot_link_code(
                        db,
                        client,
                        message=message,
                        intro=_telegram_help_text(linked=False),
                    )
                else:
                    await _handle_help_command(client, message=message, linked=True)
                await _mark_update(db, update_id, "completed")
                return

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
            elif (document := _extract_document(message)) is not None:
                await _handle_document_message(
                    db,
                    client,
                    message=message,
                    account=account,
                    document=document,
                )
            elif isinstance(message.get("document"), dict):
                await _send_unsupported_document_message(
                    client,
                    chat_id=chat_id,
                    reply_to_message_id=message.get("message_id"),
                )
            elif command:
                intent = command[0].removeprefix("/")
                arg = command[1]
                if intent == "find":
                    intent = "search"
                handled = await _handle_account_command(
                    db,
                    client,
                    message=message,
                    account=account,
                    intent=intent,
                    arg=arg,
                )
                if not handled:
                    await client.send_message(
                        chat_id,
                        _telegram_help_text(linked=True),
                        reply_to_message_id=message.get("message_id"),
                    )
            else:
                text = _message_text(message)
                if not text:
                    await client.send_message(
                        chat_id,
                        "Пришли голосовое, видео, документ или вопрос текстом.",
                        reply_to_message_id=message.get("message_id"),
                    )
                else:
                    text_intent = _text_intent(text)
                    forwarded_url = find_first_url(text)
                    if text_intent is not None:
                        intent, arg = text_intent
                        await _handle_account_command(
                            db,
                            client,
                            message=message,
                            account=account,
                            intent=intent,
                            arg=arg,
                        )
                    elif forwarded_url is not None:
                        await _handle_url_message(
                            db,
                            client,
                            message=message,
                            account=account,
                            url=forwarded_url,
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
