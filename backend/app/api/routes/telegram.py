"""Telegram bot linking and webhook routes."""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import string
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import escape
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, Database
from app.config import get_settings
from app.core import media_audio
from app.core import user_memory as user_memory_module
from app.core.agent_dispatch import AgentDispatchError, enqueue_agent_run
from app.core.agent_runtime import (
    TERMINAL_STATUSES,
    execute_agent_step,
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
from app.core.companion_actions import ApprovalError
from app.core.companion_actuators import ActuationError
from app.core.companion_resolve import resolve_action_for_user
from app.core.document_extract import (
    SUPPORTED_DOCUMENT_EXTENSIONS,
    DocumentExtractionError,
    document_kind_for_extension,
    extract_document_text,
    resolve_document_extension,
)
from app.core.item_ingest import enqueue_item_processing, ingest_item
from app.core.item_processing import process_item, summarize_and_embed_item
from app.core.item_telegram import format_fetch_error_reply, format_item_reply
from app.core.item_titles import clean_title, title_from_filename
from app.core.mcp_tools import (
    list_recordings_for_mcp,
)
from app.core.ocr import OcrError, answer_about_images, ocr_image, ocr_images
from app.core.recording_import import (
    RecordingImportError,
    TranscribedMedia,
    import_media_as_recording,
    regenerate_recording_summary,
    transcribe_media_bytes,
)
from app.core.recording_share import create_recording_share
from app.core.retry_policy import is_retryable_exception
from app.core.source_fetch import classify_url, find_first_url
from app.core.summary_audio import (
    SUMMARY_AUDIO_SOURCE_ITEM,
    SUMMARY_AUDIO_SOURCE_RECORDING,
    SummaryAudioError,
    resolve_summary_audio_file_path,
    start_summary_audio_artifact,
)
from app.core.telegram_client import (
    TelegramBotClient,
    TelegramClientError,
    TelegramFileTooLargeError,
    telegram_chunks,
)
from app.core.telegram_digest import (
    DIGEST_MAX_DAYS,
    build_digest_prompt_block,
    collect_digest_sources,
    generate_telegram_digest,
    parse_digest_days,
)
from app.core.telegram_format import ru_plural, telegram_html
from app.core.telegram_intent import (
    VoiceRouteDecision,
    classify_photo_caption,
    classify_voice_transcript,
    route_voice_by_metadata,
)
from app.core.unified_search import UnifiedHit, unified_search
from app.core.wai_agent import planner_for_agent
from app.db.session import get_db_context
from app.models.agent import Agent, AgentRun
from app.models.companion import ChatMessage, Conversation
from app.models.companion_pending_action import CompanionPendingAction
from app.models.item import Item, ItemSummary
from app.models.recording import Recording
from app.models.reminder import UserReminder
from app.models.summary_audio import SummaryAudioStatus
from app.models.telegram import (
    TelegramAccount,
    TelegramAuthTicket,
    TelegramMediaGroupPart,
    TelegramPairing,
    TelegramUpdate,
)
from app.models.user import User

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/telegram", tags=["telegram"])

PAIRING_TTL = timedelta(minutes=15)
PAIRING_PREFIX = "link_"
AUTH_PREFIX = "auth_"
AUTH_CONSENT_PREFIX = "consent:auth:"
CONSENT_CALLBACK_DATA = "consent:accept"
TERMS_URL = "https://wai.computer/terms"
PRIVACY_URL = "https://wai.computer/privacy"
CHAT_ACTION_INTERVAL_SECONDS = 4.0
REMINDER_TEXT_LIMIT = 1200
TELEGRAM_PENDING_RECORDING_TTL = timedelta(hours=6)
# Pre-signup replay: how many buffered messages we re-route after the consent
# tap, and how stale a buffered message may be before we drop it.
TELEGRAM_PENDING_SIGNUP_REPLAY_LIMIT = 5
TELEGRAM_PENDING_SIGNUP_REPLAY_TTL = timedelta(hours=24)
TELEGRAM_PRESIGNUP_LEAD = (
    "Похоже, у тебя ещё нет аккаунта WaiComputer. Твоё сообщение не потеряется — "
    "нажми кнопку, и я сразу его обработаю."
)
TELEGRAM_CONSENT_WELCOME = (
    "Аккаунт создан ✅\n\n"
    "Пришли первое голосовое, файл или ссылку — сделаю расшифровку и краткое "
    "содержание.\n\n"
    "Что ещё я умею: /help"
)
TELEGRAM_CONSENT_WELCOME_REPLAY_SUFFIX = "\n\nУже обрабатываю твоё сообщение."
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
# Deliberately minimal: everyday actions go through natural language (the
# typed slash commands still work — they share handlers with the NL intents).
TELEGRAM_BOT_COMMANDS = [
    {"command": "help", "description": "Что умеет WaiComputer в Telegram"},
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
        "Что умеет WaiComputer:\n"
        "— голосовые, аудио и видео → расшифровка + саммари "
        "(кнопки: 🌐 страница, 🎧 озвучка)\n"
        "— фото и документы → сохраню и отвечу на вопросы\n"
        "— ссылки, включая YouTube → краткое содержание\n\n"
        "Просто пиши или говори:\n"
        "«запомни люблю короткие ответы» — сохраню в память\n"
        "«напомни через 10 минут позвонить» — напомню здесь\n"
        "«найди дорожная карта» — поищу по записям\n"
        "«дайджест за неделю», «покажи последние встречи»\n"
        "или любой вопрос — отвечу по твоим данным.\n\n"
        "Веб-версия: /web · Аккаунт и данные: /settings"
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

    digest_markers = ("дайджест", "digest")
    if any(marker in lower for marker in digest_markers) and len(lower) <= 60:
        digit = next((token for token in lower.split() if token.isdigit()), "")
        return "digest", digit

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
    reply_markup: dict[str, Any] | None = None,
) -> None:
    chunks = telegram_chunks(text)
    for idx, chunk in enumerate(chunks):
        await client.send_message(
            chat_id,
            chunk,
            reply_to_message_id=reply_to_message_id if idx == 0 else None,
            parse_mode=parse_mode,
            # Buttons belong under the final message of the reply, not mid-thread.
            reply_markup=reply_markup if idx == len(chunks) - 1 else None,
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


def _transcript_document_filename(recording: Any, *, media_kind: str | None) -> str:
    """Dated, title-derived name for the attached transcript, e.g.
    ``2026-07-08-obsuzhdenie-strategii-skolkovo.txt``."""
    base = _safe_transcript_filename(
        getattr(recording, "title", None),
        media_kind=media_kind,
    )
    created_at = getattr(recording, "created_at", None)
    if isinstance(created_at, datetime):
        return f"{created_at.strftime('%Y-%m-%d')}-{base}"
    return base


SUMMARY_RETRY_CALLBACK_PREFIX = "sumretry:"
TTS_CALLBACK_PREFIX = "tts:"
# A tapped-but-still-generating button. Kept under the tts: prefix so the
# router funnels it into the same handler.
TTS_PENDING_CALLBACK_DATA = f"{TTS_CALLBACK_PREFIX}pending"


def _tts_button(kind: str, source_id: Any) -> dict[str, Any]:
    return {
        "text": "🎧 Озвучить",
        "callback_data": f"{TTS_CALLBACK_PREFIX}{kind}:{source_id}",
    }


def _is_tts_button(button: Any) -> bool:
    return isinstance(button, dict) and str(button.get("callback_data", "")).startswith(
        TTS_CALLBACK_PREFIX
    )


def _keyboard_rows(markup: dict[str, Any] | None) -> list[list[dict[str, Any]]]:
    rows = markup.get("inline_keyboard") if isinstance(markup, dict) else None
    return rows if isinstance(rows, list) else []


def _markup_with_tts_pending(markup: dict[str, Any] | None) -> dict[str, Any]:
    """The tapped 🎧 button flips to a spinner-style pending state in place."""
    pending = {"text": "⏳ Готовлю озвучку…", "callback_data": TTS_PENDING_CALLBACK_DATA}
    rows = [
        [pending if _is_tts_button(button) else button for button in row]
        for row in _keyboard_rows(markup)
    ]
    if not rows:
        rows = [[pending]]
    return {"inline_keyboard": rows}


def _markup_without_tts(markup: dict[str, Any] | None) -> dict[str, Any]:
    """Once the voice message is delivered the button's job is done — the
    track itself replaces it. Other buttons (share page) stay."""
    rows = [
        [button for button in row if not _is_tts_button(button)]
        for row in _keyboard_rows(markup)
    ]
    return {"inline_keyboard": [row for row in rows if row]}


def _recording_reply_keyboard(
    share_url: str | None, recording_id: Any = None
) -> dict[str, Any] | None:
    rows: list[list[dict[str, Any]]] = []
    if share_url:
        rows.append([{"text": "🌐 Открыть страницу", "url": share_url}])
    if recording_id is not None:
        rows.append([_tts_button("rec", recording_id)])
    if not rows:
        return None
    return {"inline_keyboard": rows}


def _item_reply_keyboard(item_id: Any) -> dict[str, Any]:
    return {"inline_keyboard": [[_tts_button("item", item_id)]]}


def _summary_retry_keyboard(
    recording_id: Any,
    share_url: str | None,
) -> dict[str, Any] | None:
    rows: list[list[dict[str, Any]]] = []
    if recording_id is not None:
        rows.append(
            [
                {
                    "text": "Повторить саммари",
                    "callback_data": f"{SUMMARY_RETRY_CALLBACK_PREFIX}{recording_id}",
                }
            ]
        )
    if share_url:
        rows.append([{"text": "🌐 Открыть страницу", "url": share_url}])
    return {"inline_keyboard": rows} if rows else None


async def _mint_recording_share_url(recording: Any) -> str | None:
    """Mint a public page link for the recording reply button.

    Runs in its own session so a mint failure can neither fail the reply nor
    poison the caller's transaction — the summary still goes out, the button
    is simply absent, and the failure is captured for triage.
    """
    recording_id = getattr(recording, "id", None)
    if recording_id is None:
        return None
    try:
        async with get_db_context() as share_db:
            _, _, url = await create_recording_share(share_db, recording_id=recording_id)
            await share_db.commit()
    except Exception:
        logger.exception("telegram share link mint failed")
        return None
    return url


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
            "Word, PowerPoint, Excel, OpenDocument, HTML/MHTML, TXT/Markdown/RTF, "
            "CSV/JSON/YAML/XML, EPUB и email-файлы. "
            "Аудио и видео сохраняю как записи."
        ),
        reply_to_message_id=reply_to_message_id,
    )


