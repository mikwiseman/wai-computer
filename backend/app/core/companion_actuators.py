"""Execute approved mutating actions — the side-effect runners the approval gate
commits after a human says yes.

Targets are grounded SERVER-SIDE: a misheard or model-supplied recipient can
never redirect a send. v1 Telegram channel = the user's OWN bot-DM thread
(``TelegramAccount.telegram_chat_id``); "send to <contact>" is deferred (it needs
the external WaiTelegram ``search_chats`` path). No fallbacks: a missing account
or empty body raises rather than guessing.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.telegram_client import TelegramBotClient
from app.models.telegram import TelegramAccount


class ActuationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


async def _resolve_own_chat_id(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        select(TelegramAccount).where(TelegramAccount.user_id == user_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise ActuationError(
            "no_telegram_account", "No linked Telegram account for this user"
        )
    chat_id = account.telegram_chat_id or account.telegram_user_id
    if not chat_id:
        raise ActuationError(
            "no_telegram_chat", "Linked Telegram account has no chat id"
        )
    return int(chat_id)


async def execute_send_message_telegram(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    args: dict[str, Any],
    telegram_client: TelegramBotClient | None = None,
) -> dict[str, Any]:
    """Send ``args['text']`` to the user's own bot-DM thread. The recipient is
    resolved server-side from the user's linked account — any ``chat_id`` in
    ``args`` is IGNORED (recipient grounding)."""
    text = (args or {}).get("text")
    if not text or not str(text).strip():
        raise ActuationError("empty_text", "Refusing to send an empty message")
    chat_id = await _resolve_own_chat_id(db, user_id)
    client = telegram_client or TelegramBotClient()
    result = await client.send_message(chat_id, str(text))
    return {
        "channel": "telegram",
        "chat_id": chat_id,
        "message_id": result.get("message_id") if isinstance(result, dict) else None,
    }


_EXECUTORS = {
    "send_message_telegram": execute_send_message_telegram,
}


async def execute_action(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    tool_name: str,
    args: dict[str, Any],
    telegram_client: TelegramBotClient | None = None,
) -> dict[str, Any]:
    """Dispatch an approved action to its server-side runner."""
    runner = _EXECUTORS.get(tool_name)
    if runner is None:
        raise ActuationError("no_executor", f"No executor for tool: {tool_name}")
    return await runner(
        db, user_id=user_id, args=args, telegram_client=telegram_client
    )
