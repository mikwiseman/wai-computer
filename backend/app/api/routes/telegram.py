"""Telegram bot linking and webhook routes."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import string
from contextlib import suppress
from dataclasses import dataclass
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
from app.core import user_memory as user_memory_module
from app.core.agent_dispatch import AgentDispatchError, enqueue_agent_run
from app.core.agent_runtime import (
    TERMINAL_STATUSES,
    cancel_run,
    execute_agent_step,
    is_retrying_agent_run,
    pop_agent_runs_to_dispatch_after_commit,
    run_job,
)
from app.core.companion import (
    ActionProposedEvent,
    CompanionError,
    ErrorEvent,
    TokenEvent,
    TurnContext,
    _message_content_to_text,
    run_turn,
)
from app.core.companion_actions import (
    ApprovalError,
    expire_due_actions,
    mark_executed,
    mark_failed,
    resolve_action,
    verify_committable,
)
from app.core.companion_actuators import ActuationError, execute_action
from app.core.companion_resolve import resolve_action_for_user
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
    list_action_items_for_mcp,
    list_recordings_for_mcp,
)
from app.core.ocr import OcrError, ocr_image
from app.core.recording_import import (
    RecordingImportError,
    TranscribedMedia,
    import_media_as_recording,
    transcribe_media_bytes,
)
from app.core.retry_policy import is_retryable_exception
from app.core.source_fetch import classify_url, find_first_url
from app.core.telegram_client import (
    TelegramBotClient,
    TelegramClientError,
    TelegramFileTooLargeError,
    telegram_chunks,
)
from app.core.telegram_format import telegram_html
from app.core.telegram_intent import (
    VoiceRouteDecision,
    classify_voice_transcript,
    route_voice_by_metadata,
)
from app.core.unified_search import UnifiedHit, unified_search
from app.core.wai_agent import planner_for_agent
from app.db.session import get_db_context
from app.models.agent import Agent, AgentRun, AgentStep
from app.models.companion import ChatMessage, Conversation
from app.models.companion_pending_action import CompanionPendingAction
from app.models.item import ItemSummary
from app.models.reminder import UserReminder
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
CONSENT_CALLBACK_DATA = "consent:accept"
DELETE_CALLBACK_DATA = "account:delete"
TERMS_URL = "https://wai.computer/terms"
PRIVACY_URL = "https://wai.computer/privacy"
BOT_LINK_CODE_TTL = timedelta(minutes=15)
BOT_LINK_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
BOT_LINK_CODE_LENGTH = 8
CHAT_ACTION_INTERVAL_SECONDS = 4.0
REMINDER_TEXT_LIMIT = 1200
TELEGRAM_PENDING_RECORDING_TTL = timedelta(hours=6)
TELEGRAM_RECORDING_IMPORT_ERROR_REPLY = "Не смог обработать запись. Попробуй позже."
TELEGRAM_WAI_GENERIC_ERROR_REPLY = "Не получилось обработать запрос к Wai. Попробуй еще раз."
TELEGRAM_WAI_RETRYABLE_ERROR_REPLY = (
    "Wai уперся во временный лимит провайдера. Попробуй еще раз через минуту."
)
_REMIND_RELATIVE_RE = re.compile(
    r"^(?:in|через)\s+(\d{1,5})\s*"
    r"(m|min|minute|minutes|мин|минут|h|hour|hours|ч|час|часа|часов|d|day|days|д|дн|день|дня|дней)"
    r"\s+(.+)$",
    re.IGNORECASE,
)
TELEGRAM_BOT_COMMANDS = [
    {"command": "start", "description": "Привязать Telegram и показать статус"},
    {"command": "help", "description": "Что умеет WaiComputer в Telegram"},
    {"command": "link", "description": "Получить новый код привязки"},
    {"command": "remember", "description": "Сохранить факт в память Wai"},
    {"command": "remind", "description": "Поставить напоминание в Telegram"},
    {"command": "agents", "description": "Показать доступных агентов"},
    {"command": "run", "description": "Запустить агента"},
    {"command": "runs", "description": "Последние запуски агентов"},
    {"command": "list", "description": "Короткий алиас для /runs"},
    {"command": "run_status", "description": "Статус запуска агента"},
    {"command": "status", "description": "Короткий алиас для /run_status"},
    {"command": "cancel_run", "description": "Остановить запуск агента"},
    {"command": "cancel", "description": "Короткий алиас для /cancel_run"},
    {"command": "approvals", "description": "Действия, ожидающие подтверждения"},
    {"command": "approve", "description": "Подтвердить действие один раз"},
    {"command": "approve_always", "description": "Подтвердить действие всегда"},
    {"command": "reject", "description": "Отклонить действие"},
    {"command": "meetings", "description": "Последние встречи"},
    {"command": "search", "description": "Поиск по записям и расшифровкам"},
    {"command": "web", "description": "Ссылка для входа в веб-версию"},
    {"command": "mcp", "description": "Получить MCP-токен для агентов"},
    {"command": "email", "description": "Привязать email для входа и чеков"},
    {"command": "export", "description": "Скачать копию своих данных"},
    {"command": "delete", "description": "Удалить аккаунт и все данные"},
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
        "/remember [human|topics|preferences] <факт> — сохранить факт в память Wai\n"
        "/remind in 10m <текст> — напомнить в Telegram; также можно ISO-время с timezone\n"
        "/agents — список агентов\n"
        "/run <агент> <задача> — запустить агента\n"
        "/runs или /list — последние запуски\n"
        "/run_status или /status <run_id> — статус запуска\n"
        "/cancel_run или /cancel <run_id> — остановить запуск\n"
        "/approvals — действия на подтверждение\n"
        "/approve <action_id> — подтвердить один раз\n"
        "/approve_always <action_id> — подтвердить всегда\n"
        "/reject <action_id> — отклонить действие\n"
        "/meetings — последние встречи\n"
        "/search <запрос> — поиск по записям, саммари и расшифровкам\n"
        "/web — ссылка для входа в веб-версию\n"
        "/mcp — MCP-токен для подключения агентов\n"
        "/email you@example.com — привязать email\n"
        "/export — скачать копию своих данных\n"
        "/delete — удалить аккаунт и все данные\n"
        "/link — привязать уже существующий аккаунт\n"
        "/settings — где управлять привязкой\n\n"
        "Можно без команд: «запомни люблю короткие ответы», "
        "«покажи последние встречи», «найди дорожная карта». "
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


def _strip_text_prefix(text: str, prefixes: tuple[str, ...]) -> str:
    stripped = text.strip()
    lower = stripped.lower()
    for prefix in prefixes:
        if lower == prefix:
            return ""
        if lower.startswith(prefix + " "):
            return stripped[len(prefix) :].strip()
    return ""


def _text_intent(text: str) -> tuple[str, str] | None:
    stripped = text.strip()
    if not stripped:
        return None
    lower = stripped.lower()

    if lower in {"help", "помощь", "команды", "что ты умеешь"}:
        return "help", ""

    remember_arg = _strip_text_prefix(stripped, ("remember", "запомни", "запомнить"))
    if remember_arg:
        return "remember", remember_arg

    remind_arg = _strip_text_prefix(stripped, ("remind me", "remind", "напомни", "напомнить"))
    if remind_arg:
        return "remind", remind_arg

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


def _is_ambiguous_status_prompt(text: str) -> bool:
    normalized = text.strip().casefold()
    if not normalized:
        return False
    if normalized in {"?", "??", "???", "статус?", "готово?", "status?", "done?"}:
        return True
    return len(normalized) <= 3 and set(normalized) <= {"?"}


def _is_pending_recording_followup(text: str) -> bool:
    normalized = text.strip().casefold()
    if _is_ambiguous_status_prompt(normalized):
        return True
    return normalized in {
        "статус",
        "готово",
        "готово?",
        "что там",
        "ну что",
        "ну?",
        "о чем",
        "о чём",
        "саммари",
        "summary",
        "summarize",
        "what is it about",
        "status",
        "status?",
        "done",
        "done?",
    }


def _parse_context_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _telegram_status_reply_for_text(context: Any, text: str) -> str | None:
    if isinstance(context, dict):
        ref_type = str(context.get("ref_type") or "")
        if ref_type == "pending_recording" and _is_pending_recording_followup(text):
            started_at = _parse_context_datetime(context.get("started_at"))
            if started_at is not None:
                age = datetime.now(timezone.utc) - started_at
                if age > TELEGRAM_PENDING_RECORDING_TTL:
                    return (
                        "Последний Telegram-импорт не завершился. "
                        "Пришли запись еще раз или проверь библиотеку WaiComputer."
                    )
            return (
                "Запись еще расшифровывается и сохраняется. "
                "Когда закончу, пришлю расшифровку и саммари сюда."
            )
        if ref_type == "recording_import_error" and _is_pending_recording_followup(text):
            message = str(context.get("message") or "ошибка импорта").strip()
            return f"Последний Telegram-импорт не завершился: {message}"
        if ref_type in {"recording", "item"}:
            return None

    if _is_ambiguous_status_prompt(text):
        return "Напиши вопрос полностью или используй /help, чтобы посмотреть команды."
    return None


def _parse_remember_arg(arg: str) -> tuple[str, str]:
    clean = arg.strip()
    if not clean:
        raise ValueError("remember requires content")

    label = "human"
    content = clean
    first, sep, rest = clean.partition(":")
    first_label = first.strip().casefold()
    if sep and first_label in user_memory_module.BLOCK_SPECS:
        label = first_label
        content = rest.strip()
    else:
        parts = clean.split(maxsplit=1)
        candidate = parts[0].strip().rstrip(":").casefold()
        if candidate in user_memory_module.BLOCK_SPECS:
            label = candidate
            content = parts[1].strip() if len(parts) > 1 else ""

    if not content:
        raise ValueError("remember requires content")
    if not content.startswith(("-", "*", "•")):
        content = f"- {content}"
    return label, content


def _reminder_format_message() -> str:
    return (
        "Формат: /remind in 10m текст, /remind in 2h текст "
        "или /remind 2026-06-04T18:30+03:00 текст."
    )


def _relative_delta(unit: str, amount: int) -> timedelta:
    normalized = unit.casefold()
    if normalized in {"m", "min", "minute", "minutes", "мин", "минут"}:
        return timedelta(minutes=amount)
    if normalized in {"h", "hour", "hours", "ч", "час", "часа", "часов"}:
        return timedelta(hours=amount)
    if normalized in {"d", "day", "days", "д", "дн", "день", "дня", "дней"}:
        return timedelta(days=amount)
    raise ValueError("unsupported reminder unit")


def _parse_remind_arg(arg: str, *, now: datetime | None = None) -> tuple[datetime, str]:
    now = now or datetime.now(timezone.utc)
    clean = arg.strip()
    if not clean:
        raise ValueError(_reminder_format_message())

    relative = _REMIND_RELATIVE_RE.match(clean)
    if relative:
        amount = int(relative.group(1))
        if amount <= 0:
            raise ValueError("Время напоминания должно быть в будущем.")
        text = relative.group(3).strip()
        if not text:
            raise ValueError(_reminder_format_message())
        return now + _relative_delta(relative.group(2), amount), _validate_reminder_text(text)

    parts = clean.split(maxsplit=2)
    candidates: list[tuple[str, str]] = []
    if len(parts) >= 2 and ("T" in parts[0] or parts[0].endswith("Z")):
        candidates.append((parts[0], clean.removeprefix(parts[0]).strip()))
    elif len(parts) >= 3:
        candidates.append((f"{parts[0]}T{parts[1]}", parts[2]))

    for raw_due, text in candidates:
        try:
            due_at = datetime.fromisoformat(raw_due.replace("Z", "+00:00"))
        except ValueError:
            continue
        if due_at.tzinfo is None or due_at.utcoffset() is None:
            raise ValueError("Укажи timezone в ISO-времени, например +03:00 или Z.")
        due_at = due_at.astimezone(timezone.utc)
        if due_at <= now:
            raise ValueError("Время напоминания должно быть в будущем.")
        return due_at, _validate_reminder_text(text)

    raise ValueError(_reminder_format_message())


def _validate_reminder_text(text: str) -> str:
    clean = text.strip()
    if not clean:
        raise ValueError(_reminder_format_message())
    if len(clean) > REMINDER_TEXT_LIMIT:
        raise ValueError(
            f"Текст напоминания слишком длинный: максимум {REMINDER_TEXT_LIMIT} символов."
        )
    return clean


def _format_reminder_due_at(due_at: datetime) -> str:
    return due_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


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


def _telegram_download_error_message(exc: TelegramClientError) -> str:
    text = str(exc).casefold()
    if (
        "file is too big" in text
        or "file too big" in text
        or "too large" in text
        or "exceeds configured limit" in text
    ):
        return _telegram_file_too_large_message()
    return "Не смог скачать файл из Telegram. Попробуй отправить файл ещё раз."


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
    # Delegates to the shared, tested converter so markdown **bold**/bullets the
    # model emits render as real Telegram HTML instead of literal asterisks.
    return telegram_html(text)


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


def _pending_recording_status_message_id(account: TelegramAccount | None) -> int | None:
    if account is None or not isinstance(account.active_context, dict):
        return None
    if account.active_context.get("ref_type") != "pending_recording":
        return None
    message_id = account.active_context.get("status_message_id")
    return message_id if isinstance(message_id, int) else None


async def _notify_telegram_internal_error(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any] | None,
    account: TelegramAccount | None,
    status_message_id: int | None,
) -> None:
    if not isinstance(message, dict):
        return
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return

    if account is not None:
        try:
            await _set_telegram_import_error_context(
                db,
                account,
                message=TELEGRAM_RECORDING_IMPORT_ERROR_REPLY,
            )
        except Exception:
            logger.exception("telegram import error context update failed")
            with suppress(Exception):
                await db.rollback()

    try:
        await client.send_message(
            chat_id,
            TELEGRAM_RECORDING_IMPORT_ERROR_REPLY,
            reply_to_message_id=message.get("message_id"),
        )
    except TelegramClientError as exc:
        logger.warning("telegram internal-error reply failed error=%s", type(exc).__name__)
    except Exception:
        logger.exception("telegram internal-error reply crashed")

    await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)


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
                "telegram chat action failed action=%s error=%s detail=%s",
                action,
                type(exc).__name__,
                str(exc)[:300],
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


# Telegram sentinel ids that are NOT real people and must never key an account:
# anonymous group admin (1087968824) and the Telegram service / channel
# auto-forward account (777000).
TELEGRAM_SENTINEL_USER_IDS = frozenset({1087968824, 777000})


def _guess_region(language_code: str | None) -> str:
    """Billing region from the Telegram client locale (drives payment provider)."""
    return "ru" if str(language_code or "").strip().lower().startswith("ru") else "global"


async def provision_user_from_telegram(
    db: AsyncSession,
    *,
    from_user: dict[str, Any],
    telegram_chat_id: int,
) -> User | None:
    """Create (or return the existing) WaiComputer account keyed by telegram_user_id.

    Emailless and password-less; region inferred from the Telegram locale; legal
    acceptance stamped with source='telegram'. Idempotent — re-provisioning returns
    the already-linked user. Returns None for bots and Telegram sentinel ids (an
    anonymous admin / the service account must never key a real account). Caller is
    responsible for having obtained the in-chat Terms/Privacy consent first.
    """
    from app.api.routes.auth import _record_legal_acceptance

    telegram_user_id = from_user.get("id")
    if not isinstance(telegram_user_id, int):
        return None
    if from_user.get("is_bot") or telegram_user_id in TELEGRAM_SENTINEL_USER_IDS:
        return None

    existing = await _load_account(db, telegram_user_id)
    if existing is not None:
        return await db.get(User, existing.user_id)

    locale = str(from_user.get("language_code") or "en")[:10]
    user = User(
        email=None,
        password_hash=None,
        region=_guess_region(from_user.get("language_code")),
        first_name=from_user.get("first_name"),
        last_name=from_user.get("last_name"),
        signup_origin="telegram",
    )
    _record_legal_acceptance(user, locale=locale, source="telegram")
    db.add(user)
    try:
        await db.flush()
        await _apply_telegram_link(
            db,
            user_id=user.id,
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            username=from_user.get("username"),
            first_name=from_user.get("first_name"),
            last_name=from_user.get("last_name"),
        )
        await db.commit()
    except IntegrityError:
        # A concurrent /start won the race — return the account it created.
        await db.rollback()
        existing = await _load_account(db, telegram_user_id)
        return await db.get(User, existing.user_id) if existing else None
    return user


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


_IMAGE_DOC_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".bmp")


def _extract_photo(message: dict[str, Any]) -> dict[str, Any] | None:
    """A Telegram photo (largest size) or an image sent as a document."""
    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        largest: dict[str, Any] | None = None
        best = -1
        for size in photos:
            if not isinstance(size, dict) or not size.get("file_id"):
                continue
            score = int(size.get("width") or 0) * int(size.get("height") or 0) or int(
                size.get("file_size") or 0
            )
            if score >= best:
                best = score
                largest = size
        if largest is not None:
            return {
                "kind": "photo",
                "file_id": largest.get("file_id"),
                "file_unique_id": largest.get("file_unique_id"),
                "file_size": largest.get("file_size"),
                "mime_type": "image/jpeg",
            }
    document = message.get("document")
    if isinstance(document, dict) and document.get("file_id"):
        mime = str(document.get("mime_type") or "").lower()
        name = str(document.get("file_name") or "").lower()
        if mime.startswith("image/") or name.endswith(_IMAGE_DOC_EXTENSIONS):
            return {
                "kind": "photo_document",
                "file_id": document.get("file_id"),
                "file_unique_id": document.get("file_unique_id"),
                "file_size": document.get("file_size"),
                "mime_type": mime or "image/jpeg",
                "file_name": document.get("file_name"),
            }
    return None


def _consent_inline_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "✅ Принимаю и создаю аккаунт", "callback_data": CONSENT_CALLBACK_DATA}]
        ]
    }


async def _send_consent_prompt(
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    lead: str | None = None,
) -> None:
    """Offer Telegram-only signup: a welcome + an inline Terms/Privacy consent tap."""
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    intro = lead or (
        "WaiComputer — твой второй мозг прямо в Telegram."
    )
    text = (
        f"{intro}\n\n"
        "Присылай голосовые, видео, фото, документы и ссылки — расшифрую, сделаю "
        "краткое содержание, отвечу на вопросы и запомню важное.\n\n"
        "Нажми кнопку, чтобы создать аккаунт. Это значит, что ты принимаешь "
        f"Условия использования ({TERMS_URL}) и Политику конфиденциальности "
        f"({PRIVACY_URL})."
    )
    await client.send_message(
        chat_id,
        text,
        reply_to_message_id=message.get("message_id"),
        reply_markup=_consent_inline_keyboard(),
    )


async def _handle_consent_callback(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    callback_id: str,
    from_user: dict[str, Any] | None,
    chat_id: int | None,
    message_id: int | None,
) -> None:
    """Provision a Telegram-only account after the user taps the consent button."""
    if not isinstance(from_user, dict) or chat_id is None:
        await client.answer_callback_query(callback_id)
        return
    user = await provision_user_from_telegram(db, from_user=from_user, telegram_chat_id=chat_id)
    if user is None:
        await client.answer_callback_query(
            callback_id, text="Не удалось создать аккаунт."
        )
        return
    await client.answer_callback_query(callback_id, text="Готово!")
    welcome = "Аккаунт WaiComputer создан. " + _telegram_help_text(linked=True)
    if isinstance(message_id, int):
        try:
            await client.edit_message_text(chat_id, message_id, welcome)
            return
        except TelegramClientError:
            logger.warning("consent welcome edit failed; sending fresh message")
    await client.send_message(chat_id, welcome)


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
        # Brand-new user: offer Telegram-only signup (consent tap -> provision).
        await _send_consent_prompt(client, message=message)
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


async def _handle_remember_command(
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
    try:
        label, content = _parse_remember_arg(arg)
    except ValueError:
        await client.send_message(
            chat_id,
            "Формат: /remember [human|topics|preferences] факт",
            reply_to_message_id=message.get("message_id"),
        )
        return
    conversation = await _ensure_telegram_conversation(db, account)
    try:
        await user_memory_module.write_block(
            db,
            account.user_id,
            label,
            "append",
            content,
            source="user",
            conversation_id=conversation.id,
        )
    except user_memory_module.MemoryError as exc:
        await client.send_message(
            chat_id,
            f"Не сохранил в память: {exc}",
            reply_to_message_id=message.get("message_id"),
        )
        return
    await client.send_message(
        chat_id,
        f"Запомнил в блоке {label}.",
        reply_to_message_id=message.get("message_id"),
    )


async def _handle_remind_command(
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
    try:
        due_at, reminder_text = _parse_remind_arg(arg)
    except ValueError as exc:
        await client.send_message(
            chat_id,
            str(exc),
            reply_to_message_id=message.get("message_id"),
        )
        return
    message_id = message.get("message_id")
    reminder = UserReminder(
        user_id=account.user_id,
        source="telegram",
        source_ref=(
            f"telegram:{chat_id}:{message_id}" if isinstance(message_id, int) else None
        ),
        text=reminder_text,
        due_at=due_at,
        status="pending",
        telegram_chat_id=chat_id,
        telegram_message_id=message_id if isinstance(message_id, int) else None,
        metadata_={"command": "remind"},
    )
    db.add(reminder)
    await db.flush()
    await client.send_message(
        chat_id,
        f"Поставил напоминание на {_format_reminder_due_at(due_at)}.",
        reply_to_message_id=message.get("message_id"),
    )


def _short_uuid(value: Any) -> str:
    return str(value)[:8]


@dataclass(frozen=True)
class AgentRefResolution:
    agent: Agent | None
    ambiguous_matches: tuple[Agent, ...] = ()


async def _resolve_agent_ref(
    db: AsyncSession,
    *,
    user_id: Any,
    ref: str,
) -> AgentRefResolution:
    clean = ref.strip()
    if not clean:
        return AgentRefResolution(None)
    try:
        agent_id = UUID(clean)
    except ValueError:
        agent_id = None
    if agent_id is not None:
        agent = (
            await db.execute(
                select(Agent).where(Agent.id == agent_id, Agent.user_id == user_id)
            )
        ).scalar_one_or_none()
        return AgentRefResolution(agent)

    result = await db.execute(
        select(Agent).where(Agent.user_id == user_id).order_by(Agent.created_at.desc())
    )
    normalized = clean.casefold()
    agents = list(result.scalars().all())
    exact_matches = tuple(agent for agent in agents if agent.name.casefold() == normalized)
    if len(exact_matches) == 1:
        return AgentRefResolution(exact_matches[0])
    if len(exact_matches) > 1:
        return AgentRefResolution(None, ambiguous_matches=exact_matches)
    if len(clean) >= 8:
        prefix_matches = tuple(agent for agent in agents if str(agent.id).startswith(clean))
        if len(prefix_matches) == 1:
            return AgentRefResolution(prefix_matches[0])
        if len(prefix_matches) > 1:
            return AgentRefResolution(None, ambiguous_matches=prefix_matches)
    return AgentRefResolution(None)


async def _load_agent_ref(
    db: AsyncSession,
    *,
    user_id: Any,
    ref: str,
) -> Agent | None:
    return (await _resolve_agent_ref(db, user_id=user_id, ref=ref)).agent


async def _load_run_ref(
    db: AsyncSession,
    *,
    user_id: Any,
    ref: str,
    conversation_id: UUID | None = None,
) -> AgentRun | None:
    clean = ref.strip()
    if not clean and conversation_id is not None:
        return (
            await db.execute(
                select(AgentRun)
                .where(
                    AgentRun.user_id == user_id,
                    AgentRun.conversation_id == conversation_id,
                )
                .order_by(AgentRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
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


@dataclass(frozen=True)
class AgentRunArgResolution:
    resolution: AgentRefResolution
    objective: str


async def _resolve_agent_run_arg(
    db: AsyncSession,
    *,
    user_id: Any,
    arg: str,
) -> AgentRunArgResolution:
    clean = arg.strip()
    if not clean:
        return AgentRunArgResolution(AgentRefResolution(None), "")

    result = await db.execute(
        select(Agent).where(Agent.user_id == user_id).order_by(Agent.created_at.desc())
    )
    agents = list(result.scalars().all())
    normalized = clean.casefold()
    name_matches: list[tuple[int, Agent, str]] = []
    for agent in agents:
        name = agent.name.strip()
        if not name:
            continue
        normalized_name = name.casefold()
        if normalized == normalized_name:
            name_matches.append((len(name), agent, ""))
            continue
        if normalized.startswith(normalized_name):
            remainder = clean[len(name) :]
            if remainder and remainder[0].isspace():
                name_matches.append((len(name), agent, remainder.strip()))

    if name_matches:
        best_len = max(match[0] for match in name_matches)
        best_matches = [match for match in name_matches if match[0] == best_len]
        if len(best_matches) == 1:
            _, agent, objective = best_matches[0]
            return AgentRunArgResolution(AgentRefResolution(agent), objective)
        return AgentRunArgResolution(
            AgentRefResolution(None, ambiguous_matches=tuple(match[1] for match in best_matches)),
            best_matches[0][2],
        )

    agent_ref, objective = _split_agent_run_arg(clean)
    resolution = await _resolve_agent_ref(db, user_id=user_id, ref=agent_ref)
    return AgentRunArgResolution(resolution, objective)


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
    run_arg = await _resolve_agent_run_arg(db, user_id=account.user_id, arg=arg)
    objective = run_arg.objective
    if run_arg.resolution.agent is None and not run_arg.resolution.ambiguous_matches:
        agent_ref, objective = _split_agent_run_arg(arg)
        if not agent_ref or not objective:
            await client.send_message(
                chat_id,
                "Формат: /run <agent_id или имя> <задача>",
                reply_to_message_id=message.get("message_id"),
            )
            return
    if not objective:
        await client.send_message(
            chat_id,
            "Формат: /run <agent_id или имя> <задача>",
            reply_to_message_id=message.get("message_id"),
        )
        return
    resolution = run_arg.resolution
    if resolution.ambiguous_matches:
        lines = [
            "Несколько агентов совпадают с этим именем. Запусти по id из /agents:",
        ]
        for match in resolution.ambiguous_matches[:5]:
            state = "on" if match.enabled else "off"
            lines.append(f"{_short_uuid(match.id)} · {match.name} · {match.kind} · {state}")
        await client.send_message(
            chat_id,
            "\n".join(lines),
            reply_to_message_id=message.get("message_id"),
        )
        return
    agent = resolution.agent
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
    if is_retrying_agent_run(run):
        lines.append("Wai продолжит автоматически после backoff.")
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
    run = await _load_run_ref(
        db,
        user_id=account.user_id,
        conversation_id=account.companion_conversation_id,
        ref=arg,
    )
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
    run = await _load_run_ref(
        db,
        user_id=account.user_id,
        conversation_id=account.companion_conversation_id,
        ref=arg,
    )
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
    await expire_due_actions(db)
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
                f"/approve {action.id}\n/approve_always {action.id}\n/reject {action.id}"
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
    run = await db.get(AgentRun, action.agent_run_id)
    if run is None:
        return
    agent = await db.get(Agent, run.agent_id)
    if agent is None:
        run.status = "failed"
        run.error = "Agent not found"
        run.finished_at = datetime.now(timezone.utc)
        await db.flush()
        return
    await run_job(
        db,
        action.agent_run_id,
        planner=planner_for_agent(agent),
        executor=execute_agent_step,
    )
    run_ids = pop_agent_runs_to_dispatch_after_commit(db)
    if not run_ids:
        return
    await db.flush()
    await db.commit()
    for run_id in run_ids:
        try:
            enqueue_agent_run(run_id)
        except AgentDispatchError as exc:
            child = (
                await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            ).scalar_one_or_none()
            if child is not None:
                child.status = "failed"
                child.error = exc.message
                child.finished_at = datetime.now(timezone.utc)
                await db.flush()
                await db.commit()
            raise


async def _telegram_agent_action_guard_message(
    db: AsyncSession,
    *,
    action_id: UUID,
    user_id: Any,
) -> str | None:
    action = (
        await db.execute(
            select(CompanionPendingAction).where(
                CompanionPendingAction.id == action_id,
                CompanionPendingAction.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if action is None or action.agent_run_id is None:
        return None
    run = await db.get(AgentRun, action.agent_run_id)
    if run is None or run.user_id != user_id:
        return "Не смог обработать подтверждение: запуск для действия не найден."
    if run.status in TERMINAL_STATUSES:
        return "Не смог обработать подтверждение: запуск уже завершен."
    return None


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
    guard_message = await _telegram_agent_action_guard_message(
        db,
        action_id=action_id,
        user_id=account.user_id,
    )
    if guard_message is not None:
        await client.send_message(
            chat_id,
            guard_message,
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
    if intent == "remember":
        await _handle_remember_command(db, client, message=message, account=account, arg=arg)
        return True
    if intent == "remind":
        await _handle_remind_command(db, client, message=message, account=account, arg=arg)
        return True
    if intent == "agents":
        await _handle_agents_command(db, client, message=message, account=account)
        return True
    if intent == "run":
        await _handle_run_command(db, client, message=message, account=account, arg=arg)
        return True
    if intent in {"runs", "list"}:
        await _handle_runs_command(db, client, message=message, account=account)
        return True
    if intent in {"run_status", "status"}:
        await _handle_run_status_command(db, client, message=message, account=account, arg=arg)
        return True
    if intent in {"cancel_run", "cancel"}:
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
    if intent == "approve_always":
        await _handle_approval_decision_command(
            db, client, message=message, account=account, arg=arg, decision="always"
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
    if intent in {"web", "login"}:
        await _handle_web_login_command(db, client, message=message, account=account)
        return True
    if intent in {"mcp", "token"}:
        await _handle_mcp_command(db, client, message=message, account=account)
        return True
    if intent == "email":
        await _handle_email_command(db, client, message=message, account=account, arg=arg)
        return True
    if intent == "export":
        await _handle_export_command(db, client, message=message, account=account)
        return True
    if intent == "delete":
        await _send_delete_confirm(client, message=message)
        return True
    return False


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def _handle_email_command(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    arg: str,
) -> None:
    """Verify-then-link: email a confirm link that attaches the address on click."""
    from app.core.email import send_email_verification_email
    from app.core.security import create_email_verification_token

    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    user = await _ensure_active_user(db, client, message=message, account=account)
    if user is None:
        return
    email = arg.strip().lower()
    if not _EMAIL_RE.match(email):
        await client.send_message(
            chat_id,
            "Формат: /email you@example.com",
            reply_to_message_id=message.get("message_id"),
        )
        return
    existing = (
        await db.execute(select(User).where(User.email == email, User.id != account.user_id))
    ).scalar_one_or_none()
    if existing is not None:
        await client.send_message(
            chat_id,
            "Этот email уже привязан к другому аккаунту WaiComputer. "
            "Войди в тот аккаунт и привяжи Telegram оттуда.",
            reply_to_message_id=message.get("message_id"),
        )
        return
    token = create_email_verification_token(account.user_id, email)
    locale = "ru" if (user.region or "") == "ru" else "en"
    try:
        await send_email_verification_email(email, token, locale=locale)
    except Exception:  # noqa: BLE001 - surface the failure; never attach an unverified email.
        logger.exception("email verification send failed")
        await client.send_message(
            chat_id,
            "Не удалось отправить письмо. Попробуй позже.",
            reply_to_message_id=message.get("message_id"),
        )
        return
    await client.send_message(
        chat_id,
        f"Отправил письмо на {email}. Нажми ссылку в письме, чтобы подтвердить адрес.",
        reply_to_message_id=message.get("message_id"),
    )


async def _handle_export_command(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
) -> None:
    """Send the user a JSON export of their data (recordings, action items, memory)."""
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    if await _ensure_active_user(db, client, message=message, account=account) is None:
        return
    async def _all_pages(fetch) -> list:
        items: list = []
        cursor: str | None = None
        for _ in range(100):  # safety cap (~2000 items)
            page = await fetch(cursor)
            items.extend(page.get("results", []))
            cursor = page.get("next_cursor")
            if not cursor:
                break
        return items

    recordings = await _all_pages(
        lambda c: list_recordings_for_mcp(db, account.user_id, limit=20, cursor=c)
    )
    action_items = await _all_pages(
        lambda c: list_action_items_for_mcp(db, account.user_id, limit=20, cursor=c)
    )
    blocks = await user_memory_module.get_or_seed_blocks(db, account.user_id)
    export = {
        "recordings": recordings,
        "action_items": action_items,
        "memory": user_memory_module.render_for_prompt(blocks),
    }
    payload = json.dumps(export, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    await client.send_document(
        chat_id,
        filename="waicomputer-export.json",
        data=payload,
        reply_to_message_id=message.get("message_id"),
    )
    await client.send_message(
        chat_id,
        f"Экспорт готов: {len(recordings)} записей, {len(action_items)} задач.",
        reply_to_message_id=message.get("message_id"),
    )


def _delete_inline_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "🗑 Да, удалить навсегда", "callback_data": DELETE_CALLBACK_DATA}]
        ]
    }


async def _send_delete_confirm(
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
) -> None:
    """Ask for an explicit tap before destructive account deletion."""
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    await client.send_message(
        chat_id,
        (
            "Удалить аккаунт WaiComputer и ВСЕ данные (записи, расшифровки, "
            "саммари, задачи, память)? Это необратимо.\n\n"
            "Сделай /export, если хочешь сначала скачать копию."
        ),
        reply_to_message_id=message.get("message_id"),
        reply_markup=_delete_inline_keyboard(),
    )


async def _handle_delete_callback(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    account: TelegramAccount,
    callback_id: str,
    chat_id: int | None,
    message_id: int | None,
) -> None:
    """Permanently delete the account after the confirm tap (cascades all data)."""
    user = await db.get(User, account.user_id)
    if user is None:
        await client.answer_callback_query(callback_id, text="Аккаунт не найден.")
        return
    await db.delete(user)  # ON DELETE CASCADE removes recordings/items/telegram link
    await db.commit()
    await client.answer_callback_query(callback_id, text="Удалено.")
    farewell = "Аккаунт и все данные удалены. Чтобы начать заново, отправь /start."
    if chat_id is None:
        return
    if isinstance(message_id, int):
        try:
            await client.edit_message_text(chat_id, message_id, farewell)
            return
        except TelegramClientError:
            logger.warning("delete farewell edit failed; sending fresh message")
    await client.send_message(chat_id, farewell)


async def _handle_web_login_command(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
) -> None:
    """DM a one-time web sign-in link (reuses the magic-link verify flow)."""
    from app.api.routes.auth import _new_magic_token

    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    user = await _ensure_active_user(db, client, message=message, account=account)
    if user is None:
        return
    token = _new_magic_token()
    user.magic_link_token = token
    user.magic_link_expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    await db.flush()
    await db.commit()
    url = f"{settings.frontend_url}/auth/verify?token={token}"
    await client.send_message(
        chat_id,
        (
            "Ссылка для входа в веб-версию WaiComputer (одноразовая, действует "
            f"15 минут):\n\n{url}\n\n"
            "Открой её на компьютере, чтобы пользоваться WaiComputer в браузере."
        ),
        reply_to_message_id=message.get("message_id"),
    )


async def _handle_mcp_command(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
) -> None:
    """Mint a read-only wc_live_ MCP token in the trusted bot context and DM it once."""
    from app.core.api_keys import API_KEY_READ_SCOPE, generate_api_key
    from app.models.api_key import ApiKey

    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    if await _ensure_active_user(db, client, message=message, account=account) is None:
        return
    plaintext, token_hash_value, prefix, last4 = generate_api_key()
    db.add(
        ApiKey(
            user_id=account.user_id,
            name="Telegram",
            token_hash=token_hash_value,
            prefix=prefix,
            last4=last4,
            scopes=[API_KEY_READ_SCOPE],
        )
    )
    await db.flush()
    await db.commit()
    await client.send_message(
        chat_id,
        (
            "Твой read-only MCP-токен (показываю один раз — сохрани его):\n\n"
            f"<code>{escape(plaintext)}</code>\n\n"
            "MCP URL: https://wai.computer/mcp\n"
            "Подключай как Bearer-токен. Управлять ключами — в Settings → API tokens."
        ),
        reply_to_message_id=message.get("message_id"),
        parse_mode="HTML",
    )


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
    return conversation


def _telegram_context(ref_type: str, ref_id: UUID, title: str | None) -> dict[str, Any]:
    return {
        "ref_type": ref_type,
        "ref_id": str(ref_id),
        "title": title,
        "source": "telegram",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _telegram_turn_context(
    context: Any,
    *,
    input_modality: str = "text",
    is_reply_to_assistant: bool = False,
) -> TurnContext:
    recording_title: str | None = None
    if isinstance(context, dict) and context.get("ref_type") == "recording":
        recording_title = str(context.get("title") or "").strip() or None
    return TurnContext(
        viewing_recording_title=recording_title,
        input_modality=input_modality,
        is_reply_to_assistant=is_reply_to_assistant,
        surface="telegram",
    )


def _apply_telegram_active_context_scope(
    conversation: Conversation,
    context: dict[str, Any] | None,
) -> None:
    scope = dict(conversation.scope or {})
    if context is None:
        scope.pop("active_context", None)
        scope.pop("recording_ids", None)
    else:
        scope["active_context"] = context
        ref_id = context.get("ref_id")
        if context.get("ref_type") == "recording" and isinstance(ref_id, str) and ref_id:
            scope["recording_ids"] = [ref_id]
        else:
            scope.pop("recording_ids", None)
    conversation.scope = scope


async def _set_telegram_active_context(
    db: AsyncSession,
    account: TelegramAccount,
    *,
    ref_type: str,
    ref_id: UUID,
    title: str | None,
) -> None:
    context = _telegram_context(ref_type, ref_id, title)
    await _write_telegram_active_context(db, account, context)


async def _write_telegram_active_context(
    db: AsyncSession,
    account: TelegramAccount,
    context: dict[str, Any] | None,
) -> None:
    account.active_context = context
    conversation = await _ensure_telegram_conversation(db, account)
    _apply_telegram_active_context_scope(conversation, context)
    await db.flush()


async def _set_telegram_pending_recording_context(
    db: AsyncSession,
    account: TelegramAccount,
    *,
    message: dict[str, Any],
    media: dict[str, Any],
    status_message_id: int | None,
) -> None:
    message_id = message.get("message_id")
    context = {
        "ref_type": "pending_recording",
        "source": "telegram",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "media_kind": str(media.get("kind") or "media"),
        "telegram_message_id": message_id if isinstance(message_id, int) else None,
        "status_message_id": status_message_id,
    }
    await _write_telegram_active_context(db, account, context)
    await db.commit()


async def _set_telegram_import_error_context(
    db: AsyncSession,
    account: TelegramAccount,
    *,
    message: str,
) -> None:
    context = {
        "ref_type": "recording_import_error",
        "source": "telegram",
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "message": message,
    }
    await _write_telegram_active_context(db, account, context)


async def _clear_telegram_active_context(
    db: AsyncSession,
    account: TelegramAccount,
) -> None:
    await _write_telegram_active_context(db, account, None)


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
    await _set_telegram_active_context(
        db,
        account,
        ref_type="item",
        ref_id=item.id,
        title=item.title,
    )
    await _send_chunks(
        client,
        chat_id,
        reply,
        reply_to_message_id=message.get("message_id"),
        parse_mode="HTML",
    )


async def _format_pending_actions_for_run(db: AsyncSession, run: AgentRun) -> str:
    actions = list(
        (
            await db.execute(
                select(CompanionPendingAction)
                .where(
                    CompanionPendingAction.agent_run_id == run.id,
                    CompanionPendingAction.status == "pending",
                )
                .order_by(CompanionPendingAction.created_at)
            )
        )
        .scalars()
        .all()
    )
    if not actions:
        return ""
    lines = ["Нужно подтверждение:"]
    for action in actions:
        manifest = action.action_manifest or {}
        preview = str(manifest.get("preview") or action.tool_name).strip()
        recipient = f" · {action.recipient_display}" if action.recipient_display else ""
        lines.append(
            f"{action.id}\n{action.tool_name} · {action.kind}{recipient}\n"
            f"{preview}\n/approve {action.id}\n"
            f"/approve_always {action.id}\n/reject {action.id}"
        )
    return "\n\n".join(lines)


_ACTION_CALLBACK_PREFIX = "act"


def _action_inline_keyboard(action_id: str) -> dict[str, Any]:
    """Inline Approve / Always / Reject buttons. callback_data is
    'act:<decision>:<uuid>' (~47 bytes, under Telegram's 64-byte cap)."""

    def cb(decision: str) -> str:
        return f"{_ACTION_CALLBACK_PREFIX}:{decision}:{action_id}"

    return {
        "inline_keyboard": [
            [
                {"text": "✅ Подтвердить", "callback_data": cb("once")},
                {"text": "🔁 Всегда", "callback_data": cb("always")},
                {"text": "✕ Отклонить", "callback_data": cb("reject")},
            ]
        ]
    }


async def _send_action_proposal(
    client: TelegramBotClient, chat_id: int, action: ActionProposedEvent
) -> None:
    preview = action.preview.strip() or action.tool
    await client.send_message(
        chat_id,
        f"Нужно подтверждение:\n{preview}",
        reply_markup=_action_inline_keyboard(action.action_id),
    )


def _parse_action_callback(data: str) -> tuple[str, str] | None:
    """Parse 'act:<decision>:<action_id>' → (decision, action_id)."""
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != _ACTION_CALLBACK_PREFIX:
        return None
    decision, action_id = parts[1], parts[2]
    if decision not in {"once", "always", "reject"}:
        return None
    return decision, action_id


async def _resolve_action_for_telegram(
    db: AsyncSession,
    *,
    account: TelegramAccount,
    action_id: UUID,
    decision: str,
) -> tuple[str, str]:
    """Resolve a tapped action via the shared helper (same path as the web
    route), resume any linked agent run, and return (toast, edited-message)."""
    guard = await _telegram_agent_action_guard_message(
        db, action_id=action_id, user_id=account.user_id
    )
    if guard is not None:
        return ("Не удалось", guard)
    try:
        outcome = await resolve_action_for_user(
            db, action_id=action_id, user_id=account.user_id, decision=decision
        )
    except ApprovalError as exc:
        await db.commit()
        return ("Не удалось", f"Не смог обработать: {exc.message}")
    except ActuationError as exc:
        await db.commit()
        return ("Ошибка", f"Действие не выполнено: {exc.message}")
    await _resume_agent_after_telegram_action(db, outcome.row)
    await db.commit()
    if decision == "reject":
        return ("Отклонено", "✕ Отклонено.")
    if outcome.status == "dispatched":
        return ("Отправлено на Mac", "✅ Отправлено на ваш Mac.")
    return ("Готово", "✅ Готово.")


async def _handle_callback_query(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    callback_query: dict[str, Any],
) -> None:
    callback_id = callback_query.get("id")
    if not isinstance(callback_id, str):
        return
    from_user = callback_query.get("from")
    telegram_user_id = from_user.get("id") if isinstance(from_user, dict) else None
    data = callback_query.get("data")
    cb_message = callback_query.get("message")
    chat_id = _telegram_chat_id(cb_message) if isinstance(cb_message, dict) else None
    message_id = (
        cb_message.get("message_id") if isinstance(cb_message, dict) else None
    )

    if not isinstance(telegram_user_id, int) or not isinstance(data, str):
        await client.answer_callback_query(callback_id)
        return
    # Consent tap: the user has NO account yet — provision before the account guard.
    if data == CONSENT_CALLBACK_DATA:
        await _handle_consent_callback(
            db,
            client,
            callback_id=callback_id,
            from_user=from_user if isinstance(from_user, dict) else None,
            chat_id=chat_id,
            message_id=message_id if isinstance(message_id, int) else None,
        )
        return
    account = await _load_account(db, telegram_user_id)
    if account is None:
        await client.answer_callback_query(
            callback_id, text="Сначала привяжи Telegram."
        )
        return
    if data == DELETE_CALLBACK_DATA:
        await _handle_delete_callback(
            db,
            client,
            account=account,
            callback_id=callback_id,
            chat_id=chat_id,
            message_id=message_id if isinstance(message_id, int) else None,
        )
        return
    parsed = _parse_action_callback(data)
    if parsed is None:
        await client.answer_callback_query(callback_id)
        return
    decision, action_id_raw = parsed
    try:
        action_id = UUID(action_id_raw)
    except ValueError:
        await client.answer_callback_query(callback_id)
        return

    short, full = await _resolve_action_for_telegram(
        db, account=account, action_id=action_id, decision=decision
    )
    await client.answer_callback_query(callback_id, text=short)
    if chat_id is not None and isinstance(message_id, int):
        try:
            await client.edit_message_text(chat_id, message_id, full)
        except TelegramClientError:
            pass  # best-effort; the message may be too old to edit


async def _format_wai_run_reply(db: AsyncSession, run: AgentRun) -> str:
    if is_retrying_agent_run(run):
        return (
            "Wai получил временный лимит провайдера и продолжает задачу в фоне. "
            f"Проверить статус: /status {run.id}"
        )
    if run.status == "failed":
        return f"Не получилось выполнить задачу Wai: {run.error or 'ошибка агента'}"
    result = run.result or {}
    text = str(result.get("output_text") or "").strip()
    artifacts = result.get("artifacts")
    if isinstance(artifacts, list) and artifacts:
        artifact_lines = ["Артефакты:"]
        for artifact in artifacts[:5]:
            if not isinstance(artifact, dict):
                continue
            title = str(artifact.get("title") or artifact.get("item_id") or "artifact")
            kind = str(artifact.get("kind") or "item")
            artifact_lines.append(f"- {title} ({kind})")
        text = f"{text}\n\n" + "\n".join(artifact_lines) if text else "\n".join(artifact_lines)
    approvals = await _format_pending_actions_for_run(db, run)
    if approvals:
        text = f"{text}\n\n{approvals}".strip()
    if text:
        return text
    return f"Wai run {run.id} status: {run.status}"


def _telegram_wai_turn_failure_reply(exc: BaseException) -> str:
    if is_retryable_exception(exc):
        return TELEGRAM_WAI_RETRYABLE_ERROR_REPLY
    return TELEGRAM_WAI_GENERIC_ERROR_REPLY


async def _handle_text_message(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    text: str,
    input_modality: str = "text",
) -> None:
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    if await _ensure_active_user(db, client, message=message, account=account) is None:
        return
    status_reply = _telegram_status_reply_for_text(account.active_context, text)
    if status_reply is not None:
        await client.send_message(
            chat_id,
            status_reply,
            reply_to_message_id=message.get("message_id"),
        )
        return
    conversation = await _ensure_telegram_conversation(db, account)
    _apply_telegram_active_context_scope(conversation, account.active_context)
    await db.flush()
    chunks: list[str] = []
    proposed_actions: list[ActionProposedEvent] = []
    action_task = asyncio.create_task(_send_chat_action_until_cancelled(client, chat_id))
    try:
        async for event in run_turn(
            db,
            account.user_id,
            conversation.id,
            text,
            turn_context=_telegram_turn_context(
                account.active_context,
                input_modality=input_modality,
                is_reply_to_assistant=_reply_is_from_assistant(message),
            ),
            enable_actions=True,
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
            _telegram_wai_turn_failure_reply(exc),
            reply_to_message_id=message.get("message_id"),
        )
        return
    except Exception as exc:  # noqa: BLE001 - Telegram must surface the failed turn.
        logger.warning("telegram Wai turn failed error=%s", type(exc).__name__)
        await client.send_message(
            chat_id,
            _telegram_wai_turn_failure_reply(exc),
            reply_to_message_id=message.get("message_id"),
        )
        return
    finally:
        await _stop_chat_action_task(action_task)

    answer = "".join(chunks).strip()
    if not answer and not proposed_actions:
        answer = "Wai не вернул ответ."
    if answer:
        await _send_chunks(
            client,
            chat_id,
            answer,
            reply_to_message_id=message.get("message_id"),
        )
    # Surface each proposed action as a tap-to-approve card (inline buttons)
    # rather than a "/approve <uuid>" command the user must copy-paste.
    for action in proposed_actions:
        await _send_action_proposal(client, chat_id, action)


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
    await _set_telegram_active_context(
        db,
        account,
        ref_type="item",
        ref_id=item.id,
        title=item.title,
    )
    await _send_chunks(
        client,
        chat_id,
        reply,
        reply_to_message_id=message.get("message_id"),
        parse_mode="HTML",
    )


async def _handle_photo_message(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    photo: dict[str, Any],
) -> None:
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    if await _ensure_active_user(db, client, message=message, account=account) is None:
        return

    file_id = photo.get("file_id")
    if not isinstance(file_id, str):
        return
    file_size = photo.get("file_size")
    if isinstance(file_size, int) and file_size > settings.telegram_download_max_bytes:
        await client.send_message(
            chat_id,
            _telegram_file_too_large_message(),
            reply_to_message_id=message.get("message_id"),
        )
        return

    status_response = await client.send_message(
        chat_id,
        "Принял фото. Распознаю и делаю краткое содержание.",
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
        body = await ocr_image(data, mime_type=str(photo.get("mime_type") or "image/jpeg"))
    except TelegramFileTooLargeError:
        await client.send_message(
            chat_id,
            _telegram_file_too_large_message(),
            reply_to_message_id=message.get("message_id"),
        )
        return
    except OcrError:
        await client.send_message(
            chat_id,
            "Не смог распознать фото. Попробуй ещё раз позже.",
            reply_to_message_id=message.get("message_id"),
        )
        return
    finally:
        await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)

    if not body.strip():
        await client.send_message(
            chat_id,
            "На фото не нашёл текста или распознаваемого содержания.",
            reply_to_message_id=message.get("message_id"),
        )
        return

    caption = str(message.get("caption") or "").strip()
    source_ref = str(photo.get("file_unique_id") or file_id)
    try:
        item, created = await ingest_item(
            db,
            account.user_id,
            source="telegram",
            source_ref=source_ref,
            kind="image",
            title=clean_title(caption) or "Фото",
            body=(f"{caption}\n\n{body}".strip() if caption else body),
            metadata={
                "telegram": {
                    "file_unique_id": photo.get("file_unique_id"),
                    "mime_type": photo.get("mime_type"),
                    "kind": photo.get("kind"),
                    "size": len(data),
                }
            },
            embed=True,
        )
        await db.flush()
    except Exception:  # noqa: BLE001 - failed import should be explicit to the sender.
        logger.exception("telegram photo ingest failed")
        await client.send_message(
            chat_id,
            "Не смог сохранить фото в материалы. Попробуй позже.",
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
            logger.exception("telegram photo processing failed")
            await client.send_message(
                chat_id,
                "Сохранил фото, но не смог сделать краткое содержание. Попробуй позже.",
                reply_to_message_id=message.get("message_id"),
            )
            return
        finally:
            await _stop_chat_action_task(action_task)

    reply = format_item_reply(item, summary)
    await _set_telegram_active_context(
        db,
        account,
        ref_type="item",
        ref_id=item.id,
        title=item.title,
    )
    await _send_chunks(
        client,
        chat_id,
        reply,
        reply_to_message_id=message.get("message_id"),
        parse_mode="HTML",
    )


def _is_forwarded(message: dict[str, Any]) -> bool:
    """True when the message was forwarded from someone else — archived content, not
    something the user is saying to Wai."""
    return bool(
        message.get("forward_origin")
        or message.get("forward_from")
        or message.get("forward_from_chat")
        or message.get("forward_sender_name")
    )


FORWARDED_TEXT_MIN_CHARS = 400

_UNSUPPORTED_MESSAGE_KINDS = {
    "sticker": "стикеры",
    "animation": "GIF и анимации",
    "location": "геолокацию",
    "venue": "места на карте",
    "contact": "контакты",
    "poll": "опросы",
    "dice": "кубики и эмодзи-игры",
    "story": "истории",
    "game": "игры",
}


def _unsupported_message_kind(message: dict[str, Any]) -> str | None:
    """Human label for a message type we knowingly don't ingest yet (else None)."""
    for key, label in _UNSUPPORTED_MESSAGE_KINDS.items():
        if message.get(key) is not None:
            return label
    return None


def _is_long_form_text(text: str) -> bool:
    """True for substantial pasted/forwarded prose worth saving as a material."""
    return len(text.strip()) >= FORWARDED_TEXT_MIN_CHARS


def _reply_is_from_assistant(message: dict[str, Any]) -> bool:
    """True when this message is a reply to one of the bot's own messages. In a
    private 1:1 chat the only bot whose messages appear is Wai, so a reply to a bot
    message is unambiguously conversational."""
    reply = message.get("reply_to_message")
    if not isinstance(reply, dict):
        return False
    sender = reply.get("from")
    return isinstance(sender, dict) and bool(sender.get("is_bot"))


async def _download_telegram_media(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    account: TelegramAccount,
    message: dict[str, Any],
    file_id: str,
    status_message_id: int | None,
) -> tuple[bytes, str | None] | None:
    """Download a Telegram file with size guards. On failure it sends the too-large
    reply, records the import-error context, clears any status message, and returns
    None. Returns ``(data, file_path)`` on success."""
    chat_id = _telegram_chat_id(message)

    async def _too_large(*, reply: bool) -> None:
        message_text = _telegram_file_too_large_message()
        await _set_telegram_import_error_context(db, account, message=message_text)
        await client.send_message(
            chat_id,
            message_text,
            reply_to_message_id=message.get("message_id") if reply else None,
        )
        await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)

    try:
        tg_file = await client.get_file(file_id)
    except TelegramClientError as exc:
        message_text = _telegram_download_error_message(exc)
        await _set_telegram_import_error_context(db, account, message=message_text)
        await client.send_message(
            chat_id,
            message_text,
            reply_to_message_id=message.get("message_id"),
        )
        await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)
        return None
    if tg_file.file_size is not None and tg_file.file_size > settings.telegram_download_max_bytes:
        await _too_large(reply=False)
        return None
    try:
        data = await client.download_file(
            tg_file, max_bytes=settings.telegram_download_max_bytes
        )
    except TelegramFileTooLargeError:
        await _too_large(reply=True)
        return None
    except TelegramClientError as exc:
        message_text = _telegram_download_error_message(exc)
        await _set_telegram_import_error_context(db, account, message=message_text)
        await client.send_message(
            chat_id,
            message_text,
            reply_to_message_id=message.get("message_id"),
        )
        await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)
        return None
    if len(data) > settings.telegram_download_max_bytes:
        await _too_large(reply=False)
        return None
    return data, tg_file.file_path