def _format_recording_duration(duration_seconds: int | None) -> str | None:
    if not isinstance(duration_seconds, int) or duration_seconds < 60:
        return None
    minutes = round(duration_seconds / 60)
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours} ч {minutes} мин"
    if hours:
        return f"{hours} ч"
    return f"{minutes} мин"


def _format_recording_meta_line(
    recording: Any,
    speaker_names: dict[str, str] | None,
) -> str | None:
    """One italic line under the title: duration + who spoke (when known)."""
    parts: list[str] = []
    duration = _format_recording_duration(getattr(recording, "duration_seconds", None))
    if duration:
        parts.append(duration)
    names = [
        name
        for name in dict.fromkeys((speaker_names or {}).values())
        if name and name.strip()
    ]
    if len(names) >= 2:
        shown = ", ".join(names[:4])
        if len(names) > 4:
            shown += f" +{len(names) - 4}"
        parts.append(shown)
    if not parts:
        return None
    return f"<i>{escape(' · '.join(parts))}</i>"


def _format_recording_summary_message(
    recording: Any,
    summary: Any,
    *,
    speaker_names: dict[str, str] | None = None,
) -> str:
    title = str(getattr(recording, "title", "") or "").strip()
    summary_text = str(getattr(summary, "summary", "") or "").strip()

    header_lines: list[str] = []
    if title:
        header_lines.append(f"<b>{escape(title)}</b>")
    meta_line = _format_recording_meta_line(recording, speaker_names)
    if meta_line:
        header_lines.append(meta_line)

    sections: list[str] = []
    if header_lines:
        sections.append("\n".join(header_lines))
    if summary_text:
        sections.append(_telegram_summary_html(summary_text))
    return "\n\n".join(sections).strip()


