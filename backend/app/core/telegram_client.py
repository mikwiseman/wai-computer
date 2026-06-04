"""Small Telegram Bot API client used by the webhook worker."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings

settings = get_settings()


class TelegramClientError(Exception):
    """Raised when Telegram rejects or fails a Bot API request."""


class TelegramFileTooLargeError(TelegramClientError):
    """Raised when a Telegram file exceeds the configured import cap."""


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

    def __init__(
        self,
        token: str | None = None,
        *,
        bot_api_base_url: str | None = None,
        file_base_url: str | None = None,
        local_file_root: str | None = None,
    ) -> None:
        self._token = token if token is not None else settings.telegram_bot_token
        if not self._token:
            raise TelegramClientError("Telegram bot token is not configured")
        api_base = (bot_api_base_url or settings.telegram_bot_api_base_url).rstrip("/")
        file_base = (file_base_url or settings.telegram_file_base_url).rstrip("/")
        self._api_base = f"{api_base}/bot{self._token}"
        self._file_base = f"{file_base}/bot{self._token}"
        root = (
            local_file_root
            if local_file_root is not None
            else settings.telegram_local_file_root
        )
        root = (root or "").strip()
        self._local_file_root = Path(root).resolve() if root else None

    @staticmethod
    def _parse_response(method: str, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            raise TelegramClientError(f"Telegram {method} returned HTTP {response.status_code}")
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
        parse_mode: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return await self._post(
            "sendMessage",
            payload,
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

    async def set_my_commands(
        self,
        commands: list[dict[str, str]],
        *,
        language_code: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"commands": commands}
        if language_code is not None:
            payload["language_code"] = language_code
        await self._post("setMyCommands", payload)

    def _resolve_local_file_path(self, file: TelegramFile) -> Path:
        if self._local_file_root is None:
            raise TelegramClientError("Telegram local file root is not configured")

        root = self._local_file_root
        raw_path = Path(file.file_path)
        if raw_path.is_absolute():
            candidate = raw_path
            allowed_root = root
        else:
            candidate = root / self._token / raw_path
            allowed_root = root / self._token

        resolved_root = allowed_root.resolve()
        resolved_candidate = candidate.resolve(strict=False)
        try:
            resolved_candidate.relative_to(resolved_root)
        except ValueError as exc:
            raise TelegramClientError("Telegram returned invalid local file path") from exc
        return resolved_candidate

    @staticmethod
    def _read_local_file(path: Path, max_bytes: int | None) -> bytes:
        try:
            stat = path.stat()
        except OSError as exc:
            raise TelegramClientError("Telegram local file is not available") from exc
        if not path.is_file():
            raise TelegramClientError("Telegram local file is not available")
        if max_bytes is not None and stat.st_size > max_bytes:
            raise TelegramFileTooLargeError("Telegram file exceeds configured limit")
        data = path.read_bytes()
        if max_bytes is not None and len(data) > max_bytes:
            raise TelegramFileTooLargeError("Telegram file exceeds configured limit")
        return data

    async def _download_http_file(self, file: TelegramFile, max_bytes: int | None) -> bytes:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("GET", f"{self._file_base}/{file.file_path}") as response:
                    if response.status_code >= 400:
                        raise TelegramClientError(
                            f"Telegram file download returned HTTP {response.status_code}"
                        )
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if max_bytes is not None and total > max_bytes:
                            raise TelegramFileTooLargeError(
                                "Telegram file exceeds configured limit"
                            )
                        chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise TelegramClientError("Telegram file download failed") from exc
        return b"".join(chunks)

    async def download_file(self, file: TelegramFile, *, max_bytes: int | None = None) -> bytes:
        if self._local_file_root is not None:
            path = self._resolve_local_file_path(file)
            return await asyncio.to_thread(self._read_local_file, path, max_bytes)
        return await self._download_http_file(file, max_bytes)


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
