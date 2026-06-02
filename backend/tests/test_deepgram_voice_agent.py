"""Unit tests for the Deepgram Voice Agent Settings builder."""

import pytest

from app.core.deepgram_voice_agent import (
    UnsupportedVoiceLanguageError,
    VoiceAgentTTS,
    build_voice_agent_settings,
    default_tts_for_language,
)

BRIDGE = "https://wai.computer/api/voice/llm/chat/completions"


def test_think_points_at_our_bridge_with_bearer_token():
    settings = build_voice_agent_settings(bridge_url=BRIDGE, voice_token="tok-123")
    think = settings["agent"]["think"]
    assert think["provider"] == {"type": "open_ai"}
    assert think["endpoint"]["url"] == BRIDGE
    assert think["endpoint"]["headers"]["authorization"] == "Bearer tok-123"


def test_listen_is_deepgram_nova3_in_requested_language():
    settings = build_voice_agent_settings(
        bridge_url=BRIDGE, voice_token="t", language="en"
    )
    listen = settings["agent"]["listen"]["provider"]
    assert listen["type"] == "deepgram"
    assert listen["model"] == "nova-3"
    assert listen["language"] == "en"


def test_english_defaults_to_deepgram_aura():
    settings = build_voice_agent_settings(bridge_url=BRIDGE, voice_token="t")
    speak = settings["agent"]["speak"]["provider"]
    assert speak["type"] == "deepgram"
    assert speak["model"] == "aura-2-thalia-en"


def test_russian_without_explicit_voice_is_refused_not_silently_wrong():
    # Aura can't speak Russian — surface it, never emit a wrong-language voice.
    with pytest.raises(UnsupportedVoiceLanguageError):
        build_voice_agent_settings(bridge_url=BRIDGE, voice_token="t", language="ru")
    with pytest.raises(UnsupportedVoiceLanguageError):
        default_tts_for_language("ru")


def test_russian_with_explicit_elevenlabs_voice_is_used():
    settings = build_voice_agent_settings(
        bridge_url=BRIDGE,
        voice_token="t",
        language="ru",
        tts=VoiceAgentTTS(provider="eleven_labs", model_id="voice-xyz", language="ru"),
    )
    speak = settings["agent"]["speak"]["provider"]
    assert speak["type"] == "eleven_labs"
    assert speak["model_id"] == "voice-xyz"
    assert speak["language"] == "ru"
    # STT still runs Deepgram nova-3 in Russian — only the voice is non-Deepgram.
    assert settings["agent"]["listen"]["provider"]["model"] == "nova-3"


def test_audio_io_and_greeting():
    settings = build_voice_agent_settings(
        bridge_url=BRIDGE, voice_token="t", greeting="Hi there"
    )
    assert settings["type"] == "Settings"
    assert settings["audio"]["input"]["sample_rate"] == 16000
    assert settings["audio"]["output"]["sample_rate"] == 24000
    assert settings["agent"]["greeting"] == "Hi there"