def _format_import_summary_message(result: Any) -> str:
    return _format_recording_summary_message(
        result.recording,
        getattr(result, "summary", None),
        speaker_names=getattr(result, "speaker_names", None),
    )


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
        media_extensions = tuple(
            f".{ext}"
            for ext in sorted(
                media_audio.SUPPORTED_AUDIO_EXTENSIONS
                | media_audio.SUPPORTED_VIDEO_EXTENSIONS
            )
        )
        if (
            mime_type.startswith("audio/")
            or mime_type.startswith("video/")
            or file_name.endswith(media_extensions)
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


def _telegram_locale(from_user: dict[str, Any] | None) -> str:
    language_code = str((from_user or {}).get("language_code") or "").lower()
    if not language_code:
        return "ru"
    return "ru" if language_code.startswith("ru") else "en"


def _consent_inline_keyboard(
    *,
    locale: str = "ru",
    callback_data: str = CONSENT_CALLBACK_DATA,
) -> dict[str, Any]:
    label = "✅ Принимаю и создаю аккаунт" if locale == "ru" else "✅ Accept and create account"
    return {
        "inline_keyboard": [
            [{"text": label, "callback_data": callback_data}]
        ]
    }


async def _send_consent_prompt(
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    lead: str | None = None,
    callback_data: str = CONSENT_CALLBACK_DATA,
) -> None:
    """Offer Telegram-only signup: a welcome + an inline Terms/Privacy consent tap."""
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    locale = _telegram_locale(_telegram_user(message))
    if locale == "ru":
        intro = lead or "WaiComputer — твой второй мозг в Telegram."
        text = (
            f"{intro}\n\n"
            "Пришли голосовое, файл, ссылку или вопрос — расшифрую, сделаю саммари "
            "и запомню важное.\n\n"
            "Нажимая кнопку, ты принимаешь Условия использования "
            f"({TERMS_URL}) и Политику конфиденциальности ({PRIVACY_URL})."
        )
    else:
        intro = lead or "WaiComputer — your second brain in Telegram."
        text = (
            f"{intro}\n\n"
            "Send a voice note, file, link, or question. I’ll transcribe it, summarize it, "
            "and remember what matters.\n\n"
            "By tapping the button, you accept the Terms of Service "
            f"({TERMS_URL}) and Privacy Policy ({PRIVACY_URL})."
        )
    await client.send_message(
        chat_id,
        text,
        reply_to_message_id=message.get("message_id"),
        reply_markup=_consent_inline_keyboard(
            locale=locale,
            callback_data=callback_data,
        ),
    )


async def _telegram_auth_ticket(
    db: AsyncSession,
    *,
    raw_token: str,
) -> TelegramAuthTicket | None:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(TelegramAuthTicket)
        .where(
            and_(
                TelegramAuthTicket.start_token_hash == _token_hash(raw_token),
                TelegramAuthTicket.expires_at > now,
                TelegramAuthTicket.approved_at.is_(None),
            )
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def _begin_telegram_auth(
    db: AsyncSession,
    *,
    raw_token: str,
    from_user: dict[str, Any],
) -> str | None:
    """Approve a linked account or reserve the ticket pending legal consent."""
    telegram_user_id = from_user.get("id")
    if not isinstance(telegram_user_id, int):
        return "invalid"
    locale = _telegram_locale(from_user)
    ticket = await _telegram_auth_ticket(db, raw_token=raw_token)
    if ticket is None:
        return "expired"
    if ticket.telegram_user_id not in (None, telegram_user_id):
        return "invalid"
    ticket.telegram_user_id = telegram_user_id
    account = await _load_account(db, telegram_user_id)
    if account is None:
        await db.commit()
        return None
    ticket.user_id = account.user_id
    ticket.approved_at = datetime.now(timezone.utc)
    await db.commit()
    if locale == "ru":
        return "Вход подтверждён ✅ Вернись в WaiComputer — аккаунт уже открыт."
    return "Sign-in confirmed ✅ Return to WaiComputer — your account is ready."


async def _approve_telegram_auth_after_consent(
    db: AsyncSession,
    *,
    raw_token: str,
    telegram_user_id: int,
    user_id: Any,
) -> bool:
    ticket = await _telegram_auth_ticket(db, raw_token=raw_token)
    if ticket is None or ticket.telegram_user_id != telegram_user_id:
        return False
    ticket.user_id = user_id
    ticket.approved_at = datetime.now(timezone.utc)
    await db.commit()
    return True


async def _handle_consent_callback(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    callback_id: str,
    from_user: dict[str, Any] | None,
    chat_id: int | None,
    message_id: int | None,
    auth_token: str | None = None,
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
    locale = _telegram_locale(from_user)
    await client.answer_callback_query(
        callback_id,
        text="Готово!" if locale == "ru" else "Done!",
    )

    telegram_user_id = from_user.get("id")
    account = (
        await _load_account(db, telegram_user_id)
        if isinstance(telegram_user_id, int)
        else None
    )
    pending: list[TelegramUpdate] = []
    if account is not None and isinstance(telegram_user_id, int):
        pending = await _collect_pending_signup_replays(
            db, telegram_user_id=telegram_user_id
        )

    auth_approved = False
    if auth_token and isinstance(telegram_user_id, int):
        auth_approved = await _approve_telegram_auth_after_consent(
            db,
            raw_token=auth_token,
            telegram_user_id=telegram_user_id,
            user_id=user.id,
        )

    if locale == "ru":
        welcome = TELEGRAM_CONSENT_WELCOME
        if auth_token:
            welcome += (
                "\n\nВход подтверждён. Вернись в WaiComputer."
                if auth_approved
                else "\n\nАккаунт создан, но вход уже истёк. Начни вход заново в WaiComputer."
            )
    else:
        welcome = (
            "Account created ✅\n\n"
            "Send your first voice note, file, or link — I’ll transcribe and summarize it.\n\n"
            "More things to try: /help"
        )
        if auth_token:
            welcome += (
                "\n\nSign-in confirmed. Return to WaiComputer."
                if auth_approved
                else "\n\nYour account is ready, but sign-in expired. Start again in WaiComputer."
            )
    if pending:
        welcome += TELEGRAM_CONSENT_WELCOME_REPLAY_SUFFIX
    sent_welcome = False
    if isinstance(message_id, int):
        try:
            await client.edit_message_text(chat_id, message_id, welcome)
            sent_welcome = True
        except TelegramClientError:
            logger.warning("consent welcome edit failed; sending fresh message")
    if not sent_welcome:
        await client.send_message(chat_id, welcome)

    # Replay the buffered pre-signup messages last so the welcome lands first,
    # then each message's own processing status follows it in the chat.
    if account is not None:
        for row in pending:
            await _replay_pending_signup_update(
                db, client, account=account, row=row
            )


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

    if arg.startswith(AUTH_PREFIX):
        raw_token = arg.removeprefix(AUTH_PREFIX)
        auth_result = await _begin_telegram_auth(
            db,
            raw_token=raw_token,
            from_user=from_user,
        )
        if auth_result is None:
            await _send_consent_prompt(
                client,
                message=message,
                callback_data=f"{AUTH_CONSENT_PREFIX}{raw_token}",
            )
            return
        if auth_result == "expired":
            text = (
                "Ссылка для входа истекла. Начни вход заново в WaiComputer."
                if _telegram_locale(from_user) == "ru"
                else "This sign-in link expired. Start again in WaiComputer."
            )
        elif auth_result == "invalid":
            text = (
                "Не удалось подтвердить вход. Начни заново в WaiComputer."
                if _telegram_locale(from_user) == "ru"
                else "Could not confirm sign-in. Start again in WaiComputer."
            )
        else:
            text = auth_result
    elif arg.startswith(PAIRING_PREFIX):
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


async def _handle_web_command(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
) -> None:
    """DM a one-time web sign-in link (the /help footer promises web access).

    Telegram-born accounts are emailless and passwordless, so a plain dashboard
    URL would dead-end at the login wall — the magic-link mint is the only way
    those users can reach the web app."""
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
    base = settings.frontend_url.rstrip("/")
    await client.send_message(
        chat_id,
        (
            "Ссылка для входа в веб-версию WaiComputer (одноразовая, действует "
            f"15 минут):\n\n{base}/auth/verify?token={token}\n\n"
            "Открой её на компьютере — там же Настройки, экспорт и удаление аккаунта."
        ),
        reply_to_message_id=message.get("message_id"),
    )


async def _handle_settings_command(
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
) -> None:
    """Reply with the account/data settings link (the /help footer promises it)."""
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    base = settings.frontend_url.rstrip("/")
    await client.send_message(
        chat_id,
        (
            f"Аккаунт и данные: {base}/dashboard#settings\n"
            "Если ещё не входил в веб — сначала отправь /web, пришлю "
            "одноразовую ссылку для входа."
        ),
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


async def _handle_digest_command(
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
    requested_days = parse_digest_days(arg)
    if requested_days is None:
        await client.send_message(
            chat_id,
            "Формат: /digest — за сегодня, /digest 3 — за последние 3 дня "
            f"(максимум {DIGEST_MAX_DAYS}).",
            reply_to_message_id=message.get("message_id"),
        )
        return
    days = min(requested_days, DIGEST_MAX_DAYS)

    period_label = "за сегодня" if days == 1 else f"за последние {days} дн."
    status_response = await client.send_message(
        chat_id,
        f"Собираю материалы {period_label}.",
        reply_to_message_id=message.get("message_id"),
    )
    status_message_id = _sent_message_id(status_response)
    action_task = asyncio.create_task(_send_chat_action_until_cancelled(client, chat_id))
    try:
        sources, total = await collect_digest_sources(db, account.user_id, days=days)
        if not sources:
            await _delete_status_message(
                client, chat_id=chat_id, message_id=status_message_id
            )
            await client.send_message(
                chat_id,
                f"Материалов {period_label} пока нет: ни записей, ни сохранённого. "
                "Пришли голосовое, ссылку или фото — и будет что дайджестить.",
                reply_to_message_id=message.get("message_id"),
            )
            return
        try:
            digest_text = await generate_telegram_digest(
                build_digest_prompt_block(sources), days=days, total_sources=total
            )
        except Exception:  # noqa: BLE001 - digest failure must be honest, never silent.
            logger.exception("telegram digest generation failed")
            await _delete_status_message(
                client, chat_id=chat_id, message_id=status_message_id
            )
            await client.send_message(
                chat_id,
                "Дайджест собрать не получилось. Попробуй ещё раз позже.",
                reply_to_message_id=message.get("message_id"),
            )
            return
    except Exception:
        # Unexpected failure: never leave a stale «Собираю материалы…» behind.
        await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)
        raise
    finally:
        await _stop_chat_action_task(action_task)

    await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)
    notes = ""
    if requested_days > DIGEST_MAX_DAYS:
        notes = f"<i>Максимум {DIGEST_MAX_DAYS} дней — показываю их.</i>\n"
    if total > len(sources):
        notes += f"<i>Материалов {total}, в дайджест вошли последние {len(sources)}.</i>\n"
    count_label = f"{total} {ru_plural(total, 'материал', 'материала', 'материалов')}"
    header = f"<b>Дайджест {escape(period_label)}</b> · {count_label}"
    await _send_chunks(
        client,
        chat_id,
        f"{notes}{header}\n\n{telegram_html(digest_text)}",
        reply_to_message_id=message.get("message_id"),
        parse_mode="HTML",
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
    if intent == "web":
        await _handle_web_command(db, client, message=message, account=account)
        return True
    if intent == "settings":
        await _handle_settings_command(client, message=message)
        return True
    if await _ensure_active_user(db, client, message=message, account=account) is None:
        return True
    if intent == "remember":
        await _handle_remember_command(db, client, message=message, account=account, arg=arg)
        return True
    if intent == "remind":
        await _handle_remind_command(db, client, message=message, account=account, arg=arg)
        return True
    if intent == "meetings":
        await _handle_meetings_command(db, client, message=message, account=account)
        return True
    if intent == "digest":
        await _handle_digest_command(
            db, client, message=message, account=account, arg=arg
        )
        return True
    if intent == "search":
        await _handle_search_command(db, client, message=message, account=account, query=arg)
        return True
    return False


async def _ensure_telegram_conversation(
    db: AsyncSession,
    account: TelegramAccount,
) -> Conversation:
    await db.refresh(account, attribute_names=["user_id", "companion_conversation_id"])
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
            format_fetch_error_reply(
                fetch_error.get("message", "Couldn't fetch that link."),
                fetch_error.get("code"),
            ),
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
        reply_markup=_item_reply_keyboard(item.id),
    )


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


async def _handle_summary_retry_callback(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    account: TelegramAccount,
    callback_id: str,
    chat_id: int | None,
    data: str,
) -> None:
    """Regenerate a failed recording summary from the retry button."""
    try:
        recording_id = UUID(data.removeprefix(SUMMARY_RETRY_CALLBACK_PREFIX))
    except ValueError:
        await client.answer_callback_query(callback_id)
        return
    if chat_id is None:
        await client.answer_callback_query(callback_id)
        return

    result = await db.execute(
        select(Recording).where(
            Recording.id == recording_id,
            Recording.user_id == account.user_id,
            Recording.deleted_at.is_(None),
        )
    )
    recording = result.scalar_one_or_none()
    if recording is None:
        await client.answer_callback_query(callback_id, text="Запись не найдена.")
        return
    user = await db.get(User, account.user_id)
    if user is None:
        await client.answer_callback_query(callback_id, text="Аккаунт не найден.")
        return

    await client.answer_callback_query(callback_id, text="Пишу саммари…")
    status_response = await client.send_message(chat_id, "Пишу саммари…")
    status_message_id = _sent_message_id(status_response)
    action_task = asyncio.create_task(_send_chat_action_until_cancelled(client, chat_id))
    try:
        summary, speaker_names = await regenerate_recording_summary(
            db,
            recording=recording,
            user=user,
        )
    except Exception:
        logger.exception("telegram summary retry failed")
        with suppress(Exception):
            await db.rollback()
        await client.send_message(
            chat_id,
            "Саммари снова не получилось. Попробуй позже.",
            reply_markup=_summary_retry_keyboard(recording_id, None),
        )
        await _delete_status_message(
            client, chat_id=chat_id, message_id=status_message_id
        )
        return
    finally:
        await _stop_chat_action_task(action_task)

    share_url = await _mint_recording_share_url(recording)
    reply = _format_recording_summary_message(
        recording,
        summary,
        speaker_names=speaker_names,
    )
    if reply:
        await _send_chunks(
            client,
            chat_id,
            reply,
            parse_mode="HTML",
            reply_markup=_recording_reply_keyboard(share_url, recording.id),
        )
    await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)


async def _summary_audio_source_title(
    db: AsyncSession,
    *,
    recording_id: Any,
    item_id: Any,
) -> str | None:
    if recording_id is not None:
        recording = await db.get(Recording, recording_id)
        title = getattr(recording, "title", None)
        return title.strip() if isinstance(title, str) and title.strip() else None
    if item_id is not None:
        item = await db.get(Item, item_id)
        title = getattr(item, "title", None)
        return title.strip() if isinstance(title, str) and title.strip() else None
    return None


async def deliver_summary_audio_to_telegram(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    artifact: Any,
    chat_id: int,
    reply_to_message_id: int | None,
) -> None:
    """Send a SUCCEEDED summary-audio artifact into the chat as a native
    voice bubble (waveform + inline playback), not a file attachment."""
    path = resolve_summary_audio_file_path(artifact)
    data = path.read_bytes()
    title = await _summary_audio_source_title(
        db, recording_id=artifact.recording_id, item_id=artifact.item_id
    )
    base = _safe_transcript_filename(title, media_kind="summary").removesuffix(".txt")
    extension = path.suffix.lstrip(".") or "mp3"
    duration = getattr(artifact, "duration_seconds", None)
    await client.send_voice(
        chat_id,
        filename=f"{base}.{extension}",
        data=data,
        caption=f"🎧 {title}" if title else "🎧 Саммари",
        duration=duration if isinstance(duration, int) else None,
        reply_to_message_id=reply_to_message_id,
    )


async def _handle_tts_callback(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    account: TelegramAccount,
    callback_id: str,
    chat_id: int | None,
    reply_to_message_id: int | None,
    data: str,
    message_markup: dict[str, Any] | None = None,
) -> None:
    """🎧 Озвучить: start-or-reuse the durable summary-audio artifact and deliver
    it to this chat — the wai-rocks "audio podcast", on demand instead of on
    every capture. Reuses the same artifact pipeline (ownership, caps, hash
    dedupe) as the apps. The tapped button flips to ⏳ while the track renders
    and disappears once the voice message lands."""
    if data == TTS_PENDING_CALLBACK_DATA:
        await client.answer_callback_query(
            callback_id, text="Аудио уже готовится — момент"
        )
        return
    kind, _, raw_id = data.removeprefix(TTS_CALLBACK_PREFIX).partition(":")
    source_kind = {
        "rec": SUMMARY_AUDIO_SOURCE_RECORDING,
        "item": SUMMARY_AUDIO_SOURCE_ITEM,
    }.get(kind)
    try:
        source_id = UUID(raw_id)
    except ValueError:
        await client.answer_callback_query(callback_id)
        return
    if source_kind is None or chat_id is None:
        await client.answer_callback_query(callback_id)
        return

    try:
        artifact = await start_summary_audio_artifact(
            db,
            source_kind=source_kind,
            source_id=source_id,
            user_id=account.user_id,
        )
        await db.flush()
    except SummaryAudioError as exc:
        await client.answer_callback_query(callback_id, text="Не получилось")
        await client.send_message(
            chat_id,
            f"Озвучить не получится: {exc.message}",
            reply_to_message_id=reply_to_message_id,
        )
        return

    if artifact.status == SummaryAudioStatus.SUCCEEDED.value:
        await client.answer_callback_query(callback_id, text="Отправляю аудио")
        try:
            await deliver_summary_audio_to_telegram(
                db,
                client,
                artifact=artifact,
                chat_id=chat_id,
                reply_to_message_id=reply_to_message_id,
            )
        except SummaryAudioError as exc:
            await client.send_message(
                chat_id,
                f"Аудио есть, но отправить не вышло: {exc.message}",
                reply_to_message_id=reply_to_message_id,
            )
            return
        # The track replaced the button — retire it, keep the other buttons.
        if reply_to_message_id is not None:
            try:
                await client.edit_message_reply_markup(
                    chat_id, reply_to_message_id, _markup_without_tts(message_markup)
                )
            except TelegramClientError:
                pass  # cosmetic; the message may be too old to edit
        return

    if artifact.status == SummaryAudioStatus.QUEUED.value and not artifact.task_id:
        from app.tasks.telegram_summary_audio import (
            deliver_summary_audio_telegram_task,
        )

        # The worker must see the QUEUED artifact row, so commit before enqueue
        # (same ordering as the app summary-audio routes).
        await db.commit()
        try:
            async_result = deliver_summary_audio_telegram_task.delay(
                artifact_id=str(artifact.id),
                chat_id=chat_id,
                reply_to_message_id=reply_to_message_id,
                button_message_id=reply_to_message_id,
                restore_markup=message_markup,
                final_markup=_markup_without_tts(message_markup),
            )
            artifact.task_id = str(async_result.id)
            await db.flush()
        except Exception:  # noqa: BLE001 — broker down: fail loudly, never pretend success
            logger.exception("telegram summary audio enqueue failed")
            artifact.status = SummaryAudioStatus.FAILED.value
            artifact.error_code = "summary_audio_enqueue_failed"
            artifact.error_message = "Failed to start summary audio generation."
            await db.flush()
            await client.answer_callback_query(callback_id, text="Не получилось")
            await client.send_message(
                chat_id,
                "Не смог запустить озвучку. Попробуй ещё раз позже.",
                reply_to_message_id=reply_to_message_id,
            )
            return
        await client.answer_callback_query(
            callback_id, text="Готовлю аудио — пришлю сюда"
        )
        # Flip the tapped button to its pending state so the chat shows work
        # is underway even before the "recording voice…" header action.
        if reply_to_message_id is not None:
            try:
                await client.edit_message_reply_markup(
                    chat_id,
                    reply_to_message_id,
                    _markup_with_tts_pending(message_markup),
                )
            except TelegramClientError:
                pass  # cosmetic
        return

    # RUNNING, or QUEUED with a task already claimed by another tap/app request.
    await client.answer_callback_query(
        callback_id, text="Аудио уже готовится — момент"
    )


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
    if data == CONSENT_CALLBACK_DATA or data.startswith(AUTH_CONSENT_PREFIX):
        auth_token = (
            data.removeprefix(AUTH_CONSENT_PREFIX)
            if data.startswith(AUTH_CONSENT_PREFIX)
            else None
        )
        await _handle_consent_callback(
            db,
            client,
            callback_id=callback_id,
            from_user=from_user if isinstance(from_user, dict) else None,
            chat_id=chat_id,
            message_id=message_id if isinstance(message_id, int) else None,
            auth_token=auth_token,
        )
        return
    account = await _load_account(db, telegram_user_id)
    if account is None:
        await client.answer_callback_query(
            callback_id, text="Сначала привяжи Telegram."
        )
        return
    if data.startswith(SUMMARY_RETRY_CALLBACK_PREFIX):
        await _handle_summary_retry_callback(
            db,
            client,
            account=account,
            callback_id=callback_id,
            chat_id=chat_id,
            data=data,
        )
        return
    if data.startswith(TTS_CALLBACK_PREFIX):
        cb_markup = (
            cb_message.get("reply_markup") if isinstance(cb_message, dict) else None
        )
        await _handle_tts_callback(
            db,
            client,
            account=account,
            callback_id=callback_id,
            chat_id=chat_id,
            reply_to_message_id=message_id if isinstance(message_id, int) else None,
            data=data,
            message_markup=cb_markup if isinstance(cb_markup, dict) else None,
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
            telegram_html(answer),
            reply_to_message_id=message.get("message_id"),
            parse_mode="HTML",
        )
    # Surface each proposed action as a tap-to-approve card (inline buttons) —
    # the only approval surface in Telegram; there are no approval commands.
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
            summary = await summarize_and_embed_item(db, item)
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
        reply_markup=_item_reply_keyboard(item.id),
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

    question_caption = str(message.get("caption") or "").strip()
    if question_caption:
        caption_route = await classify_photo_caption(question_caption)
        # Privacy-safe: only the route + reason tag, never the caption itself.
        logger.info(
            "telegram photo caption routed route=%s reason=%s",
            caption_route.route,
            caption_route.reason,
        )
        if caption_route.route == "question":
            await _answer_photo_question(
                db,
                client,
                message=message,
                account=account,
                photo=photo,
                caption=question_caption,
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
            summary = await summarize_and_embed_item(db, item)
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
        reply_markup=_item_reply_keyboard(item.id),
    )


async def _answer_photo_question(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    photo: dict[str, Any],
    caption: str,
) -> None:
    """A photo whose caption is addressed to Wai: answer the caption about the
    image, then file the photo + answer as a material (lossless either way).

    The answer is the reply; filing happens quietly afterwards so the user isn't
    spammed with a second summary of the same photo."""
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    file_id = str(photo.get("file_id"))

    status_response = await client.send_message(
        chat_id,
        "Смотрю на фото и отвечаю.",
        reply_to_message_id=message.get("message_id"),
    )
    status_message_id = _sent_message_id(status_response)
    action_task = asyncio.create_task(_send_chat_action_until_cancelled(client, chat_id))
    try:
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
        data, _file_path = downloaded
        mime_type = str(photo.get("mime_type") or "image/jpeg")
        try:
            answer = await answer_about_images(
                [(data, mime_type)], question=caption
            )
        except OcrError:
            await _delete_status_message(
                client, chat_id=chat_id, message_id=status_message_id
            )
            await client.send_message(
                chat_id,
                "Не смог ответить по этому фото. Попробуй ещё раз позже.",
                reply_to_message_id=message.get("message_id"),
            )
            return
    except Exception:
        # Unexpected failure: never leave a stale «Смотрю на фото…» behind.
        await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)
        raise
    finally:
        await _stop_chat_action_task(action_task)

    await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)
    await _send_chunks(
        client,
        chat_id,
        telegram_html(answer),
        reply_to_message_id=message.get("message_id"),
        parse_mode="HTML",
    )

    # File the photo + answer as a material so the exchange lands in the brain.
    source_ref = str(photo.get("file_unique_id") or file_id)
    try:
        item, created = await ingest_item(
            db,
            account.user_id,
            source="telegram",
            source_ref=source_ref,
            kind="image",
            title=clean_title(caption) or "Фото",
            body=f"Вопрос: {caption}\n\nОтвет: {answer}",
            metadata={
                "telegram": {
                    "file_unique_id": photo.get("file_unique_id"),
                    "mime_type": photo.get("mime_type"),
                    "kind": photo.get("kind"),
                    "size": len(data),
                },
                "vision_qa": True,
            },
            embed=True,
        )
        await db.flush()
        if created:
            # The summary worker must see the committed item row.
            await db.commit()
            await enqueue_item_processing(db, item)
        await _set_telegram_active_context(
            db, account, ref_type="item", ref_id=item.id, title=item.title
        )
    except Exception:  # noqa: BLE001 - the answer was delivered; filing failure must still be visible.
        logger.exception("telegram photo question ingest failed")
        await client.send_message(
            chat_id,
            "Ответил, но не смог сохранить фото в материалы.",
            reply_to_message_id=message.get("message_id"),
        )


