"""Unit tests for the Inworld realtime STT integration."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.core.inworld import (
    INWORLD_STT_WS_URL,
    build_inworld_jwt_authorization,
    build_session,
    inline_query_url,
    mint_client_jwt,
    normalise_inworld_credential,
    split_inworld_credential,
)


def test_normalise_credential_accepts_raw_id_secret() -> None:
    raw = "client_abc:secret_xyz"
    encoded = normalise_inworld_credential(raw)
    decoded = base64.b64decode(encoded).decode("utf-8")
    assert decoded == raw


def test_normalise_credential_passes_through_already_base64() -> None:
    raw = "id:secret"
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    assert normalise_inworld_credential(encoded) == encoded


def test_normalise_credential_accepts_basic_header_value() -> None:
    raw = "id:secret"
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    assert normalise_inworld_credential(f"Basic {encoded}") == encoded


def test_normalise_credential_rejects_empty() -> None:
    with pytest.raises(ValueError):
        normalise_inworld_credential("   ")


def test_normalise_credential_rejects_plain_string_without_colon() -> None:
    with pytest.raises(ValueError):
        # 32 chars, plausible API token shape but no colon and not valid base64.
        normalise_inworld_credential("not-a-valid-credential-format-x")


def test_split_credential_accepts_basic_base64() -> None:
    encoded = base64.b64encode(b"client_abc:secret_xyz").decode("ascii")
    assert split_inworld_credential(encoded) == ("client_abc", "secret_xyz")


def test_split_credential_accepts_basic_header_value() -> None:
    encoded = base64.b64encode(b"client_abc:secret_xyz").decode("ascii")
    assert split_inworld_credential(f"Basic {encoded}") == ("client_abc", "secret_xyz")


def test_build_inworld_jwt_authorization_is_deterministic_for_inputs() -> None:
    header = build_inworld_jwt_authorization(
        key="client_abc",
        secret="secret_xyz",
        now=datetime(2026, 5, 19, 10, 30, 0, tzinfo=UTC),
        nonce="abcdef123456",
    )

    assert header.startswith(
        "IW1-HMAC-SHA256 ApiKey=client_abc,DateTime=20260519103000,"
        "Nonce=abcdef123456,Signature="
    )
    assert header.rsplit("Signature=", 1)[1] == (
        "15b24c267b4099db344e1c41cab21fa26c9f984ad5ff793705ea302eeeb61982"
    )


def test_build_session_uses_inworld_default_and_basic_auth() -> None:
    session = build_session(api_key="user:pass")

    assert session.websocket_url == INWORLD_STT_WS_URL
    assert session.model_id == "inworld/inworld-stt-1"
    assert session.audio_encoding == "LINEAR16"
    assert session.sample_rate_hertz == 16_000
    assert session.number_of_channels == 1
    assert session.auth_header.startswith("Basic ")
    decoded = base64.b64decode(session.auth_header.removeprefix("Basic ")).decode("utf-8")
    assert decoded == "user:pass"


def test_build_session_honours_overrides() -> None:
    session = build_session(
        api_key="user:pass",
        model_id="inworld/inworld-stt-1",
        language="ru",
        sample_rate=24_000,
        channels=2,
        auth_header="Bearer jwt-token",
        expires_in_seconds=850,
    )
    assert session.model_id == "inworld/inworld-stt-1"
    assert session.language == "ru"
    assert session.sample_rate_hertz == 24_000
    assert session.number_of_channels == 2
    assert session.auth_header == "Bearer jwt-token"
    assert session.expires_in_seconds == 850


def test_build_session_normalises_blank_language_to_multi() -> None:
    session = build_session(api_key="user:pass", language="   ")
    assert session.language == "multi"


def test_inline_query_url_includes_auth_header() -> None:
    session = build_session(api_key="user:pass")
    url = inline_query_url(session)
    assert url.startswith(INWORLD_STT_WS_URL)
    assert "key=Basic" in url


@pytest.mark.asyncio
async def test_mint_client_jwt_posts_signed_request() -> None:
    response = type(
        "Response",
        (),
        {
            "status_code": 200,
            "json": lambda self: {
                "token": "jwt-token",
                "expirationTime": "2026-05-19T10:45:00Z",
                "sessionId": "default:abc",
            },
        },
    )()
    client = type(
        "Client",
        (),
        {"post": AsyncMock(return_value=response)},
    )()
    async_ctx = type(
        "AsyncContext",
        (),
        {
            "__aenter__": AsyncMock(return_value=client),
            "__aexit__": AsyncMock(return_value=None),
        },
    )()

    with (
        patch("app.core.inworld.httpx.AsyncClient", return_value=async_ctx),
        patch(
            "app.core.inworld.datetime",
        ) as datetime_mock,
    ):
        datetime_mock.now.return_value = datetime(2026, 5, 19, 10, 30, 0, tzinfo=UTC)
        datetime_mock.fromisoformat.side_effect = datetime.fromisoformat
        token = await mint_client_jwt(
            api_key=base64.b64encode(b"client_abc:secret_xyz").decode("ascii"),
            workspace="",
        )

    assert token.token == "jwt-token"
    assert token.expires_in_seconds == 900
    assert token.session_id == "default:abc"
    call = client.post.await_args
    assert call.args == ("/auth/v1/tokens/token:generate",)
    assert call.kwargs["json"] == {"key": "client_abc", "resources": []}
    assert call.kwargs["headers"]["Authorization"].startswith(
        "IW1-HMAC-SHA256 ApiKey=client_abc,"
    )