async def _recent_assistant_text(db: AsyncSession, account: TelegramAccount) -> str | None:
    """The bot's most recent message in this chat, so the voice classifier can tell a
    short spoken reply (e.g. answering Wai's question) from a standalone note even
    when the user didn't use Telegram's reply feature. Best-effort; None if no chat yet."""
    conv_id = account.companion_conversation_id
    if conv_id is None:
        return None
    row = (
        await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conv_id,
                ChatMessage.role == "assistant",
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    text = _message_content_to_text(row.content).strip()
    return text or None


async def _route_media_message(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    media: dict[str, Any],
) -> None:
    """Decide whether an incoming voice note is a library recording or a message to
    Wai, then dispatch.

    Non-voice media and the confident cases (forwarded, long-form) skip straight to
    the historical import flow. A short voice note is transcribed once; if the
    transcript is addressed to Wai it is answered like a typed message, otherwise it
    is filed reusing that same download + transcript (no second STT pass)."""
    decision = route_voice_by_metadata(
        kind=str(media.get("kind") or "media"),
        duration_seconds=_telegram_media_duration_seconds(media),
        is_forwarded=_is_forwarded(message),
        is_reply_to_assistant=_reply_is_from_assistant(message),
        max_command_seconds=settings.telegram_voice_command_max_seconds,
    )
    if decision is not None and decision.route == "file":
        # Privacy-safe: only the route + reason tag, never the transcript.
        logger.info("telegram voice routed route=file reason=%s", decision.reason)
        await _handle_media_message(
            db, client, message=message, account=account, media=media
        )
        return

    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    user = await _ensure_active_user(db, client, message=message, account=account)
    if user is None:
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

    action_task = asyncio.create_task(_send_chat_action_until_cancelled(client, chat_id))
    try:
        downloaded = await _download_telegram_media(
            db, client, account=account, message=message, file_id=file_id, status_message_id=None
        )
        if downloaded is None:
            return
        data, file_path = downloaded
        try:
            transcribed = await transcribe_media_bytes(
                db=db,
                user=user,
                data=data,
                filename=media.get("file_name") or file_path,
                content_type=media.get("mime_type"),
                language=user.default_language,
                duration_seconds=_telegram_media_duration_seconds(media),
                source_label="telegram",
            )
        except RecordingImportError as exc:
            await _set_telegram_import_error_context(db, account, message=exc.message)
            await client.send_message(
                chat_id, exc.message, reply_to_message_id=message.get("message_id")
            )
            return
    finally:
        await _stop_chat_action_task(action_task)

    if decision is None:
        if not transcribed.has_speech:
            decision = VoiceRouteDecision("file", "no_speech")
        else:
            decision = await classify_voice_transcript(
                transcribed.transcript_text,
                recent_assistant_message=await _recent_assistant_text(db, account),
            )

    # Privacy-safe: only the route + reason tag, never the transcript.
    logger.info("telegram voice routed route=%s reason=%s", decision.route, decision.reason)

    if decision.route == "message" and transcribed.has_speech:
        await _handle_voice_as_message(
            db, client, message=message, account=account, transcript=transcribed.transcript_text
        )
        return

    # File it, reusing the download + transcript we already produced.
    await _handle_media_message(
        db,
        client,
        message=message,
        account=account,
        media=media,
        prefetched=(data, file_path),
        precomputed=transcribed,
    )


async def _handle_voice_as_message(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    transcript: str,
) -> None:
    """A voice note addressed to Wai: echo what was heard (STT transparency), then
    route the transcript through the same pipeline as a typed message."""
    chat_id = _telegram_chat_id(message)
    if chat_id is not None:
        echo = transcript.strip()
        if len(echo) > 600:
            echo = echo[:600].rstrip() + "…"
        await client.send_message(
            chat_id,
            f"🎙 <i>«{escape(echo)}»</i>",
            reply_to_message_id=message.get("message_id"),
            parse_mode="HTML",
        )
    await _route_text_like(
        db,
        client,
        message=message,
        account=account,
        text=transcript,
        input_modality="voice",
    )


async def _handle_forwarded_text(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    text: str,
) -> None:
    """Save substantial forwarded/pasted prose as a material with an AI summary."""
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    if await _ensure_active_user(db, client, message=message, account=account) is None:
        return

    status_response = await client.send_message(
        chat_id,
        "Сохраняю в материалы и делаю краткое содержание.",
        reply_to_message_id=message.get("message_id"),
    )
    status_message_id = _sent_message_id(status_response)
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    message_id = message.get("message_id")
    source_ref = f"telegram:text:{chat_id}:{message_id}" if isinstance(message_id, int) else None
    try:
        item, created = await ingest_item(
            db,
            account.user_id,
            source="telegram",
            source_ref=source_ref,
            kind="note",
            title=clean_title(first_line) or "Пересланный текст",
            body=text,
            metadata={"telegram": {"forwarded": True}},
            embed=True,
        )
        await db.flush()
    except Exception:  # noqa: BLE001 - failed import should be explicit to the sender.
        logger.exception("telegram forwarded text ingest failed")
        await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)
        await client.send_message(
            chat_id,
            "Не смог сохранить текст в материалы. Попробуй позже.",
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
            logger.exception("telegram forwarded text summary failed")
            await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)
            await client.send_message(
                chat_id,
                "Сохранил текст, но не смог сделать краткое содержание. Попробуй позже.",
                reply_to_message_id=message.get("message_id"),
            )
            return
        finally:
            await _stop_chat_action_task(action_task)

    await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)
    reply = format_item_reply(item, summary)
    await _set_telegram_active_context(
        db, account, ref_type="item", ref_id=item.id, title=item.title
    )
    await _send_chunks(
        client,
        chat_id,
        reply,
        reply_to_message_id=message.get("message_id"),
        parse_mode="HTML",
    )


