"""Tests for realtime transcription provider abstraction."""

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.realtime_transcription import (
    RealtimeTranscriptionSession,
    _build_deepgram_realtime_session,
    _build_inworld_realtime_session,
    _build_openai_realtime_session,
    _create_elevenlabs_realtime_token,
    _deepgram_proxy_websocket_url,
    create_realtime_transcription_session,
)


@pytest.mark.asyncio
async def test_create_elevenlabs_realtime_token_uses_token_value():
    response = httpx.Response(
        200,
        json={"token": "single-use-token-for-test"},
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/single-use-token/realtime_scribe"),
    )

    with (
        patch("app.core.realtime_transcription.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "xi-key"
        token, expires_in = await _create_elevenlabs_realtime_token()

    assert token == "single-use-token-for-test"
    assert expires_in == 900


@pytest.mark.asyncio
async def test_create_elevenlabs_realtime_token_rejects_invalid_payload():
    response = httpx.Response(
        200,
        json={"token": ""},
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/single-use-token/realtime_scribe"),
    )

    with (
        patch("app.core.realtime_transcription.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "xi-key"
        with pytest.raises(RuntimeError, match="invalid realtime transcription token"):
            await _create_elevenlabs_realtime_token()


@pytest.mark.asyncio
async def test_create_elevenlabs_realtime_token_requires_api_key():
    with patch("app.core.realtime_transcription.get_settings") as mock_settings:
        mock_settings.return_value.elevenlabs_api_key = ""
        with pytest.raises(ValueError, match="ELEVENLABS_API_KEY not configured"):
            await _create_elevenlabs_realtime_token()


@pytest.mark.asyncio
async def test_create_realtime_transcription_session_uses_inworld_recording_defaults():
    fake_jwt = type(
        "InworldJwt",
        (),
        {"token": "iw-jwt", "expires_in_seconds": 850},
    )()

    with (
        patch("app.core.realtime_transcription.get_settings") as mock_settings,
        patch(
            "app.core.realtime_transcription.mint_inworld_client_jwt",
            new=AsyncMock(return_value=fake_jwt),
        ),
    ):
        mock_settings.return_value.inworld_api_key = "user:pass"
        mock_settings.return_value.inworld_workspace = ""
        from app.core.realtime_transcription import create_realtime_transcription_session

        session = await create_realtime_transcription_session(language="multi", channels=1)

    assert session == RealtimeTranscriptionSession(
        provider="inworld",
        token="iw-jwt",
        expires_in_seconds=850,
        sample_rate=16_000,
        audio_format="linear16_16000",
        language="multi",
        channels=1,
        model="inworld/inworld-stt-1",
        keep_alive_interval_seconds=None,
        commit_strategy="vad",
        no_verbatim=False,
        websocket_url="wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional",
        auth_scheme="bearer",
    )


@pytest.mark.asyncio
async def test_create_realtime_transcription_session_uses_soniox_recording_choice():
    user = type(
        "User",
        (),
        {
            "recording_live_stt_provider": "soniox",
            "recording_live_stt_model": "stt-rt-v4",
        },
    )()
    from app.core.realtime_transcription import create_realtime_transcription_session

    fake_soniox = type(
        "SonioxSession",
        (),
        {
            "temporary_api_key": "sx-temp",
            "expires_in_seconds": 60,
            "sample_rate": 16_000,
            "language": "ru",
            "channels": 2,
            "model": "stt-rt-v4",
            "websocket_url": "wss://stt-rt.soniox.com/transcribe-websocket",
        },
    )()
    with patch(
        "app.core.realtime_transcription.mint_soniox_realtime_session",
        new=AsyncMock(return_value=fake_soniox),
    ):
        session = await create_realtime_transcription_session(
            language="ru",
            channels=2,
            purpose="recording",
            user=user,
        )

    assert session.provider == "soniox"
    assert session.model == "stt-rt-v4"
    assert session.language == "ru"
    assert session.channels == 2
    assert session.token == "sx-temp"
    assert session.auth_scheme == "message_api_key"
    assert session.websocket_url == "wss://stt-rt.soniox.com/transcribe-websocket"


@pytest.mark.asyncio
async def test_create_realtime_transcription_session_uses_inworld_bearer_jwt():
    user = type(
        "User",
        (),
        {
            "recording_live_stt_provider": "inworld",
            "recording_live_stt_model": "inworld/inworld-stt-1",
        },
    )()
    fake_jwt = type(
        "InworldJwt",
        (),
        {"token": "iw-jwt", "expires_in_seconds": 850},
    )()

    from app.core.realtime_transcription import create_realtime_transcription_session

    with (
        patch("app.core.realtime_transcription.get_settings") as mock_settings,
        patch(
            "app.core.realtime_transcription.mint_inworld_client_jwt",
            new=AsyncMock(return_value=fake_jwt),
        ),
    ):
        mock_settings.return_value.inworld_api_key = "user:pass"
        mock_settings.return_value.inworld_workspace = ""
        session = await create_realtime_transcription_session(
            language="ru",
            channels=2,
            purpose="recording",
            user=user,
        )

    assert session.provider == "inworld"
    assert session.model == "inworld/inworld-stt-1"
    assert session.language == "ru"
    assert session.channels == 2
    assert session.token == "iw-jwt"
    assert session.auth_scheme == "bearer"
    assert session.expires_in_seconds == 850
    assert session.websocket_url == "wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional"


@pytest.mark.asyncio
async def test_create_realtime_transcription_session_rejects_bad_recording_model():
    user = type(
        "User",
        (),
        {"recording_live_stt_provider": "openai", "recording_live_stt_model": "bad-model"},
    )()
    from app.core.realtime_transcription import create_realtime_transcription_session

    with pytest.raises(ValueError, match="Unsupported recording_live_stt option"):
        await create_realtime_transcription_session(user=user)


@pytest.mark.asyncio
async def test_create_dictation_session_rejects_removed_openai_realtime_model():
    user = type(
        "User",
        (),
        {
            "dictation_live_stt_provider": "openai",
            "dictation_live_stt_model": "gpt-realtime-whisper",
        },
    )()
    from app.core.realtime_transcription import create_realtime_transcription_session

    with pytest.raises(ValueError, match="Unsupported dictation_live_stt option"):
        await create_realtime_transcription_session(
            language="en",
            channels=1,
            purpose="dictation",
            user=user,
        )


@pytest.mark.asyncio
async def test_build_openai_realtime_session_uses_client_secret_and_ws_url():
    with (
        patch(
            "app.core.realtime_transcription.create_openai_realtime_client_secret",
            new=AsyncMock(return_value="openai-secret"),
        ) as create_secret,
        patch(
            "app.core.realtime_transcription.openai_realtime_websocket_url",
            return_value="wss://openai.example/realtime",
        ),
    ):
        session = await _build_openai_realtime_session(
            model="gpt-4o-mini-transcribe",
            language=" RU ",
            channels=2,
        )

    create_secret.assert_awaited_once_with(model="gpt-4o-mini-transcribe", language=" RU ")
    assert session.provider == "openai"
    assert session.token == "openai-secret"
    assert session.sample_rate == 24_000
    assert session.audio_format == "pcm_24000"
    assert session.commit_strategy == "manual"
    assert session.no_verbatim is False
    assert session.websocket_url == "wss://openai.example/realtime"
    assert session.auth_scheme == "bearer"


@pytest.mark.asyncio
async def test_build_deepgram_realtime_session_uses_authenticated_proxy_token():
    user = type("User", (), {"id": "user-123"})()

    with (
        patch("app.core.realtime_transcription.get_settings") as mock_settings,
        patch(
            "app.core.realtime_transcription.create_access_token",
            return_value="proxy-jwt",
        ) as create_token,
    ):
        mock_settings.return_value.deepgram_api_key = "deepgram-test-key"
        mock_settings.return_value.deepgram_realtime_proxy_token_ttl_seconds = 120
        mock_settings.return_value.frontend_url = "https://wai.computer"
        session = await _build_deepgram_realtime_session(
            model="flux-general-multi",
            language="ru",
            channels=2,
            user=user,
        )

    create_token.assert_called_once()
    assert session.provider == "deepgram"
    assert session.token == "proxy-jwt"
    assert session.expires_in_seconds == 120
    assert session.audio_format == "linear16_16000"
    assert session.language == "ru"
    assert session.channels == 2
    assert session.websocket_url == (
        "wss://wai.computer/api/transcription/deepgram-proxy?"
        "model=flux-general-multi&language=ru&channels=2"
    )
    assert session.auth_scheme == "bearer"


@pytest.mark.asyncio
async def test_build_deepgram_realtime_session_requires_proxy_api_key_for_user():
    user = type("User", (), {"id": "user-123"})()

    with patch("app.core.realtime_transcription.get_settings") as mock_settings:
        mock_settings.return_value.deepgram_api_key = ""
        with pytest.raises(ValueError, match="DEEPGRAM_API_KEY not configured"):
            await _build_deepgram_realtime_session(
                model="flux-general-multi",
                language="ru",
                channels=1,
                user=user,
            )


@pytest.mark.asyncio
async def test_build_deepgram_realtime_session_uses_provider_grant_without_user():
    fake_session = type(
        "DeepgramSession",
        (),
        {
            "access_token": "dg-temp",
            "expires_in_seconds": 300,
            "sample_rate": 16_000,
            "language": "multi",
            "channels": 1,
            "model": "flux-general-multi",
            "keep_alive_interval_seconds": 5,
            "websocket_url": "wss://deepgram.example/listen",
        },
    )()

    with patch(
        "app.core.realtime_transcription.mint_deepgram_realtime_session",
        new=AsyncMock(return_value=fake_session),
    ) as mint_session:
        session = await _build_deepgram_realtime_session(
            model="flux-general-multi",
            language="multi",
            channels=1,
        )

    mint_session.assert_awaited_once_with(
        model="flux-general-multi",
        language="multi",
        channels=1,
    )
    assert session.provider == "deepgram"
    assert session.token == "dg-temp"
    assert session.keep_alive_interval_seconds == 5
    assert session.websocket_url == "wss://deepgram.example/listen"


def test_deepgram_proxy_websocket_url_matches_frontend_scheme():
    with patch("app.core.realtime_transcription.get_settings") as mock_settings:
        mock_settings.return_value.frontend_url = "https://wai.computer/"
        assert _deepgram_proxy_websocket_url(
            model="flux", language="ru", channels=0
        ) == "wss://wai.computer/api/transcription/deepgram-proxy?model=flux&language=ru&channels=1"

        mock_settings.return_value.frontend_url = "http://localhost:3000"
        assert _deepgram_proxy_websocket_url(
            model="flux", language="multi", channels=2
        ) == (
            "ws://localhost:3000/api/transcription/deepgram-proxy?"
            "model=flux&language=multi&channels=2"
        )

        mock_settings.return_value.frontend_url = "ws://local.test"
        assert _deepgram_proxy_websocket_url(
            model="flux", language="en", channels=1
        ).startswith("ws://local.test/api/transcription/deepgram-proxy?")


@pytest.mark.asyncio
async def test_build_inworld_realtime_session_requires_api_key():
    with patch("app.core.realtime_transcription.get_settings") as mock_settings:
        mock_settings.return_value.inworld_api_key = ""
        with pytest.raises(ValueError, match="INWORLD_API_KEY not configured"):
            await _build_inworld_realtime_session("ru", 1, model="inworld/inworld-stt-1")


@pytest.mark.asyncio
async def test_create_dictation_session_uses_deepgram_proxy_for_authenticated_user():
    user = type(
        "User",
        (),
        {
            "id": "user-123",
            "dictation_live_stt_provider": "deepgram",
            "dictation_live_stt_model": "flux-general-multi",
        },
    )()

    with (
        patch("app.core.realtime_transcription.get_settings") as mock_settings,
        patch("app.core.realtime_transcription.create_access_token", return_value="proxy-jwt"),
    ):
        mock_settings.return_value.deepgram_api_key = "deepgram-test-key"
        mock_settings.return_value.deepgram_realtime_proxy_token_ttl_seconds = 60
        mock_settings.return_value.frontend_url = "https://wai.computer"
        session = await create_realtime_transcription_session(
            language=" RU ",
            channels=0,
            purpose="dictation",
            user=user,
        )

    assert session.provider == "deepgram"
    assert session.language == "ru"
    assert session.channels == 1
    assert session.token == "proxy-jwt"


@pytest.mark.asyncio
async def test_create_recording_session_uses_elevenlabs_when_selected():
    user = type(
        "User",
        (),
        {
            "recording_live_stt_provider": "elevenlabs",
            "recording_live_stt_model": "scribe_v2_realtime",
        },
    )()

    with (
        patch("app.core.realtime_transcription.get_settings") as mock_settings,
        patch(
            "app.core.realtime_transcription._create_elevenlabs_realtime_token",
            new=AsyncMock(return_value=("sutkn", 900)),
        ),
    ):
        mock_settings.return_value.elevenlabs_no_verbatim = False
        session = await create_realtime_transcription_session(
            language="EN",
            channels=2,
            purpose="recording",
            user=user,
        )

    assert session.provider == "elevenlabs"
    assert session.language == "en"
    assert session.channels == 2
    assert session.no_verbatim is False
    assert session.auth_scheme == "query_token"


class _ProxyWebSocket:
    def __init__(self, *, authorization: str | None = "Bearer token", messages=None) -> None:
        self.headers = {"authorization": authorization} if authorization is not None else {}
        self.accepted = False
        self.closed: list[int] = []
        self.sent_bytes: list[bytes] = []
        self.sent_text: list[str] = []
        self._messages = list(messages or [])

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int) -> None:
        self.closed.append(code)

    async def receive(self) -> dict:
        if not self._messages:
            raise WebSocketDisconnect()
        message = self._messages.pop(0)
        if message.get("disconnect"):
            raise WebSocketDisconnect()
        return message

    async def send_bytes(self, message: bytes) -> None:
        self.sent_bytes.append(message)

    async def send_text(self, message: str) -> None:
        self.sent_text.append(message)


class _ProxyUpstream:
    def __init__(self, messages=None) -> None:
        self.sent: list[bytes | str] = []
        self._messages = list(messages or [])

    async def send(self, message: bytes | str) -> None:
        self.sent.append(message)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            await asyncio.sleep(60)
        return self._messages.pop(0)


class _ProxyConnect:
    def __init__(self, upstream: _ProxyUpstream, *, fail: bool = False) -> None:
        self.upstream = upstream
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self

    async def __aenter__(self):
        if self.fail:
            raise RuntimeError("upstream failed")
        return self.upstream

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_deepgram_proxy_rejects_missing_or_invalid_bearer_token():
    from app.api.routes.realtime_transcription import _bearer_token, deepgram_realtime_proxy

    assert _bearer_token(None) is None
    assert _bearer_token("Basic abc") is None
    assert _bearer_token("Bearer   ") is None
    assert _bearer_token("Bearer abc") == "abc"

    websocket = _ProxyWebSocket(authorization=None)
    await deepgram_realtime_proxy(websocket, model="flux-general-multi")
    assert websocket.closed == [1008]

    with patch("app.api.routes.realtime_transcription.decode_access_token", return_value=None):
        websocket = _ProxyWebSocket()
        await deepgram_realtime_proxy(websocket, model="flux-general-multi")
    assert websocket.closed == [1008]


@pytest.mark.asyncio
async def test_deepgram_proxy_rejects_invalid_model_and_missing_api_key():
    from app.api.routes.realtime_transcription import deepgram_realtime_proxy

    with patch(
        "app.api.routes.realtime_transcription.decode_access_token",
        return_value={"sub": "u"},
    ):
        invalid_model = _ProxyWebSocket()
        await deepgram_realtime_proxy(invalid_model, model="not-a-model")
        assert invalid_model.closed == [1008]

    with (
        patch(
            "app.api.routes.realtime_transcription.decode_access_token",
            return_value={"sub": "u"},
        ),
        patch("app.api.routes.realtime_transcription.get_settings") as mock_settings,
    ):
        mock_settings.return_value.deepgram_api_key = ""
        missing_key = _ProxyWebSocket()
        await deepgram_realtime_proxy(missing_key, model="flux-general-multi")
        assert missing_key.closed == [1011]


@pytest.mark.asyncio
async def test_deepgram_proxy_relays_audio_control_and_upstream_messages(monkeypatch):
    from app.api.routes.realtime_transcription import deepgram_realtime_proxy

    websocket = _ProxyWebSocket(
        messages=[
            {"bytes": b"pcm"},
            {"text": '{"type":"KeepAlive"}'},
            {"text": '{"type":"ignored"}'},
            {"disconnect": True},
        ]
    )
    upstream = _ProxyUpstream(messages=[b"binary-from-upstream", "text-from-upstream"])
    connector = _ProxyConnect(upstream)
    monkeypatch.setattr("app.api.routes.realtime_transcription.websockets.connect", connector)

    with (
        patch(
            "app.api.routes.realtime_transcription.decode_access_token",
            return_value={"sub": "u"},
        ),
        patch("app.api.routes.realtime_transcription.get_settings") as mock_settings,
    ):
        mock_settings.return_value.deepgram_api_key = "deepgram-test-key"
        await deepgram_realtime_proxy(
            websocket,
            model="flux-general-multi",
            language="ru",
            channels=2,
        )

    assert websocket.accepted is True
    assert websocket.sent_bytes == [b"binary-from-upstream"]
    assert websocket.sent_text == ["text-from-upstream"]
    assert upstream.sent == [b"pcm", '{"type":"KeepAlive"}']
    assert connector.calls[0][1]["additional_headers"] == {"Authorization": "Token deepgram-test-key"}


@pytest.mark.asyncio
async def test_deepgram_proxy_closes_on_upstream_failure(monkeypatch):
    from app.api.routes.realtime_transcription import deepgram_realtime_proxy

    websocket = _ProxyWebSocket(messages=[{"bytes": b"pcm"}])
    monkeypatch.setattr(
        "app.api.routes.realtime_transcription.websockets.connect",
        _ProxyConnect(_ProxyUpstream(), fail=True),
    )

    with (
        patch(
            "app.api.routes.realtime_transcription.decode_access_token",
            return_value={"sub": "u"},
        ),
        patch("app.api.routes.realtime_transcription.get_settings") as mock_settings,
    ):
        mock_settings.return_value.deepgram_api_key = "deepgram-test-key"
        await deepgram_realtime_proxy(websocket, model="flux-general-multi")

    assert websocket.accepted is True
    assert websocket.closed == [1011]
