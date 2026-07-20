"""Tests for realtime transcription session routes."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from websockets.exceptions import ConnectionClosedError

from app.core.personalization import RealtimePersonalizationHints
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
        "app.api.routes.realtime_transcription.load_user_realtime_hints",
        new=AsyncMock(return_value=RealtimePersonalizationHints(keyterms=[], replacements=[])),
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
    assert mint.await_args.kwargs["replacements"] == []
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
        "app.core.realtime_transcription.require_openai_api_key",
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
    assert payload["model"] == "gpt-realtime-whisper"
    assert payload["provider"] == "openai"
    assert payload["sample_rate"] == 24_000
    assert payload["keep_alive_interval_seconds"] is None
    assert payload["commit_strategy"] == "manual"
    claims = decode_realtime_proxy_token(payload["token"])
    assert claims.provider == "openai"
    assert claims.language == "ru"
    assert claims.purpose == "dictation"
    assert "WaiComputer" in claims.keyterms
    assert ("во ecomputer", "WaiComputer") in claims.replacements


@pytest.mark.asyncio
async def test_realtime_transcription_session_loads_replacements_for_live_dictation(
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
    mint = AsyncMock(return_value=session)
    replacements = [("WaiCompyuter", "WaiComputer"), ("Bolnichny", "больничный")]
    hints = RealtimePersonalizationHints(keyterms=["WaiComputer"], replacements=replacements)

    with patch(
        "app.api.routes.realtime_transcription.create_realtime_transcription_session",
        new=mint,
    ), patch(
        "app.api.routes.realtime_transcription.load_user_realtime_hints",
        new=AsyncMock(return_value=hints),
    ) as load_hints:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/transcription/session",
                headers={"Authorization": "Bearer fake-token"},
                json={"language": "multi", "channels": 1, "purpose": "dictation"},
            )

    assert response.status_code == 200
    load_hints.assert_awaited_once()
    assert load_hints.await_args.kwargs["user_id"] == mock_authenticated_user.id
    assert mint.await_args.kwargs["keyterms"] == ["WaiComputer"]
    assert mint.await_args.kwargs["replacements"] == replacements


@pytest.mark.asyncio
async def test_realtime_transcription_session_merges_client_dictation_hints(
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
    mint = AsyncMock(return_value=session)
    server_replacements = [("server wrong", "ServerRight")]
    hints = RealtimePersonalizationHints(
        keyterms=["ServerTerm"],
        replacements=server_replacements,
    )

    with patch(
        "app.api.routes.realtime_transcription.create_realtime_transcription_session",
        new=mint,
    ), patch(
        "app.api.routes.realtime_transcription.load_user_realtime_hints",
        new=AsyncMock(return_value=hints),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/transcription/session",
                headers={"Authorization": "Bearer fake-token"},
                json={
                    "language": "multi",
                    "channels": 1,
                    "purpose": "dictation",
                    "keyterms": ["WaiComputer", "Nova 3"],
                    "replacements": [
                        {"find": "why computer", "replace": "WaiComputer"},
                    ],
                },
            )

    assert response.status_code == 200
    assert mint.await_args.kwargs["keyterms"] == ["ServerTerm", "WaiComputer", "Nova 3"]
    assert mint.await_args.kwargs["replacements"] == [
        ("server wrong", "ServerRight"),
        ("why computer", "WaiComputer"),
    ]


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
    def __init__(
        self,
        headers: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
    ) -> None:
        self.headers = headers or {}
        self.query_params = query_params or {}
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


FINAL_CLOSE_STREAM_RESULT = (
    '{"type":"Results","channel":{"alternatives":[{"transcript":"final words"}]},'
    '"is_final":true}'
)


class CloseStreamDelayedFinalProvider:
    def __init__(self) -> None:
        self.sent: list[bytes | str] = []
        self.closed = False
        self._close_stream_received = asyncio.Event()
        self._final_sent = False

    async def send(self, payload: bytes | str) -> None:
        self.sent.append(payload)
        if isinstance(payload, str) and '"type":"CloseStream"' in payload.replace(" ", ""):
            self._close_stream_received.set()

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes | str:
        if self._final_sent:
            raise StopAsyncIteration
        await self._close_stream_received.wait()
        await asyncio.sleep(0.01)
        self._final_sent = True
        return FINAL_CLOSE_STREAM_RESULT


class CloseStreamThenConnectionClosedProvider:
    def __init__(self) -> None:
        self.sent: list[bytes | str] = []
        self.closed = False
        self._close_stream_received = asyncio.Event()

    async def send(self, payload: bytes | str) -> None:
        self.sent.append(payload)
        if isinstance(payload, str) and '"type":"CloseStream"' in payload.replace(" ", ""):
            self._close_stream_received.set()

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes | str:
        await self._close_stream_received.wait()
        raise ConnectionClosedError(None, None)


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


class SendTextFailingWebSocket(FakeWebSocket):
    async def send_text(self, payload: str) -> None:
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
async def test_realtime_stream_drains_provider_results_after_close_stream_disconnect():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})
    provider = CloseStreamDelayedFinalProvider()
    websocket.queue_receive({"type": "websocket.receive", "text": '{"type":"CloseStream"}'})
    websocket.queue_receive({"type": "websocket.disconnect"})

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
        "app.api.routes.realtime_transcription._websockets_header_kwarg",
        return_value="additional_headers",
    ):
        await route.stream_realtime_transcription(websocket)

    assert provider.sent == ['{"type":"CloseStream"}']
    assert provider.closed is False
    assert websocket.sent_text == [FINAL_CLOSE_STREAM_RESULT]
    assert websocket.closed_codes == [1000]


@pytest.mark.asyncio
async def test_realtime_stream_accepts_token_via_query_param():
    """Browsers cannot set the Authorization header on a WS handshake, so the
    proxy also accepts the short-lived session token via the `token` query
    param. Native clients keep using the header."""
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket(query_params={"token": "proxy-token"})
    provider = FakeProvider(messages=[b'{"type":"Metadata"}'])

    def fake_connect(url: str, **kwargs):
        return FakeProviderConnection(provider)

    with patch(
        "app.api.routes.realtime_transcription.decode_realtime_proxy_token",
        return_value=_claims(),
    ) as decode, patch(
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

    # Authenticated via the query param (no missing-bearer error), decoded that
    # token, and proxied the provider frame through.
    decode.assert_called_once_with("proxy-token")
    assert websocket.accepted is True
    assert route.PROXY_ERROR_MISSING_BEARER not in websocket.json_payloads
    assert websocket.sent_bytes == [b'{"type":"Metadata"}']


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


@pytest.mark.asyncio
async def test_realtime_stream_records_provider_connection_closed_as_failed():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})
    provider = FakeProvider()
    usage_events: list[dict[str, object]] = []

    async def waiting_client_to_provider(*args, **kwargs):
        await asyncio.sleep(60)

    async def provider_connection_closed(*args, **kwargs):
        raise ConnectionClosedError(None, None)

    async def record_usage(**kwargs):
        usage_events.append(kwargs)

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
        new=waiting_client_to_provider,
    ), patch(
        "app.api.routes.realtime_transcription._provider_to_client",
        new=provider_connection_closed,
    ), patch(
        "app.api.routes.realtime_transcription.record_deepgram_usage_event_standalone",
        new=record_usage,
    ):
        await route.stream_realtime_transcription(websocket)

    assert websocket.closed_codes == [1000]
    assert usage_events
    assert usage_events[-1]["status"] == "failed"
    assert usage_events[-1]["error_type"] == "ConnectionClosed"


@pytest.mark.asyncio
async def test_realtime_stream_records_client_send_runtime_error_as_successful_disconnect():
    from app.api.routes import realtime_transcription as route

    websocket = SendTextFailingWebSocket({"authorization": "Bearer proxy-token"})
    provider = FakeProvider(messages=['{"type":"Results","is_final":true}'])
    usage_events: list[dict[str, object]] = []

    async def record_usage(**kwargs):
        usage_events.append(kwargs)

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
        "app.api.routes.realtime_transcription.record_deepgram_usage_event_standalone",
        new=record_usage,
    ):
        await route.stream_realtime_transcription(websocket)

    assert websocket.json_payloads == []
    assert websocket.closed_codes == [1000]
    assert usage_events
    assert usage_events[-1]["status"] == "succeeded"
    assert usage_events[-1]["error_type"] is None


@pytest.mark.asyncio
async def test_realtime_stream_records_provider_close_after_close_stream_as_success():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})
    provider = CloseStreamThenConnectionClosedProvider()
    usage_events: list[dict[str, object]] = []
    websocket.queue_receive({"type": "websocket.receive", "text": '{"type":"CloseStream"}'})
    websocket.queue_receive({"type": "websocket.disconnect"})

    async def record_usage(**kwargs):
        usage_events.append(kwargs)

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
        "app.api.routes.realtime_transcription.record_deepgram_usage_event_standalone",
        new=record_usage,
    ):
        await route.stream_realtime_transcription(websocket)

    assert provider.sent == ['{"type":"CloseStream"}']
    assert websocket.json_payloads == []
    assert websocket.closed_codes == [1000]
    assert usage_events
    assert usage_events[-1]["status"] == "succeeded"
    assert usage_events[-1]["error_type"] is None


class DisconnectRaceProvider:
    """Provider whose read loop only fails once WE close it — reproduces the
    provider-close reaction to an abrupt client hang-up."""

    def __init__(self) -> None:
        self.sent: list[bytes | str] = []
        self.closed = False
        self._closed_event = asyncio.Event()

    async def send(self, payload: bytes | str) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True
        self._closed_event.set()

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes | str:
        await self._closed_event.wait()
        raise ConnectionClosedError(None, None)


@pytest.mark.asyncio
async def test_realtime_stream_client_abandon_is_not_recorded_as_failure():
    """Abrupt client disconnect (app killed, network drop, no CloseStream):
    upstream closes the provider, downstream's read races into
    ConnectionClosed. That used to escape and mark the stream 'failed'
    (22 of 49 'failed' streams in the 2026-06 window)."""
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})
    provider = DisconnectRaceProvider()
    usage_events: list[dict[str, object]] = []
    websocket.queue_receive({"type": "websocket.receive", "bytes": b"pcm"})
    websocket.queue_receive({"type": "websocket.disconnect"})

    async def record_usage(**kwargs):
        usage_events.append(kwargs)

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
        "app.api.routes.realtime_transcription.record_deepgram_usage_event_standalone",
        new=record_usage,
    ):
        await route.stream_realtime_transcription(websocket)

    assert provider.closed is True
    assert websocket.json_payloads == []
    assert usage_events
    assert usage_events[-1]["status"] == "succeeded"
    assert usage_events[-1]["error_type"] is None


class PaymentRequiredConnection:
    """Simulates websockets.connect rejected by Deepgram with HTTP 402."""

    async def __aenter__(self):
        error = RuntimeError("server rejected WebSocket connection: HTTP 402")
        error.status_code = 402
        raise error

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.mark.asyncio
async def test_realtime_stream_402_trips_provider_breaker():
    """Deepgram credit exhaustion (2026-06-27: 9 streams failed with 402) must
    open the circuit breaker so session mints fast-fail and ops get paged —
    previously only the batch path fed the breaker."""
    from app.api.routes import realtime_transcription as route
    from app.core import transcription_guard as guard

    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})
    usage_events: list[dict[str, object]] = []

    async def record_usage(**kwargs):
        usage_events.append(kwargs)

    with patch(
        "app.api.routes.realtime_transcription.decode_realtime_proxy_token",
        return_value=_claims(),
    ), patch(
        "app.api.routes.realtime_transcription.require_deepgram_api_key",
        return_value="server-provider-key",
    ), patch(
        "app.api.routes.realtime_transcription.websockets.connect",
        return_value=PaymentRequiredConnection(),
    ), patch(
        "app.api.routes.realtime_transcription.record_deepgram_usage_event_standalone",
        new=record_usage,
    ):
        await route.stream_realtime_transcription(websocket)

    assert await guard.provider_breaker_open() is True
    assert usage_events
    assert usage_events[-1]["status"] == "failed"
    assert usage_events[-1]["provider_status_code"] == 402


@pytest.mark.asyncio
async def test_realtime_stream_success_resets_provider_breaker_streak():
    from app.api.routes import realtime_transcription as route
    from app.core import transcription_guard as guard

    await guard.record_provider_result(success=False)
    assert await guard.get_redis().exists("dg:breaker:fails") == 1

    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})
    provider = FakeProvider(messages=['{"type":"Results"}'])

    with patch(
        "app.api.routes.realtime_transcription.decode_realtime_proxy_token",
        return_value=_claims(),
    ), patch(
        "app.api.routes.realtime_transcription.require_deepgram_api_key",
        return_value="server-provider-key",
    ), patch(
        "app.api.routes.realtime_transcription.websockets.connect",
        return_value=FakeProviderConnection(provider),
    ):
        await route.stream_realtime_transcription(websocket)

    assert await guard.get_redis().exists("dg:breaker:fails") == 0


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

    await route._client_to_provider(websocket, provider, asyncio.Event(), asyncio.Event())

    assert provider.sent == [b"pcm", '{"type":"KeepAlive"}']
    assert provider.closed is True


@pytest.mark.asyncio
async def test_provider_to_client_forwards_binary_and_text_messages():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket()
    provider = FakeProvider(messages=[b"binary", "text"])

    await route._provider_to_client(websocket, provider, asyncio.Event(), asyncio.Event())

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
    """The Deepgram breaker gates Deepgram-backed mints (recording)."""
    from app.core import transcription_guard as guard

    await guard.record_provider_result(success=False, status_code=402)
    response = await _post_session(
        {"language": "multi", "channels": 1, "purpose": "recording"}
    )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_realtime_dictation_mint_ignores_deepgram_breaker(mock_authenticated_user):
    """Dictation rides OpenAI; a Deepgram outage must not block it."""
    from app.core import transcription_guard as guard

    await guard.record_provider_result(success=False, status_code=402)
    with patch(
        "app.core.realtime_transcription.require_openai_api_key",
        return_value="provider_key",
    ):
        response = await _post_session()
    assert response.status_code == 200
    assert response.json()["provider"] == "openai"


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


@pytest.mark.asyncio
async def test_realtime_stream_releases_slot_when_breadcrumb_raises(monkeypatch):
    """A failure in the post-acquire 'proxy opened' breadcrumb must not leak the
    stream slot. The slot is acquired before the relay; anything between acquire
    and the finally that raises unguarded leaks the slot for the full lease TTL
    (up to ~65 min for dictation), locking the user out behind TOO_MANY_STREAMS.
    """
    from app.api.routes import realtime_transcription as route
    from app.config import get_settings
    from app.core import transcription_guard as guard

    monkeypatch.setattr(get_settings(), "realtime_max_concurrent_streams_per_user", 1)

    real_breadcrumb = route.add_sentry_breadcrumb

    def _boom(*args, **kwargs):
        if kwargs.get("message") == "proxy opened":
            raise RuntimeError("sentry breadcrumb backend unavailable")
        return real_breadcrumb(*args, **kwargs)

    monkeypatch.setattr(route, "add_sentry_breadcrumb", _boom)

    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})
    with patch(
        "app.api.routes.realtime_transcription.decode_realtime_proxy_token",
        return_value=_claims(),
    ), patch(
        "app.api.routes.realtime_transcription.require_deepgram_api_key",
        return_value="server-provider-key",
    ):
        # The breadcrumb raise must be caught (not propagated) by the route...
        await route.stream_realtime_transcription(websocket)

    assert route.PROXY_ERROR_PAYLOAD in websocket.json_payloads
    assert websocket.closed_codes == [1011]
    # ...and the single per-user slot must be free again — the finally ran.
    token = await guard.acquire_stream_slot("user-transcription", lease_ttl_seconds=60)
    assert token is not None, "stream slot leaked after a post-acquire failure"


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


# --- OpenAI realtime bridge (dictation) --------------------------------------

import base64  # noqa: E402
import json as _json  # noqa: E402


def _openai_claims(
    replacements: list[tuple[str, str]] | None = None,
) -> RealtimeTranscriptionProxyClaims:
    return RealtimeTranscriptionProxyClaims(
        subject="user-transcription",
        language="ru",
        channels=1,
        model="gpt-realtime-whisper",
        purpose="dictation",
        provider="openai",
        replacements=replacements or [],
    )


class OpenAIScriptedProvider:
    """Interactive OpenAI realtime fake: replies to session.update and commit."""

    _END = object()

    def __init__(
        self,
        *,
        reject_session: bool = False,
        error_on_append: dict | None = None,
    ) -> None:
        self.sent: list[str] = []
        self.closed = False
        self.reject_session = reject_session
        self.error_on_append = error_on_append
        self._queue: asyncio.Queue = asyncio.Queue()

    def script(self, event: dict) -> None:
        self._queue.put_nowait(_json.dumps(event))

    async def send(self, payload: str) -> None:
        self.sent.append(payload)
        message = _json.loads(payload)
        message_type = message.get("type")
        if message_type == "session.update":
            if self.reject_session:
                self.script(
                    {
                        "type": "error",
                        "error": {"code": "invalid_value", "message": "bad config"},
                    }
                )
                return
            self.script({"type": "session.created"})
            self.script({"type": "session.updated"})
        elif message_type == "input_audio_buffer.append":
            if self.error_on_append is not None:
                self.script({"type": "error", "error": self.error_on_append})
                self.error_on_append = None
        elif message_type == "input_audio_buffer.commit":
            self.script(
                {
                    "type": "conversation.item.input_audio_transcription.delta",
                    "item_id": "item_1",
                    "delta": "привет мир",
                }
            )
            self.script(
                {
                    "type": "conversation.item.input_audio_transcription.completed",
                    "item_id": "item_1",
                    "transcript": "Привет, мир!",
                }
            )

    async def recv(self) -> str:
        item = await self._queue.get()
        if item is self._END:
            raise StopAsyncIteration
        return item

    async def close(self) -> None:
        self.closed = True
        self._queue.put_nowait(self._END)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        item = await self._queue.get()
        if item is self._END:
            raise StopAsyncIteration
        return item


def _patched_openai_stream(provider: OpenAIScriptedProvider, claims=None):
    return (
        patch(
            "app.api.routes.realtime_transcription.decode_realtime_proxy_token",
            return_value=claims or _openai_claims(),
        ),
        patch(
            "app.api.routes.realtime_transcription.require_openai_api_key",
            return_value="server-openai-key",
        ),
        patch(
            "app.api.routes.realtime_transcription.websockets.connect",
            new=lambda url, **kwargs: FakeProviderConnection(provider),
        ),
        patch(
            "app.api.routes.realtime_transcription._websockets_header_kwarg",
            return_value="additional_headers",
        ),
    )


@pytest.mark.asyncio
async def test_openai_stream_translates_audio_finalize_and_close():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})
    provider = OpenAIScriptedProvider()
    pcm = b"\x01\x02" * (24_000 // 2)  # 500 ms of 24 kHz PCM16
    websocket.queue_receive({"type": "websocket.receive", "bytes": pcm})
    websocket.queue_receive({"type": "websocket.receive", "text": '{"type":"KeepAlive"}'})
    websocket.queue_receive({"type": "websocket.receive", "text": '{"type":"Finalize"}'})
    websocket.queue_receive({"type": "websocket.receive", "text": '{"type":"CloseStream"}'})

    claims = _openai_claims(replacements=[("мир", "world")])
    patches = _patched_openai_stream(provider, claims)
    with patches[0], patches[1], patches[2], patches[3]:
        await route.stream_realtime_transcription(websocket)

    sent_types = [_json.loads(item).get("type") for item in provider.sent]
    assert sent_types[0] == "session.update"
    session_config = _json.loads(provider.sent[0])["session"]
    assert session_config["type"] == "transcription"
    assert session_config["audio"]["input"]["turn_detection"] is None
    assert session_config["audio"]["input"]["transcription"]["model"] == "gpt-realtime-whisper"

    appends = [
        _json.loads(item)
        for item in provider.sent
        if _json.loads(item).get("type") == "input_audio_buffer.append"
    ]
    assert base64.b64decode(appends[0]["audio"]) == pcm
    assert "input_audio_buffer.commit" in sent_types

    results = [p for p in websocket.json_payloads if p.get("type") == "Results"]
    assert results, websocket.json_payloads
    interim = results[0]
    assert interim["is_final"] is False
    assert interim["channel"]["alternatives"][0]["transcript"] == "привет world"
    final = results[-1]
    assert final["is_final"] is True
    assert final["from_finalize"] is True
    assert final["channel"]["alternatives"][0]["transcript"] == "Привет, world!"

    assert provider.closed is True
    assert websocket.closed_codes == [1000]


@pytest.mark.asyncio
async def test_openai_stream_marks_empty_finalize_without_commit():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})
    provider = OpenAIScriptedProvider()
    # 50 ms of audio — below the 120 ms commit floor.
    websocket.queue_receive({"type": "websocket.receive", "bytes": b"\x00" * 2_400})
    websocket.queue_receive({"type": "websocket.receive", "text": '{"type":"Finalize"}'})
    websocket.queue_receive({"type": "websocket.receive", "text": '{"type":"CloseStream"}'})

    patches = _patched_openai_stream(provider)
    with patches[0], patches[1], patches[2], patches[3]:
        await route.stream_realtime_transcription(websocket)

    sent_types = [_json.loads(item).get("type") for item in provider.sent]
    assert "input_audio_buffer.commit" not in sent_types
    metadata_frames = [p for p in websocket.json_payloads if p.get("type") == "Metadata"]
    assert metadata_frames, websocket.json_payloads
    assert websocket.closed_codes == [1000]


@pytest.mark.asyncio
async def test_openai_stream_rejected_session_config_fails_loudly():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})
    provider = OpenAIScriptedProvider(reject_session=True)

    patches = _patched_openai_stream(provider)
    with patches[0], patches[1], patches[2], patches[3]:
        await route.stream_realtime_transcription(websocket)

    assert route.PROXY_ERROR_PAYLOAD in websocket.json_payloads
    assert websocket.closed_codes == [1011]


@pytest.mark.asyncio
async def test_openai_stream_reports_missing_api_key():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})

    with patch(
        "app.api.routes.realtime_transcription.decode_realtime_proxy_token",
        return_value=_openai_claims(),
    ), patch(
        "app.api.routes.realtime_transcription.require_openai_api_key",
        side_effect=ValueError("OPENAI_API_KEY is not configured"),
    ):
        await route.stream_realtime_transcription(websocket)

    assert websocket.json_payloads == [route.PROXY_ERROR_MISSING_API_KEY]
    assert websocket.closed_codes == [1011]


@pytest.mark.asyncio
async def test_openai_stream_client_disconnect_closes_provider():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})
    provider = OpenAIScriptedProvider()
    websocket.queue_receive({"type": "websocket.receive", "bytes": b"\x00" * 9_600})
    websocket.queue_receive({"type": "websocket.disconnect"})

    patches = _patched_openai_stream(provider)
    with patches[0], patches[1], patches[2], patches[3]:
        await route.stream_realtime_transcription(websocket)

    assert provider.closed is True
    # Client is gone: no close frame is owed to it.
    assert websocket.closed_codes == []


@pytest.mark.asyncio
async def test_openai_stream_maps_upstream_error_frames():
    from app.api.routes import realtime_transcription as route

    websocket = FakeWebSocket({"authorization": "Bearer proxy-token"})
    provider = OpenAIScriptedProvider(
        error_on_append={"code": "insufficient_quota", "message": "Quota exceeded"},
    )
    websocket.queue_receive({"type": "websocket.receive", "bytes": b"\x00" * 9_600})
    websocket.queue_receive({"type": "websocket.receive", "text": '{"type":"CloseStream"}'})

    patches = _patched_openai_stream(provider)
    with patches[0], patches[1], patches[2], patches[3]:
        await route.stream_realtime_transcription(websocket)

    error_frames = [p for p in websocket.json_payloads if p.get("type") == "Error"]
    assert error_frames and error_frames[0]["err_code"] == "insufficient_quota"