async def _route_text_like(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    text: str,
    input_modality: str = "text",
) -> None:
    """Route a typed-or-spoken message: structured command, URL ingest, forwarded
    long-form prose, or agent turn. Shared by the text branch and voice notes routed
    to chat so both modalities behave identically."""
    text_intent = _text_intent(text)
    forwarded_url = find_first_url(text)
    if text_intent is not None:
        intent, arg = text_intent
        await _handle_account_command(
            db, client, message=message, account=account, intent=intent, arg=arg
        )
    elif forwarded_url is not None:
        await _handle_url_message(
            db, client, message=message, account=account, url=forwarded_url
        )
    elif input_modality == "text" and _is_forwarded(message) and _is_long_form_text(text):
        await _handle_forwarded_text(
            db, client, message=message, account=account, text=text
        )
    else:
        await _handle_text_message(
            db,
            client,
            message=message,
            account=account,
            text=text,
            input_modality=input_modality,
        )


async def _handle_media_message(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    media: dict[str, Any],
    prefetched: tuple[bytes, str | None] | None = None,
    precomputed: TranscribedMedia | None = None,
) -> None:
    """Save media as a library recording.

    ``prefetched`` / ``precomputed`` let intent routing hand over a voice note it
    already downloaded and transcribed so it is filed without a second download or
    STT pass; when both are None this is the unchanged historical import flow.
    """
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    user = await _ensure_active_user(db, client, message=message, account=account)
    if user is None:
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
    await _set_telegram_pending_recording_context(
        db,
        account,
        message=message,
        media=media,
        status_message_id=status_message_id,
    )

    if prefetched is not None:
        data, downloaded_file_path = prefetched
    else:
        downloaded = await _download_telegram_media(
            db,
            client,
            account=account,
            message=message,
            file_id=file_id,
            status_message_id=status_message_id,
        )
        if downloaded is None:
            return
        data, downloaded_file_path = downloaded

    caption = str(message.get("caption") or "").strip()
    title = caption[:500] if caption else None
    action_task = asyncio.create_task(_send_chat_action_until_cancelled(client, chat_id))
    try:
        result = await import_media_as_recording(
            db=db,
            user=user,
            data=data,
            filename=media.get("file_name") or downloaded_file_path,
            content_type=media.get("mime_type"),
            title=title,
            source_label="telegram",
            language=user.default_language,
            duration_seconds=_telegram_media_duration_seconds(media),
            precomputed=precomputed,
        )
    except RecordingImportError as exc:
        logger.warning(
            "telegram media import failed code=%s kind=%s",
            exc.code,
            media.get("kind"),
        )
        await _set_telegram_import_error_context(db, account, message=exc.message)
        await client.send_message(chat_id, exc.message)
        await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)
        return
    except Exception:  # noqa: BLE001 - a Telegram import must always answer the sender.
        logger.exception("telegram media import crashed kind=%s", media.get("kind"))
        await _set_telegram_import_error_context(
            db,
            account,
            message=TELEGRAM_RECORDING_IMPORT_ERROR_REPLY,
        )
        await client.send_message(
            chat_id,
            TELEGRAM_RECORDING_IMPORT_ERROR_REPLY,
            reply_to_message_id=message.get("message_id"),
        )
        await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)
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
    recording_id = getattr(result.recording, "id", None)
    if recording_id is not None:
        await _set_telegram_active_context(
            db,
            account,
            ref_type="recording",
            ref_id=recording_id,
            title=result.recording.title,
        )
    else:
        await _clear_telegram_active_context(db, account)
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
        message: dict[str, Any] | None = None
        account: TelegramAccount | None = None
        try:
            callback_query = update.get("callback_query")
            if isinstance(callback_query, dict):
                await _handle_callback_query(
                    db, client, callback_query=callback_query
                )
                await _mark_update(db, update_id, "completed")
                return

            raw_message = update.get("message")
            if not isinstance(raw_message, dict):
                await _mark_update(db, update_id, "completed")
                return
            message = raw_message

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
            if command and command[0] == "/start":
                await _handle_start_command(
                    db,
                    client,
                    message=message,
                    arg=command[1],
                )
                await _mark_update(db, update_id, "completed")
                return

            account = await _load_account(db, telegram_user_id)
            if command and command[0] == "/link":
                # Explicit: link this Telegram to an EXISTING WaiComputer account.
                if account is not None:
                    await _handle_help_command(client, message=message, linked=True)
                else:
                    await _send_bot_link_code(
                        db,
                        client,
                        message=message,
                        intro="Чтобы привязать уже существующий аккаунт WaiComputer:",
                    )
                await _mark_update(db, update_id, "completed")
                return
            if command and command[0] == "/help":
                if account is None:
                    await _send_consent_prompt(client, message=message)
                else:
                    await _handle_help_command(client, message=message, linked=True)
                await _mark_update(db, update_id, "completed")
                return

            if account is None:
                # First message from a brand-new user (e.g. a voice note before
                # signup): offer account creation; they resend after the consent tap.
                await _send_consent_prompt(
                    client,
                    message=message,
                    lead="Похоже, у тебя ещё нет аккаунта WaiComputer.",
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
                await _route_media_message(
                    db,
                    client,
                    message=message,
                    account=account,
                    media=media,
                )
            elif (photo := _extract_photo(message)) is not None:
                await _handle_photo_message(
                    db,
                    client,
                    message=message,
                    account=account,
                    photo=photo,
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
                    unsupported = _unsupported_message_kind(message)
                    if unsupported is not None:
                        await client.send_message(
                            chat_id,
                            f"Пока не умею обрабатывать {unsupported}. "
                            "Пришли голосовое, видео, фото, документ или текст.",
                            reply_to_message_id=message.get("message_id"),
                        )
                    else:
                        await client.send_message(
                            chat_id,
                            "Пришли голосовое, видео, фото, документ или вопрос текстом.",
                            reply_to_message_id=message.get("message_id"),
                        )
                else:
                    await _route_text_like(
                        db,
                        client,
                        message=message,
                        account=account,
                        text=text,
                        input_modality="text",
                    )
            await _mark_update(db, update_id, "completed")
        except (TelegramClientError, RecordingImportError) as exc:
            logger.warning(
                "telegram update failed update_id=%s code=%s detail=%s",
                update_id,
                type(exc).__name__,
                str(exc)[:500],
            )
            await _mark_update(
                db,
                update_id,
                "failed",
                type(exc).__name__,
                str(exc)[:2000] or "Telegram update failed",
            )
        except Exception:
            logger.exception("telegram update failed update_id=%s", update_id)
            status_message_id = None
            with suppress(Exception):
                status_message_id = _pending_recording_status_message_id(account)
            notify_account = account
            if not db.is_active:
                with suppress(Exception):
                    await db.rollback()
                notify_account = None
            await _notify_telegram_internal_error(
                db,
                client,
                message=message,
                account=notify_account,
                status_message_id=status_message_id,
            )
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