ALBUM_DEBOUNCE_SECONDS = 3


async def _buffer_album_photo(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
) -> None:
    """Buffer one photo of a Telegram album and debounce the album task.

    Telegram sends an album as N separate messages within ~a second. Each part
    is stored (workers may interleave, so the buffer is the DB) and the FIRST
    stored part schedules the processing task ``ALBUM_DEBOUNCE_SECONDS`` later.
    A straggler arriving after the album was already processed falls back to
    the single-photo flow so it is never dropped."""
    chat_id = _telegram_chat_id(message)
    media_group_id = str(message.get("media_group_id") or "")
    message_id = message.get("message_id")
    if chat_id is None or not media_group_id or not isinstance(message_id, int):
        return

    already_processed = (
        await db.execute(
            select(TelegramMediaGroupPart.id)
            .where(
                TelegramMediaGroupPart.media_group_id == media_group_id,
                TelegramMediaGroupPart.processed_at.is_not(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if already_processed is not None:
        photo = _extract_photo(message)
        if photo is not None:
            await _handle_photo_message(
                db, client, message=message, account=account, photo=photo
            )
        return

    inserted = await db.execute(
        pg_insert(TelegramMediaGroupPart)
        .values(
            media_group_id=media_group_id,
            telegram_user_id=account.telegram_user_id,
            chat_id=chat_id,
            message_id=message_id,
            message=message,
        )
        .on_conflict_do_nothing(constraint="uq_tg_media_group_part")
    )
    await db.flush()
    if not inserted.rowcount:
        return

    part_count = (
        await db.execute(
            select(TelegramMediaGroupPart.id).where(
                TelegramMediaGroupPart.media_group_id == media_group_id
            )
        )
    ).all()
    if len(part_count) == 1:
        from app.tasks.telegram_album_import import process_telegram_media_group_task

        process_telegram_media_group_task.apply_async(
            kwargs={
                "media_group_id": media_group_id,
                "telegram_user_id": account.telegram_user_id,
            },
            countdown=ALBUM_DEBOUNCE_SECONDS,
        )
        with suppress(TelegramClientError):
            await client.send_chat_action(chat_id)


async def _process_photo_album(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    account: TelegramAccount,
    parts: list[TelegramMediaGroupPart],
) -> None:
    """Process a buffered Telegram photo album as ONE capture.

    Wai-rocks-style: the album gets a single combined vision pass and a single
    reply — a caption addressed to Wai is answered about all photos together,
    otherwise the album is filed as one material. Parts are marked processed on
    every outcome (the task never retries; failures are surfaced to the user)."""
    photo_parts = [part for part in parts if _extract_photo(part.message) is not None]
    processed_at = datetime.now(timezone.utc)
    for part in parts:
        part.processed_at = processed_at
    if not photo_parts:
        await db.flush()
        return

    first_message = photo_parts[0].message
    chat_id = photo_parts[0].chat_id
    reply_to = photo_parts[0].message_id
    await db.flush()

    user = await _ensure_active_user(db, client, message=first_message, account=account)
    if user is None:
        return

    caption = ""
    for part in photo_parts:
        candidate = str(part.message.get("caption") or "").strip()
        if candidate:
            caption = candidate
            break

    status_response = await client.send_message(
        chat_id,
        f"Принял альбом ({len(photo_parts)} фото). Обрабатываю.",
        reply_to_message_id=reply_to,
    )
    status_message_id = _sent_message_id(status_response)
    action_task = asyncio.create_task(_send_chat_action_until_cancelled(client, chat_id))
    try:
        images: list[tuple[bytes, str]] = []
        file_unique_ids: list[str] = []
        for part in photo_parts:
            photo = _extract_photo(part.message)
            if photo is None:
                continue
            downloaded = await _download_telegram_media(
                db,
                client,
                account=account,
                message=part.message,
                file_id=str(photo.get("file_id")),
                status_message_id=None,
            )
            if downloaded is None:
                # The size/download error was already replied for this part;
                # keep going so the rest of the album still lands.
                continue
            data, _file_path = downloaded
            images.append((data, str(photo.get("mime_type") or "image/jpeg")))
            file_unique_ids.append(
                str(photo.get("file_unique_id") or photo.get("file_id"))
            )

        if not images:
            await _delete_status_message(
                client, chat_id=chat_id, message_id=status_message_id
            )
            return

        route = "label"
        if caption:
            caption_route = await classify_photo_caption(caption)
            # Privacy-safe: only the route + reason tag, never the caption itself.
            logger.info(
                "telegram album caption routed route=%s reason=%s count=%s",
                caption_route.route,
                caption_route.reason,
                len(images),
            )
            route = caption_route.route

        media_group_id = photo_parts[0].media_group_id
        telegram_meta: dict[str, Any] = {
            "media_group_id": media_group_id,
            "file_unique_ids": file_unique_ids,
            "count": len(images),
        }

        if route == "question":
            try:
                answer = await answer_about_images(images, question=caption)
            except OcrError:
                await _delete_status_message(
                    client, chat_id=chat_id, message_id=status_message_id
                )
                await client.send_message(
                    chat_id,
                    "Не смог ответить по этому альбому. Попробуй ещё раз позже.",
                    reply_to_message_id=reply_to,
                )
                return
            await _delete_status_message(
                client, chat_id=chat_id, message_id=status_message_id
            )
            await _send_chunks(
                client,
                chat_id,
                telegram_html(answer),
                reply_to_message_id=reply_to,
                parse_mode="HTML",
            )
            try:
                item, created = await ingest_item(
                    db,
                    account.user_id,
                    source="telegram",
                    source_ref=media_group_id,
                    dedup_key=f"telegram:album:{media_group_id}",
                    kind="image",
                    title=clean_title(caption) or f"Альбом ({len(images)} фото)",
                    body=f"Вопрос: {caption}\n\nОтвет: {answer}",
                    metadata={"telegram": telegram_meta, "vision_qa": True},
                    embed=True,
                )
                await db.flush()
                if created:
                    # The summary worker must see the committed item row.
                    await db.commit()
                    await enqueue_item_processing(db, item)
                await _set_telegram_active_context(
                    db, account, ref_type="item", ref_id=item.id, title=item.title
                )
            except Exception:  # noqa: BLE001 - answer delivered; filing failure must be visible.
                logger.exception("telegram album question ingest failed")
                await client.send_message(
                    chat_id,
                    "Ответил, но не смог сохранить альбом в материалы.",
                    reply_to_message_id=reply_to,
                )
            return

        try:
            body = await ocr_images(images)
        except OcrError:
            await _delete_status_message(
                client, chat_id=chat_id, message_id=status_message_id
            )
            await client.send_message(
                chat_id,
                "Не смог распознать альбом. Попробуй ещё раз позже.",
                reply_to_message_id=reply_to,
            )
            return
        if not body.strip():
            await _delete_status_message(
                client, chat_id=chat_id, message_id=status_message_id
            )
            await client.send_message(
                chat_id,
                "В альбоме не нашёл текста или распознаваемого содержания.",
                reply_to_message_id=reply_to,
            )
            return

        try:
            item, created = await ingest_item(
                db,
                account.user_id,
                source="telegram",
                source_ref=media_group_id,
                dedup_key=f"telegram:album:{media_group_id}",
                kind="image",
                title=clean_title(caption) or f"Альбом ({len(images)} фото)",
                body=(f"{caption}\n\n{body}".strip() if caption else body),
                metadata={"telegram": telegram_meta},
                embed=True,
            )
            await db.flush()
        except Exception:  # noqa: BLE001 - failed import should be explicit to the sender.
            logger.exception("telegram album ingest failed")
            await _delete_status_message(
                client, chat_id=chat_id, message_id=status_message_id
            )
            await client.send_message(
                chat_id,
                "Не смог сохранить альбом в материалы. Попробуй позже.",
                reply_to_message_id=reply_to,
            )
            return

        summary = (
            await db.execute(select(ItemSummary).where(ItemSummary.item_id == item.id))
        ).scalar_one_or_none()
        if created or summary is None:
            try:
                summary = await summarize_and_embed_item(db, item)
                await db.flush()
            except Exception:  # noqa: BLE001 - keep the saved item and surface the failure.
                logger.exception("telegram album summary failed")
                await _delete_status_message(
                    client, chat_id=chat_id, message_id=status_message_id
                )
                await client.send_message(
                    chat_id,
                    "Сохранил альбом, но не смог сделать краткое содержание. Попробуй позже.",
                    reply_to_message_id=reply_to,
                )
                return

        await _delete_status_message(
            client, chat_id=chat_id, message_id=status_message_id
        )
        reply = format_item_reply(item, summary)
        await _set_telegram_active_context(
            db, account, ref_type="item", ref_id=item.id, title=item.title
        )
        await _send_chunks(
            client,
            chat_id,
            reply,
            reply_to_message_id=reply_to,
            parse_mode="HTML",
            reply_markup=_item_reply_keyboard(item.id),
        )
    except Exception:
        # Unexpected failure: never leave a stale «Принял альбом…» behind.
        await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)
        raise
    finally:
        await _stop_chat_action_task(action_task)


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

    try:
        if decision is None:
            if not transcribed.has_speech:
                decision = VoiceRouteDecision("file", "no_speech")
            else:
                decision = await classify_voice_transcript(
                    transcribed.transcript_text,
                    recent_assistant_message=await _recent_assistant_text(db, account),
                )

        # Privacy-safe: only the route + reason tag, never the transcript.
        logger.info(
            "telegram voice routed route=%s reason=%s", decision.route, decision.reason
        )

        if decision.route == "message" and transcribed.has_speech:
            await _handle_voice_as_message(
                db,
                client,
                message=message,
                account=account,
                transcript=transcribed.transcript_text,
            )
            return

        # File it, reusing the download + transcript we already produced.
        await _handle_media_message(
            db,
            client,
            message=message,
            account=account,
            media=media,
            source_filename=file_path,
            precomputed=transcribed,
        )
    finally:
        # The normalised intent-media file belongs to this routing pass; the
        # import (if any) has finished with it by now.
        await transcribed.discard()


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
            cut = echo.rfind(" ", 0, 600)
            echo = echo[: cut if cut > 300 else 600].rstrip() + "…"
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
            summary = await summarize_and_embed_item(db, item)
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
        reply_markup=_item_reply_keyboard(item.id),
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
    source_filename: str | None = None,
    precomputed: TranscribedMedia | None = None,
) -> None:
    """Save media as a library recording.

    ``precomputed`` lets intent routing hand over a voice note it already
    downloaded and transcribed so it is filed inline without a second download
    or STT pass (``source_filename`` preserves the Telegram file path as the
    extension hint). Everything else — including every video and large audio
    file — is handed to the recording Celery worker: the download and
    ffmpeg/STT work must never run inside the API process (a 236 MB video
    OOM-killed the webhook worker on 2026-07-09, silently losing the import).
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

    if precomputed is not None:
        # Voice note already downloaded + transcribed for intent routing —
        # filing it reuses that work and stays cheap enough for the API process.
        await _import_telegram_media_and_reply(
            db,
            client,
            message=message,
            account=account,
            user=user,
            media=media,
            status_message_id=status_message_id,
            source_filename=source_filename,
            precomputed=precomputed,
        )
        return

    try:
        from app.tasks.celery_app import celery_app

        celery_app.send_task(
            "app.tasks.telegram_media_import.import_telegram_media",
            kwargs={
                "account_id": str(account.id),
                "user_id": str(user.id),
                "message": message,
                "media": media,
                "status_message_id": status_message_id,
            },
            queue="recording",
            routing_key="recording",
        )
    except Exception:  # noqa: BLE001 — broker down: tell the sender, don't go silent.
        logger.exception("telegram media import enqueue failed")
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


async def _import_telegram_media_and_reply(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
    user: User,
    media: dict[str, Any],
    status_message_id: int | None,
    source_path: Path | None = None,
    source_filename: str | None = None,
    precomputed: TranscribedMedia | None = None,
) -> None:
    """Import already-materialised Telegram media and deliver the full reply flow
    (progress edits, transcript .txt, summary + share button, error messages).

    Runs inside the API process only for tiny precomputed voice notes; the
    recording Celery worker calls it with ``source_path`` for everything else."""
    chat_id = _telegram_chat_id(message)
    if chat_id is None:
        return
    caption = str(message.get("caption") or "").strip()
    title = caption[:500] if caption else None
    action_task = asyncio.create_task(_send_chat_action_until_cancelled(client, chat_id))

    async def _report_import_stage(stage: str) -> None:
        if stage != "summarizing" or status_message_id is None:
            return
        try:
            await client.edit_message_text(
                chat_id,
                status_message_id,
                "Расшифровал. Пишу саммари…",
            )
        except TelegramClientError as exc:
            logger.warning("telegram status edit failed error=%s", type(exc).__name__)

    try:
        result = await import_media_as_recording(
            db=db,
            user=user,
            source_path=source_path,
            filename=media.get("file_name") or source_filename,
            content_type=media.get("mime_type"),
            title=title,
            source_label="telegram",
            language=user.default_language,
            duration_seconds=_telegram_media_duration_seconds(media),
            precomputed=precomputed,
            on_stage=_report_import_stage,
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
        try:
            await client.send_document(
                chat_id,
                filename=_transcript_document_filename(
                    result.recording,
                    media_kind=str(media.get("kind") or "media"),
                ),
                data=(result.transcript_document or result.transcript).encode("utf-8"),
                reply_to_message_id=message.get("message_id"),
            )
        except TelegramClientError as exc:
            # The recording is imported; a failed .txt attachment must not
            # swallow the summary + share link that follow.
            logger.warning(
                "telegram transcript document send failed error=%s",
                type(exc).__name__,
            )
    share_url = (
        await _mint_recording_share_url(result.recording) if result.transcript else None
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
    if not result.transcript:
        await client.send_message(
            chat_id,
            "В записи не слышно речи — расшифровывать нечего.",
            reply_to_message_id=message.get("message_id"),
        )
    elif getattr(result, "summary", None) is not None and summary_message:
        await _send_chunks(
            client,
            chat_id,
            summary_message,
            reply_to_message_id=message.get("message_id"),
            parse_mode="HTML",
            reply_markup=_recording_reply_keyboard(share_url, recording_id),
        )
    else:
        # The transcript is saved but the summary generation failed. Say so and
        # offer a retry — never pretend the job finished.
        await client.send_message(
            chat_id,
            "Расшифровка готова — файл выше. Саммари сгенерировать не получилось.",
            reply_to_message_id=message.get("message_id"),
            reply_markup=_summary_retry_keyboard(recording_id, share_url),
        )
    await _delete_status_message(client, chat_id=chat_id, message_id=status_message_id)


async def _refresh_account_from_message(
    db: AsyncSession,
    account: TelegramAccount,
    *,
    message: dict[str, Any],
) -> None:
    """Sync the account's chat id + profile fields from the latest message.

    Mirrors the field updates the normal dispatch path applies before routing,
    so the pre-signup replay path stays byte-for-byte consistent with it."""
    from_user = _telegram_user(message) or {}
    chat_id = _telegram_chat_id(message)
    if chat_id is not None:
        account.telegram_chat_id = chat_id
    account.username = from_user.get("username")
    account.first_name = from_user.get("first_name")
    account.last_name = from_user.get("last_name")
    account.last_seen_at = datetime.now(timezone.utc)
    await db.flush()


async def _route_account_message(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    message: dict[str, Any],
    account: TelegramAccount,
) -> None:
    """Dispatch one message from a provisioned account to its handler.

    The single source of truth for how a linked user's message is routed —
    shared by the live webhook path and the post-signup replay so a replayed
    first message behaves identically to one sent after signup."""
    chat_id = _telegram_chat_id(message)
    command = _message_command(message)
    media = _extract_media(message)
    if media is not None:
        await _route_media_message(
            db, client, message=message, account=account, media=media
        )
    elif (photo := _extract_photo(message)) is not None:
        media_group_id = message.get("media_group_id")
        if isinstance(media_group_id, str) and media_group_id:
            await _buffer_album_photo(db, client, message=message, account=account)
        else:
            await _handle_photo_message(
                db, client, message=message, account=account, photo=photo
            )
    elif (document := _extract_document(message)) is not None:
        await _handle_document_message(
            db, client, message=message, account=account, document=document
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
            db, client, message=message, account=account, intent=intent, arg=arg
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


async def _stash_pending_signup_update(
    db: AsyncSession,
    update_id: int,
    *,
    update: dict[str, Any],
    telegram_user_id: int,
) -> None:
    """Persist a brand-new user's pre-signup message for post-consent replay.

    The idempotency row already exists (the webhook inserted it before
    dispatching); we attach the raw update and flip it to ``pending_signup`` so
    the consent callback can find and re-route it."""
    stored = await db.get(TelegramUpdate, update_id)
    if stored is None:
        return
    stored.payload = update
    stored.telegram_user_id = telegram_user_id
    stored.status = "pending_signup"
    await db.flush()


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def _collect_pending_signup_replays(
    db: AsyncSession,
    *,
    telegram_user_id: int,
) -> list[TelegramUpdate]:
    """Return the buffered pre-signup updates worth replaying, newest-capped.

    Marks the losers ``skipped``: everything beyond the most recent
    ``TELEGRAM_PENDING_SIGNUP_REPLAY_LIMIT`` messages, anything older than
    ``TELEGRAM_PENDING_SIGNUP_REPLAY_TTL``, and rows with no usable payload."""
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(TelegramUpdate)
            .where(
                TelegramUpdate.telegram_user_id == telegram_user_id,
                TelegramUpdate.status == "pending_signup",
            )
            .order_by(TelegramUpdate.update_id)
        )
    ).scalars().all()
    if not rows:
        return []

    over_cap = (
        rows[:-TELEGRAM_PENDING_SIGNUP_REPLAY_LIMIT]
        if len(rows) > TELEGRAM_PENDING_SIGNUP_REPLAY_LIMIT
        else []
    )
    recent = rows[-TELEGRAM_PENDING_SIGNUP_REPLAY_LIMIT:]
    for row in over_cap:
        row.status = "skipped"
        row.processed_at = now

    eligible: list[TelegramUpdate] = []
    for row in recent:
        received = _as_aware(row.received_at)
        payload = row.payload if isinstance(row.payload, dict) else None
        message = payload.get("message") if isinstance(payload, dict) else None
        if received is not None and now - received > TELEGRAM_PENDING_SIGNUP_REPLAY_TTL:
            row.status = "skipped"
            row.processed_at = now
        elif not isinstance(message, dict):
            row.status = "skipped"
            row.processed_at = now
        else:
            eligible.append(row)
    await db.flush()
    return eligible


async def _replay_pending_signup_update(
    db: AsyncSession,
    client: TelegramBotClient,
    *,
    account: TelegramAccount,
    row: TelegramUpdate,
) -> None:
    """Re-route one buffered pre-signup message, marking the row's outcome.

    Routing helpers commit before enqueuing Celery work (the known
    commit-before-enqueue contract), so we commit the status mark too — one bad
    message must never roll back an already-enqueued import."""
    message = row.payload["message"]
    update_id = row.update_id
    try:
        await _refresh_account_from_message(db, account, message=message)
        await _route_account_message(db, client, message=message, account=account)
    except Exception as exc:  # noqa: BLE001 — one failure must not block the rest
        logger.warning(
            "telegram pending-signup replay failed update_id=%s code=%s",
            update_id,
            type(exc).__name__,
        )
        with suppress(Exception):
            await db.rollback()
        fresh = await db.get(TelegramUpdate, update_id)
        if fresh is not None:
            fresh.status = "failed"
            fresh.error_code = type(exc).__name__[:100]
            fresh.error_message = str(exc)[:2000] or "pending-signup replay failed"
            fresh.processed_at = datetime.now(timezone.utc)
            with suppress(Exception):
                await db.commit()
        return
    row.status = "completed"
    row.processed_at = datetime.now(timezone.utc)
    with suppress(Exception):
        await db.commit()


async def _handle_update(update: dict[str, Any]) -> None:
    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        return
    client = TelegramBotClient()
    async with get_db_context() as db:
        message: dict[str, Any] | None = None
        account: TelegramAccount | None = None
        media_message = False
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
            if command and command[0] == "/help":
                if account is None:
                    await _send_consent_prompt(client, message=message)
                else:
                    await _handle_help_command(client, message=message, linked=True)
                await _mark_update(db, update_id, "completed")
                return

            if account is None:
                # First message from a brand-new user (e.g. a voice note before
                # signup): offer account creation AND stash the raw update so the
                # message is replayed — not dropped — right after the consent tap.
                await _stash_pending_signup_update(
                    db, update_id, update=update, telegram_user_id=telegram_user_id
                )
                await _send_consent_prompt(
                    client,
                    message=message,
                    lead=TELEGRAM_PRESIGNUP_LEAD,
                )
                return
            await _refresh_account_from_message(db, account, message=message)
            media_message = _extract_media(message) is not None
            await _route_account_message(db, client, message=message, account=account)
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
            if media_message or status_message_id is not None:
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
