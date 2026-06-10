"""Edge-case coverage for the token-safe Telegram Bot API client.

Covers the stdlib fallback response parser, the sync multipart fallback,
local Bot API file handling, and download size caps. Everything
network-shaped is faked (``urllib.request.urlopen`` and ``httpx.AsyncClient``
are patched) — no test talks to a real server.
"""

from __future__ import annotations

import io
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.telegram_client import (
    TelegramBotClient,
    TelegramClientError,
    TelegramFile,
    TelegramFileTooLargeError,
)


def test_parse_response_body_maps_error_statuses_and_bodies():
    parse = TelegramBotClient._parse_response_body

    # HTTP error with a non-JSON body keeps only the status code.
    with pytest.raises(TelegramClientError, match="returned HTTP 502"):
        parse("sendMessage", 502, b"<html>bad gateway</html>")

    # HTTP error with a JSON body surfaces Telegram's description.
    with pytest.raises(TelegramClientError, match="failed: chat not found"):
        parse("sendMessage", 400, b'{"ok": false, "description": "chat not found"}')

    # 200 with an undecodable body.
    with pytest.raises(TelegramClientError, match="returned invalid JSON"):
        parse("sendMessage", 200, b"\xff not json")

    # 200 with ok=false and no description.
    with pytest.raises(TelegramClientError, match="failed: request failed"):
        parse("sendMessage", 200, b'{"ok": false}')

    # Non-dict results are wrapped, matching the httpx parser.
    assert parse("getMe", 200, b'{"ok": true, "result": 42}') == {"value": 42}


def test_post_json_sync_parses_http_error_payload():
    client = TelegramBotClient("token-a")
    error = urllib.error.HTTPError(
        "https://api.invalid/method",
        429,
        "Too Many Requests",
        None,
        io.BytesIO(b'{"ok": false, "description": "Too Many Requests: retry after 3"}'),
    )

    with (
        patch("app.core.telegram_client.urllib.request.urlopen", side_effect=error),
        pytest.raises(TelegramClientError, match="retry after 3"),
    ):
        client._post_json_sync("sendMessage", {"chat_id": 1})


class _SyncUrlopenResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def __enter__(self) -> "_SyncUrlopenResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_post_multipart_sync_success_returns_result():
    client = TelegramBotClient("token-b")
    urlopen = MagicMock(
        return_value=_SyncUrlopenResponse(200, b'{"ok": true, "result": {"message_id": 7}}')
    )

    with patch("app.core.telegram_client.urllib.request.urlopen", urlopen):
        result = client._post_multipart_sync(
            "sendDocument",
            data={"chat_id": "1"},
            files={"document": ("a.txt", b"hello", "text/plain")},
        )

    assert result == {"message_id": 7}
    request = urlopen.call_args.args[0]
    assert request.full_url.endswith("/sendDocument")
    assert b"hello" in request.data


def test_post_multipart_sync_parses_http_error_payload():
    client = TelegramBotClient("token-c")
    error = urllib.error.HTTPError(
        "https://api.invalid/method",
        413,
        "Payload Too Large",
        None,
        io.BytesIO(b'{"ok": false, "description": "file is too big"}'),
    )

    with (
        patch("app.core.telegram_client.urllib.request.urlopen", side_effect=error),
        pytest.raises(TelegramClientError, match="file is too big"),
    ):
        client._post_multipart_sync(
            "sendDocument",
            data={"chat_id": "1"},
            files={"document": ("a.txt", b"x", "text/plain")},
        )


@pytest.mark.asyncio
async def test_edit_message_text_sends_parse_mode_and_markup(monkeypatch):
    client = TelegramBotClient("token-d")
    captured: dict[str, object] = {}

    async def fake_post(method, payload):
        captured["method"] = method
        captured["payload"] = payload
        return {"message_id": 5}

    monkeypatch.setattr(client, "_post", fake_post)

    result = await client.edit_message_text(
        10, 5, "updated", reply_markup={"inline_keyboard": []}, parse_mode="HTML"
    )

    assert result == {"message_id": 5}
    assert captured["method"] == "editMessageText"
    assert captured["payload"] == {
        "chat_id": 10,
        "message_id": 5,
        "text": "updated",
        "disable_web_page_preview": True,
        "reply_markup": {"inline_keyboard": []},
        "parse_mode": "HTML",
    }


def test_resolve_local_file_path_requires_configured_root():
    client = TelegramBotClient("token-e", local_file_root="")

    with pytest.raises(TelegramClientError, match="local file root is not configured"):
        client._resolve_local_file_path(TelegramFile("file-id", "voice/file.ogg", None))


@pytest.mark.asyncio
async def test_download_file_accepts_absolute_local_path_inside_root(tmp_path: Path):
    target = tmp_path / "music" / "file.mp3"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"absolute bytes")
    client = TelegramBotClient("123456:ABC", local_file_root=str(tmp_path))

    data = await client.download_file(TelegramFile("file-id", str(target), None))

    assert data == b"absolute bytes"


@pytest.mark.asyncio
async def test_download_file_rejects_absolute_local_path_outside_root(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"secret")
    client = TelegramBotClient("123456:ABC", local_file_root=str(root))

    with pytest.raises(TelegramClientError, match="invalid local file path"):
        await client.download_file(TelegramFile("file-id", str(outside), None))


@pytest.mark.asyncio
async def test_download_file_local_missing_file_is_unavailable(tmp_path: Path):
    client = TelegramBotClient("123456:ABC", local_file_root=str(tmp_path))

    with pytest.raises(TelegramClientError, match="local file is not available"):
        await client.download_file(TelegramFile("file-id", "voice/missing.ogg", None))


@pytest.mark.asyncio
async def test_download_file_local_directory_is_unavailable(tmp_path: Path):
    token = "123456:ABC"
    (tmp_path / token / "voice" / "dir.ogg").mkdir(parents=True)
    client = TelegramBotClient(token, local_file_root=str(tmp_path))

    with pytest.raises(TelegramClientError, match="local file is not available"):
        await client.download_file(TelegramFile("file-id", "voice/dir.ogg", None))


class _GrowingFile:
    """Stat says the file fits the cap; the bytes read afterwards do not."""

    def stat(self) -> SimpleNamespace:
        return SimpleNamespace(st_size=2)

    def is_file(self) -> bool:
        return True

    def read_bytes(self) -> bytes:
        return b"grew past the cap"


def test_read_local_file_rejects_bytes_exceeding_limit_after_stat():
    with pytest.raises(TelegramFileTooLargeError):
        TelegramBotClient._read_local_file(_GrowingFile(), 2)


class _FakeHttpxStream:
    def __init__(self, response: object) -> None:
        self._response = response

    async def __aenter__(self) -> object:
        return self._response

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakeStreamResponse:
    def __init__(self, status_code: int, chunks: list[bytes]) -> None:
        self.status_code = status_code
        self._chunks = chunks

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


@pytest.mark.asyncio
async def test_download_http_file_enforces_max_bytes():
    response = _FakeStreamResponse(200, [b"0123", b"4567"])
    client_mock = MagicMock()
    client_mock.stream = MagicMock(return_value=_FakeHttpxStream(response))
    async_ctx = MagicMock()
    async_ctx.__aenter__ = AsyncMock(return_value=client_mock)
    async_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("app.core.telegram_client.httpx.AsyncClient", return_value=async_ctx):
        client = TelegramBotClient("token-f", local_file_root="")
        with pytest.raises(TelegramFileTooLargeError):
            await client.download_file(
                TelegramFile("file-id", "voice/big.ogg", None), max_bytes=6
            )
