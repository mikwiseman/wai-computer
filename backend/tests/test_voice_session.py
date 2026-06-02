"""Unit tests for the per-session voice token (mint + verify, fail-closed)."""

import uuid

import pytest
from jose import jwt

from app.config import get_settings
from app.core.voice_session import (
    VOICE_LLM_AUDIENCE,
    VoiceSessionClaims,
    VoiceTokenError,
    create_voice_session_token,
    decode_voice_session_token,
)


def test_mint_then_verify_roundtrip():
    user_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    token, ttl = create_voice_session_token(
        user_id=user_id, conversation_id=conversation_id
    )
    assert ttl == 1800
    claims = decode_voice_session_token(token)
    assert claims == VoiceSessionClaims(
        user_id=user_id, conversation_id=conversation_id
    )


def test_expired_token_is_rejected():
    token, _ = create_voice_session_token(
        user_id=uuid.uuid4(), conversation_id=uuid.uuid4(), ttl_seconds=-1
    )
    with pytest.raises(VoiceTokenError):
        decode_voice_session_token(token)


def test_wrong_audience_is_rejected():
    # A token minted for a different audience must not pass as a voice token.
    settings = get_settings()
    bad = jwt.encode(
        {"sub": str(uuid.uuid4()), "aud": "some-other-aud", "cid": str(uuid.uuid4())},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(VoiceTokenError):
        decode_voice_session_token(bad)


def test_tampered_token_is_rejected():
    token, _ = create_voice_session_token(
        user_id=uuid.uuid4(), conversation_id=uuid.uuid4()
    )
    tampered = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")
    with pytest.raises(VoiceTokenError):
        decode_voice_session_token(tampered)


def test_malformed_subject_is_rejected():
    settings = get_settings()
    token = jwt.encode(
        {"sub": "not-a-uuid", "aud": VOICE_LLM_AUDIENCE, "cid": str(uuid.uuid4())},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(VoiceTokenError):
        decode_voice_session_token(token)


def test_missing_subject_is_rejected():
    settings = get_settings()
    token = jwt.encode(
        {"aud": VOICE_LLM_AUDIENCE, "cid": str(uuid.uuid4())},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(VoiceTokenError):
        decode_voice_session_token(token)


def test_missing_conversation_is_rejected():
    settings = get_settings()
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "aud": VOICE_LLM_AUDIENCE},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(VoiceTokenError):
        decode_voice_session_token(token)
