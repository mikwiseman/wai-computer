"""Small Telegram Bot API client used by the webhook worker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

settings = get_settings()


class TelegramClientError(Exception):
    """Raised when Telegram rejects or fails a Bot API request."""


@dataclass(frozen=True)
class TelegramFile:
    file_id: str
    file_path: str
    file_size: int | None


class TelegramBotClient:
    """Token-safe wrapper around the Bot API.

    Never include Telegram URLs in exceptions: both method and file URLs contain
    the bot token.
    """

    def __init__(self, token: str | None = None) -> None:
        self._token = token if token is not None else settings.telegram_bot_token
        if not self._token:
            raise TelegramClientError("Telegram bot token is not configured")
        self._api_base = f"https://api.telegram.org/bot{self._token}"
        self._file_base = f"https://api.telegram.org/file/bot{self._token}"

    @staticmethod
    def _parse_response(method: str, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            raise TelegramClientError(
                f"Telegram {method} returned HTTP {response.status_code}"
            )
        data = response.json()
        if not data.get("ok"):
            description = str(data.get("description") or "request failed")
            raise TelegramClientError(f"Telegram {method} failed: {description}")
        result = data.get("result")
        return result if isinstance(result, dict) else {"value": result}

    async def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(f"{self._api_base}/{method}", json=payload)
        except httpx.HTTPError as exc:
            raise TelegramClientError(f"Telegram {method} request failed") from exc

        return self._parse_response(method, response)

    async def _post_multipart(
        self,
        method: str,
        *,
        data: dict[str, str],
        files: dict[str, tuple[str, bytes, str]],
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self._api_base}/{method}",
                    data=data,
                    files=files,
                )
        except httpx.HTTPError as exc:
            raise TelegramClientError(f"Telegram {method} request failed") from exc

        return self._parse_response(method, response)

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any]:
        return await self._post(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
                **(
                    {"reply_to_message_id": reply_to_message_id}
                    if reply_to_message_id is not None
                    else {}
                ),
            },
        )

    async def send_document(
        self,
        chat_id: int,
        *,
        filename: str,
        data: bytes,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any]:
        payload = {"chat_id": str(chat_id)}
        if caption:
            payload["caption"] = caption
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = str(reply_to_message_id)
        return await self._post_multipart(
            "sendDocument",
            data=payload,
            files={"document": (filename, data, "text/plain; charset=utf-8")},
        )

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        await self._post("sendChatAction", {"chat_id": chat_id, "action": action})

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        await self._post("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

    async def get_file(self, file_id: str) -> TelegramFile:
        result = await self._post("getFile", {"file_id": file_id})
        file_path = result.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            raise TelegramClientError("Telegram getFile returned no file_path")
        file_size = result.get("file_size")
        return TelegramFile(
            file_id=file_id,
            file_path=file_path,
            file_size=file_size if isinstance(file_size, int) else None,
        )

    async def delete_my_commands(self) -> None:
        await self._post("deleteMyCommands", {})

    async def download_file(self, file: TelegramFile) -> bytes:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.get(f"{self._file_base}/{file.file_path}")
        except httpx.HTTPError as exc:
            raise TelegramClientError("Telegram file download failed") from exc

        if response.status_code >= 400:
            raise TelegramClientError(
                f"Telegram file download returned HTTP {response.status_code}"
            )
        return response.content


def telegram_chunks(text: str, *, limit: int = 3900) -> list[str]:
    """Split a bot response into Telegram-safe message chunks."""
    clean = text.strip()
    if not clean:
        return []
    chunks: list[str] = []
    remaining = clean
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks
