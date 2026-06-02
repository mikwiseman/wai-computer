"""Integration tests for the ElevenLabs custom-LLM bridge routes."""

import json
import uuid
from typing import Any

from app.core.companion import DoneEvent, TokenEvent
from app.core.voice_session import (
    create_voice_session_token,
    decode_voice_session_token,
)


async def _fake_run_turn(db, user_id, conversation_id, user_text, **kwargs):
    # Voice runs the brain read-only; assert that here too.
    assert kwargs.get("enable_actions") is False
    yield TokenEvent(text="Hello ")
    yield TokenEvent(text="world.")
    yield DoneEvent()


def _sse_payloads(body: str) -> list[Any]:
    out: list[Any] = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block.startswith("data: "):
            continue
        data = block[len("data: ") :]
        out.append(data if data == "[DONE]" else json.loads(data))
    return out


async def test_session_mints_token_and_deepgram_settings(client, auth_headers):
    res = await client.post("/api/voice/llm/session", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["expires_in_seconds"] == 1800
    claims = decode_voice_session_token(body["token"])
    assert str(claims.conversation_id) == body["conversation_id"]
    # The Deepgram Voice Agent settings point think at our bridge with the token.
    think = body["voice_agent_settings"]["agent"]["think"]
    assert think["provider"] == {"type": "open_ai"}
    assert think["endpoint"]["url"].endswith("/api/voice/llm/chat/completions")
    assert think["endpoint"]["headers"]["authorization"] == f"Bearer {body['token']}"
    assert body["voice_agent_settings"]["agent"]["listen"]["provider"]["model"] == "nova-3"


async def test_session_russian_without_voice_is_refused(client, auth_headers):
    # Deepgram Aura can't speak Russian; surface it rather than a wrong voice.
    res = await client.post(
        "/api/voice/llm/session?language=ru", headers=auth_headers
    )
    assert res.status_code == 400, res.text


async def test_chat_completions_streams_brain_answer(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.voice.run_turn", _fake_run_turn)
    token, _ = create_voice_session_token(
        user_id=uuid.uuid4(), conversation_id=uuid.uuid4()
    )
    res = await client.post(
        "/api/voice/llm/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={"model": "wai", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert res.status_code == 200, res.text
    payloads = _sse_payloads(res.text)
    assert payloads[0]["choices"][0]["delta"] == {"role": "assistant"}
    contents = [
        p["choices"][0]["delta"]["content"]
        for p in payloads
        if isinstance(p, dict) and "content" in p["choices"][0]["delta"]
    ]
    assert contents == ["Hello ", "world."]
    assert payloads[-1] == "[DONE]"


async def test_chat_completions_requires_a_token(client):
    res = await client.post(
        "/api/voice/llm/chat/completions",
        json={"model": "wai", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert res.status_code == 401, res.text


async def test_chat_completions_rejects_invalid_token(client):
    res = await client.post(
        "/api/voice/llm/chat/completions",
        headers={"Authorization": "Bearer not-a-real-token"},
        json={"model": "wai", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert res.status_code == 401, res.text


async def test_chat_completions_no_user_message_yields_empty_completion(
    client, monkeypatch
):
    # run_turn must not even be called when there is no user turn.
    async def _boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("run_turn should not run without a user message")
        yield

    monkeypatch.setattr("app.api.routes.voice.run_turn", _boom)
    token, _ = create_voice_session_token(
        user_id=uuid.uuid4(), conversation_id=uuid.uuid4()
    )
    res = await client.post(
        "/api/voice/llm/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={"model": "wai", "messages": [{"role": "assistant", "content": "hi"}]},
    )
    assert res.status_code == 200, res.text
    payloads = _sse_payloads(res.text)
    assert payloads[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert payloads[-1] == "[DONE]"
    # No content chunks for an empty completion.
    assert not [
        p
        for p in payloads
        if isinstance(p, dict) and p["choices"][0]["delta"].get("content")
    ]
