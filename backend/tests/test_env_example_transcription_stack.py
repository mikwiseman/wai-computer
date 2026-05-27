from pathlib import Path


def test_env_example_exposes_only_current_stt_stack():
    env_example = Path(__file__).resolve().parents[1] / ".env.example"
    content = env_example.read_text()

    assert "OPENAI_API_KEY=" in content
    assert "ELEVENLABS_SPEECH_TO_TEXT_MODEL=scribe_v2" in content

    removed_stt_entries = (
        "ELEVENLABS_" + "REALTIME_SPEECH_TO_TEXT_MODEL",
        "IN" + "WORLD_API_KEY",
        "DEEP" + "GRAM_API_KEY",
        "SON" + "IOX_API_KEY",
        "scribe_v2" + "_realtime",
    )
    for entry in removed_stt_entries:
        assert entry not in content
