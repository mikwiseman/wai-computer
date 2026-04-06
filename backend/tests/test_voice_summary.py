"""Tests for voice summary module."""

from unittest.mock import AsyncMock, patch

from app.services.agent.voice_summary import estimate_voice_duration_text, summarize_voice


class TestEstimateVoiceDuration:
    def test_none_duration(self):
        assert estimate_voice_duration_text(None) == ""

    def test_zero_duration(self):
        assert estimate_voice_duration_text(0) == ""

    def test_seconds_only(self):
        assert estimate_voice_duration_text(45) == "45s"

    def test_exact_minutes(self):
        assert estimate_voice_duration_text(120) == "2m"

    def test_minutes_and_seconds(self):
        assert estimate_voice_duration_text(90) == "1m30s"

    def test_large_duration(self):
        assert estimate_voice_duration_text(3661) == "61m1s"


class TestSummarizeVoice:
    async def test_empty_transcript(self):
        result = await summarize_voice("")
        assert "Could not transcribe" in result

    async def test_whitespace_transcript(self):
        result = await summarize_voice("   ")
        assert "Could not transcribe" in result

    async def test_short_transcript_returns_directly(self):
        result = await summarize_voice("Hello world, testing")
        assert "Transcript" in result
        assert "Hello world, testing" in result

    @patch("app.services.agent.voice_summary.get_settings")
    @patch("app.services.agent.voice_summary.anthropic.AsyncAnthropic")
    async def test_long_transcript_calls_llm(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value.anthropic_api_key = "test-key"

        mock_client = AsyncMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = AsyncMock(
            content=[AsyncMock(text="Summary: A discussion about project planning.")]
        )

        long_transcript = " ".join(["word"] * 30)
        result = await summarize_voice(long_transcript)
        assert "Transcript" in result
        assert "Summary: A discussion" in result

    @patch("app.services.agent.voice_summary.get_settings")
    @patch("app.services.agent.voice_summary.anthropic.AsyncAnthropic")
    async def test_long_transcript_truncated_in_display(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value.anthropic_api_key = "test-key"

        mock_client = AsyncMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = AsyncMock(
            content=[AsyncMock(text="Summary text")]
        )

        # 600-char transcript should be truncated in display
        long_transcript = " ".join(["longword"] * 100)
        result = await summarize_voice(long_transcript)
        assert "first 500 chars" in result

    @patch("app.services.agent.voice_summary.get_settings")
    async def test_no_api_key_skips_llm(self, mock_settings):
        mock_settings.return_value.anthropic_api_key = ""

        long_transcript = " ".join(["word"] * 30)
        result = await summarize_voice(long_transcript)
        assert "Transcript" in result

    @patch("app.services.agent.voice_summary.get_settings")
    @patch("app.services.agent.voice_summary.anthropic.AsyncAnthropic")
    async def test_llm_failure_still_returns_transcript(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value.anthropic_api_key = "test-key"

        mock_client = AsyncMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("API error")

        long_transcript = " ".join(["word"] * 30)
        result = await summarize_voice(long_transcript)
        assert "Transcript" in result

    @patch("app.services.agent.voice_summary.get_settings")
    @patch("app.services.agent.voice_summary.anthropic.AsyncAnthropic")
    async def test_entities_extracted(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value.anthropic_api_key = ""

        transcript = "John and Sarah discussed the $500 budget for the project last Monday"
        result = await summarize_voice(transcript)
        assert "Transcript" in result

    @patch("app.services.agent.voice_summary.get_settings")
    @patch("app.services.agent.voice_summary.anthropic.AsyncAnthropic")
    async def test_commitments_detected(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value.anthropic_api_key = ""

        transcript = " ".join(["word"] * 15) + " I promised to send the report by Friday"
        result = await summarize_voice(transcript, user_name="Mik")
        assert "Transcript" in result
