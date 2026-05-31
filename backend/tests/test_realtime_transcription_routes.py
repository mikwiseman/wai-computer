"""Tests for realtime transcription session routes."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.realtime_transcription import (
    RealtimeTranscriptionProxyClaims,
    RealtimeTranscriptionSession,
    decode_realtime_proxy_token,
)
from app.main import app


@pytest.fixture
def mock_authenticated_user():
    """Patch get_current_user to return a fake user."""
    from app.api.deps import get_current_user

    fake_user = MagicMock()
    fake_user.id = "user-transcription"

    async def _override():
        return fake_user

    with patch(
        "app.api.routes.realtime_transcription.load_user_keyterms",
        new=AsyncMock(return_value=[]),
    ):
        app.dependency_overrides[get_current_user] = _override
        yield fake_user
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_realtime_transcription_session_returns_provider_payload(mock_authenticated_user):
    session = RealtimeTranscriptionSession(
        provider="deepgram",
        token="dg_token",
        expires_in_seconds=60,
        sample_rate=16_000,
        audio_format="linear16",
        language="multi",
        channels=1,
        model="nova-3",
        keep_alive_interval_seconds=4,
        commit_strategy=None,
        no_verbatim=False,
        websocket_url="wss://api.deepgram.com/v1/listen?model=nova-3",
        auth_scheme="bearer",
    )

    mint = AsyncMock(return_value=session)
    with patch(
        "app.api.routes.realtime_transcription.create_realtime_transcription_session",
        new=mint,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/transcription/session",
                headers={
                    "Authorization": "Bearer fake-token",
                    "X-Forwarded-Proto": "https",
                    "X-Forwarded-Host": "wai.computer",
                },
                json={"language": "multi", "channels": 1},
            )

    assert response.status_code == 200
    assert mint.await_args.kwargs["websocket_url"] == (
        "wss://wai.computer/api/transcription/stream"
    )
    assert mint.await_args.kwargs["keyterms"] == []
    payload = response.json()
    assert payload["provider"] == "deepgram"
    assert payload["token"] == "dg_token"
    assert payload["model"] == "nova-3"
    assert payload["sample_rate"] == 16_000
    assert payload["audio_format"] == "linear16"
    assert payload["keep_alive_interval_seconds"] == 4
    assert payload["commit_strategy"] is None
    assert payload["no_verbatim"] is False
    assert payload["auth_scheme"] == "bearer"


@pytest.mark.asyncio
async def test_realtime_transcription_session_mints_local_proxy_token(
    mock_authenticated_user,
):
    with patch(
        "app.core.realtime_transcription.require_deepgram_api_key",
        return_value="provider_key",
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/transcription/session",
                headers={
                    "Authorization": "Bearer fake-token",
                    "X-Forwarded-Proto": "https",
                    "X-Forwarded-Host": "wai.computer",
                },
                json={"language": "ru", "channels": 1, "purpose": "dictation"},
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["websocket_url"] == "wss://wai.computer/api/transcription/stream"
    assert payload["auth_scheme"] == "bearer"
    assert payload["model"] == "nova-3"
    claims = decode_realtime_proxy_token(payload["token"])
    assert claims.language == "ru"
    assert claims.purpose == "dictation"
    assert claims.keyterms == []


@pytest.mark.asyncio
async def test_realtime_transcription_session_reports_slow_session_mint(
    mock_authenticated_user,
):
    session = RealtimeTranscriptionSession(
        provider="deepgram",
        token="dg_token",
        expires_in_seconds=60,
        sample_rate=16_000,
        audio_format="linear16",
        language="multi",
        channels=1,
        model="nova-3",
        keep_alive_interval_seconds=4,
        commit_strategy=None,
        no_verbatim=False,
        websocket_url="wss://api.deepgram.com/v1/listen?model=nova-3",
        auth_scheme="bearer",
    )
    captured: dict[str, object] = {}

    def fake_anomaly(
        code: str,
        message: str,
        *,
        category: str,
        extras: dict[str, object] | None = None,
    ) -> None:
        captured["code"] = code
        captured["message"] = message
        captured["category"] = category
        captured["extras"] = extras

    with patch(
        "app.api.routes.realtime_transcription.create_realtime_transcription_session",
        new=AsyncMock(return_value=session),
    ), patch(
        "app.api.routes.realtime_transcription.perf_counter",
        side_effect=[0.0, 3.0],
    ), patch(
        "app.api.routes.realtime_transcription.capture_sentry_anomaly",
        new=fake_anomaly,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/transcription/session",
                headers={"Authorization": "Bearer fake-token"},
                json={"language": "multi", "channels": 1},
            )

    assert response.status_code == 200
    assert captured["code"] == "realtime.session_mint.slow"
    assert captured["category"] == "transcription.session"
    assert captured["extras"] is not None
    assert captured["extras"]["provider"] == "deepgram"
    assert captured["extras"]["model"] == "nova-3"
    assert captured["extras"]["latency_ms"] == 3_000


@pytest.mark.asyncio
async def test_realtime_transcription_session_returns_503_on_missing_config(
    mock_authenticated_user,
):
    with patch(
        "app.api.routes.realtime_transcription.create_realtime_transcription_session",
        new=AsyncMock(side_effect=ValueError("DEEPGRAM_API_KEY not configured")),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/transcription/session",
                headers={"Authorization": "Bearer fake-token"},
                json={"language": "en", "channels": 1},
            )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Live transcription is temporarily unavailable. Please try again in a moment."
    )


@pytest.mark.asyncio
async def test_realtime_transcription_session_captures_sentry_on_unexpected_error(
    mock_authenticated_user,
):
    captured: dict[str, object] = {}

    def fake_capture(error: Exception, *, extras: dict[str, object] | None = None) -> None:
        captured["error"] = error
        captured["extras"] = extras

    with patch(
        "app.api.routes.realtime_transcription.create_realtime_transcription_session",
        new=AsyncMock(side_effect=RuntimeError("provider exploded")),
    ), patch(
        "app.api.routes.realtime_transcription.capture_sentry_exception",
        new=fake_capture,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/transcription/session",
                headers={"Authorization": "Bearer fake-token"},
                json={"language": "multi", "channels": 1},
            )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Live transcription is temporarily unavailable. Please try again in a moment."
    )
    assert isinstance(captured["error"], RuntimeError)
    assert captured["extras"] is not None
    assert captured["extras"]["alert_code"] == "realtime.session_mint.failed"
    assert captured["extras"]["language"] == "multi"
    assert captured["extras"]["channels"] == 1
    assert captured["extras"]["purpose"] == "recording"
    assert isinstance(captured["extras"]["latency_ms"], int)


@pytest.mark.asyncio
async def test_realtime_transcription_session_requires_auth():
    app.dependency_overrides.clear()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/transcription/session",
            json={"language": "en", "channels": 1},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_realtime_transcription_session_rejects_stereo_request(mock_authenticated_user):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/transcription/session",
            headers={"Authorization": "Bearer fake-token"},
            json={"language": "en", "channels": 2},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_realtime_transcription_session_rejects_unsupported_language(
    mock_authenticated_user,
):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/transcription/session",
            headers={"Authorization": "Bearer fake-token"},
            json={"language": "zz-TEST", "channels": 1},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Unsupported live transcription language."


class FakeWebSocket:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}
        self.accepted = False
        self.closed_codes: list[int] = []
        self.json_payloads: list[dict[str, object]] = []
        self.sent_bytes: list[bytes] = []
        self.sent_text: list[str] = []
        self._receive_queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, *, code: int) -> None:
        self.closed_codes.append(code)

    async def send_json(self, payload: dict[str, object]) -> None:
        self.json_payloads.append(payload)

    async def send_bytes(self, payload: bytes) -> None:
        self.sent_bytes.append(payload)

    async def send_text(self, payload: str) -> None:
        self.sent_text.append(payload)

    async def receive(self) -> dict[str, object]:
        return await self._receive_queue.get()

    def queue_receive(self, message: dict[str, object]) -> None:
        self._receive_queue.put_nowait(message)


class FakeProvider:
    def __init__(self, messages: list[bytes | str] | None = None) -> None:
        self.messages = messages or []
        self.sent: list[bytes | str] = []
        self.closed = False

    async def send(self, payload: bytes | str) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        self._iterator = iter(self.messages)
        return self

    async def __anext__(self) -> bytes | str:
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeProviderConnection:
    def __init__(self, provider: FakeProvider) -> None:
        self.provider = provider

    async def __aenter__(self) -> FakeProvider:
        return self.provider

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class FailingProviderConnection:
    async def __aenter__(self):
        raise RuntimeError("provider offline")

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class SendJsonFailingWebSocket(FakeWebSocket):
    async def send_json(self, payload: dict[str, object]) -> None:
        raise RuntimeError("websocket already closed")


def _claims() -> RealtimeTranscriptionProxyClaims:
    return RealtimeTranscriptionProxyClaims(
        subject="user-transcription",
        language="ru",
        channels=1,
        model="nova-3",
        purpose="dictation",
    )


@pytest.mark.asyncio
async def test_realtime_stream_closes_without_bearer_token():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket()

    await route.stream_realtime_transcription(websocket)

    # Now ACCEPTS first, sends a structured error frame, then closes — the
    # previous close-before-accept pattern made the client see a generic
    # WS-upgrade failure with no diagnostic body, which DictationManager
    # silently swallowed during its .connecting window.
    assert websocket.accepted is True
    assert websocket.json_payloads == [route.PROXY_ERROR_MISSING_BEARER]
    assert websocket.closed_codes == [1008]


@pytest.mark.asyncio
async def test_realtime_stream_closes_on_invalid_proxy_token():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket({"authorization": "Bearer invalid"})

    with patch(
        "app.api.routes.realtime_transcription.decode_realtime_proxy_token",
        side_effect=ValueError("bad token"),
    ):
        await route.stream_realtime_transcription(websocket)

    assert websocket.accepted is True
    assert websocket.json_payloads == [route.PROXY_ERROR_INVALID_TOKEN]
    assert websocket.closed_codes == [1008]


@pytest.mark.asyncio
async def test_realtime_stream_reports_provider_config_error_without_secret():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})

    with patch(
        "app.api.routes.realtime_transcription.decode_realtime_proxy_token",
        return_value=_claims(),
    ), patch(
        "app.api.routes.realtime_transcription.require_deepgram_api_key",
        side_effect=ValueError("DEEPGRAM_API_KEY not configured"),
    ):
        await route.stream_realtime_transcription(websocket)

    assert websocket.accepted is True
    assert websocket.json_payloads == [route.PROXY_ERROR_MISSING_API_KEY]
    assert websocket.closed_codes == [1011]


@pytest.mark.asyncio
async def test_realtime_stream_connects_to_deepgram_with_server_api_key():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})
    provider = FakeProvider(messages=[b'{"type":"Metadata"}', '{"type":"Results"}'])
    connect_calls: list[dict[str, object]] = []

    def fake_connect(url: str, **kwargs):
        connect_calls.append({"url": url, **kwargs})
        return FakeProviderConnection(provider)

    with patch(
        "app.api.routes.realtime_transcription.decode_realtime_proxy_token",
        return_value=_claims(),
    ), patch(
        "app.api.routes.realtime_transcription.require_deepgram_api_key",
        return_value="server-provider-key",
    ), patch(
        "app.api.routes.realtime_transcription.websockets.connect",
        new=fake_connect,
    ), patch(
        "app.api.routes.realtime_transcription._websockets_header_kwarg",
        return_value="additional_headers",
    ):
        await route.stream_realtime_transcription(websocket)

    assert websocket.accepted is True
    assert websocket.sent_bytes == [b'{"type":"Metadata"}']
    assert websocket.sent_text == ['{"type":"Results"}']
    assert websocket.closed_codes == [1000]
    assert connect_calls
    assert "model=nova-3" in str(connect_calls[0]["url"])
    assert connect_calls[0]["additional_headers"] == {
        "Authorization": "Token server-provider-key"
    }


@pytest.mark.asyncio
async def test_realtime_stream_reports_provider_connect_failure():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})
    captured: dict[str, object] = {}

    def fake_capture(error: Exception, *, extras: dict[str, object] | None = None) -> None:
        captured["error"] = error
        captured["extras"] = extras

    with patch(
        "app.api.routes.realtime_transcription.decode_realtime_proxy_token",
        return_value=_claims(),
    ), patch(
        "app.api.routes.realtime_transcription.require_deepgram_api_key",
        return_value="server-provider-key",
    ), patch(
        "app.api.routes.realtime_transcription.websockets.connect",
        return_value=FailingProviderConnection(),
    ), patch(
        "app.api.routes.realtime_transcription.capture_sentry_exception",
        new=fake_capture,
    ):
        await route.stream_realtime_transcription(websocket)

    assert isinstance(captured["error"], RuntimeError)
    assert captured["extras"] is not None
    assert captured["extras"]["alert_code"] == "realtime.stream.failed"
    assert websocket.json_payloads == [route.PROXY_ERROR_PAYLOAD]
    assert websocket.closed_codes == [1011]


@pytest.mark.asyncio
async def test_realtime_stream_ignores_error_payload_when_socket_already_closed():
    from app.api.routes import realtime_transcription as route

    websocket = SendJsonFailingWebSocket({"authorization": "Bearer proxy-token"})

    with patch(
        "app.api.routes.realtime_transcription.decode_realtime_proxy_token",
        return_value=_claims(),
    ), patch(
        "app.api.routes.realtime_transcription.require_deepgram_api_key",
        return_value="server-provider-key",
    ), patch(
        "app.api.routes.realtime_transcription.websockets.connect",
        return_value=FailingProviderConnection(),
    ):
        await route.stream_realtime_transcription(websocket)

    assert websocket.closed_codes == [1011]


@pytest.mark.asyncio
async def test_realtime_stream_reports_unexpected_bridge_task_failure():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})
    provider = FakeProvider()
    captured: dict[str, object] = {}

    async def failing_client_to_provider(*args, **kwargs):
        raise RuntimeError("upstream failed")

    async def waiting_provider_to_client(*args, **kwargs):
        await asyncio.sleep(60)

    def fake_capture(error: Exception, *, extras: dict[str, object] | None = None) -> None:
        captured["error"] = error
        captured["extras"] = extras

    with patch(
        "app.api.routes.realtime_transcription.decode_realtime_proxy_token",
        return_value=_claims(),
    ), patch(
        "app.api.routes.realtime_transcription.require_deepgram_api_key",
        return_value="server-provider-key",
    ), patch(
        "app.api.routes.realtime_transcription.websockets.connect",
        return_value=FakeProviderConnection(provider),
    ), patch(
        "app.api.routes.realtime_transcription._client_to_provider",
        new=failing_client_to_provider,
    ), patch(
        "app.api.routes.realtime_transcription._provider_to_client",
        new=waiting_provider_to_client,
    ), patch(
        "app.api.routes.realtime_transcription.capture_sentry_exception",
        new=fake_capture,
    ):
        await route.stream_realtime_transcription(websocket)

    assert isinstance(captured["error"], RuntimeError)
    assert websocket.json_payloads == [route.PROXY_ERROR_PAYLOAD]
    assert websocket.closed_codes == [1011]


def test_websockets_header_kwarg_supports_newer_additional_headers(monkeypatch):
    from app.api.routes import realtime_transcription as route

    def fake_connect(url: str, *, additional_headers=None):
        del url, additional_headers

    monkeypatch.setattr(route.websockets, "connect", fake_connect)

    assert route._websockets_header_kwarg() == "additional_headers"


@pytest.mark.asyncio
async def test_client_to_provider_forwards_audio_and_control_messages():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket()
    provider = FakeProvider()
    websocket.queue_receive({"type": "websocket.receive", "bytes": b"pcm"})
    websocket.queue_receive({"type": "websocket.receive", "text": '{"type":"KeepAlive"}'})
    websocket.queue_receive({"type": "lifespan.noop"})
    websocket.queue_receive({"type": "websocket.disconnect"})

    await route._client_to_provider(websocket, provider)

    assert provider.sent == [b"pcm", '{"type":"KeepAlive"}']
    assert provider.closed is True


@pytest.mark.asyncio
async def test_provider_to_client_forwards_binary_and_text_messages():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket()
    provider = FakeProvider(messages=[b"binary", "text"])

    await route._provider_to_client(websocket, provider)

    assert websocket.sent_bytes == [b"binary"]
    assert websocket.sent_text == ["text"]


@pytest.mark.asyncio
async def test_close_websocket_ignores_already_closed_runtime_error():
    from app.api.routes import realtime_transcription as route

    websocket = MagicMock()
    websocket.close = AsyncMock(side_effect=RuntimeError("already closed"))

    await route._close_websocket(websocket, code=1000)

    websocket.close.assert_awaited_once_with(code=1000)


# --- cost/abuse guard wiring (2026 incident hardening) -----------------------
async def _post_session(json_body: dict | None = None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            "/api/transcription/session",
            headers={"Authorization": "Bearer fake-token"},
            json=json_body or {"language": "multi", "channels": 1, "purpose": "dictation"},
        )


@pytest.mark.asyncio
async def test_realtime_session_503_when_transcription_halted(mock_authenticated_user):
    from app.core import transcription_guard as guard

    await guard.get_redis().set("dg:killswitch", "1")
    response = await _post_session()
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_realtime_session_503_when_circuit_breaker_open(mock_authenticated_user):
    from app.core import transcription_guard as guard

    await guard.record_provider_result(success=False, status_code=402)
    response = await _post_session()
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_realtime_session_429_on_mint_burst(mock_authenticated_user, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "realtime_mint_burst_max", 0)
    response = await _post_session()
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_realtime_session_503_when_daily_minutes_exhausted(mock_authenticated_user):
    from app.core import transcription_guard as guard

    # fake_user.id is "user-transcription"; record past the default per-user cap (1200)
    await guard.record_minutes("user-transcription", 5000)
    response = await _post_session()
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_realtime_stream_closes_when_transcription_halted():
    from app.api.routes import realtime_transcription as route
    from app.core import transcription_guard as guard

    await guard.get_redis().set("dg:killswitch", "1")
    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})
    with patch(
        "app.api.routes.realtime_transcription.decode_realtime_proxy_token",
        return_value=_claims(),
    ), patch(
        "app.api.routes.realtime_transcription.require_deepgram_api_key",
        return_value="server-provider-key",
    ):
        await route.stream_realtime_transcription(websocket)
    assert websocket.accepted is True
    assert route.PROXY_ERROR_HALTED in websocket.json_payloads
    assert websocket.closed_codes == [1011]


@pytest.mark.asyncio
async def test_realtime_stream_rejected_when_concurrency_full(monkeypatch):
    from app.api.routes import realtime_transcription as route
    from app.config import get_settings
    from app.core import transcription_guard as guard

    monkeypatch.setattr(get_settings(), "realtime_max_concurrent_streams_per_user", 1)
    # occupy the single per-user slot
    await guard.acquire_stream_slot("user-transcription", lease_ttl_seconds=60)
    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})
    with patch(
        "app.api.routes.realtime_transcription.decode_realtime_proxy_token",
        return_value=_claims(),
    ), patch(
        "app.api.routes.realtime_transcription.require_deepgram_api_key",
        return_value="server-provider-key",
    ):
        await route.stream_realtime_transcription(websocket)
    assert route.PROXY_ERROR_TOO_MANY_STREAMS in websocket.json_payloads
    assert websocket.closed_codes == [1008]


class _HangingProvider:
    """A provider whose pump never completes, to exercise the wall-clock cap."""

    async def send(self, payload: bytes | str) -> None:
        return None

    async def close(self) -> None:
        return None

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.Event().wait()  # never resolves


@pytest.mark.asyncio
async def test_realtime_stream_force_closes_at_max_duration(monkeypatch):
    from app.api.routes import realtime_transcription as route
    from app.config import get_settings

    # tiny cap so asyncio.wait times out immediately with both pumps still pending
    monkeypatch.setattr(get_settings(), "realtime_stream_max_seconds_dictation", 0.05)
    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})  # empty queue -> recv hangs
    with patch(
        "app.api.routes.realtime_transcription.decode_realtime_proxy_token",
        return_value=_claims(),
    ), patch(
        "app.api.routes.realtime_transcription.require_deepgram_api_key",
        return_value="server-provider-key",
    ), patch(
        "app.api.routes.realtime_transcription.websockets.connect",
        return_value=FakeProviderConnection(_HangingProvider()),
    ):
        await route.stream_realtime_transcription(websocket)
    assert route.PROXY_ERROR_SESSION_EXPIRED in websocket.json_payloads
    assert websocket.closed_codes == [1000]
