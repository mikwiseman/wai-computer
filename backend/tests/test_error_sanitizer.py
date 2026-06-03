"""Tests for :mod:`app.core.error_sanitizer`."""

from __future__ import annotations

import pytest

from app.core.error_sanitizer import (
    GENERIC_FAILURE_MESSAGE,
    sanitize_failure_message,
)


class TestSanitizeFailureMessage:
    """``sanitize_failure_message`` strips paths, tracebacks, and PII."""

    def test_none_returns_none(self) -> None:
        assert sanitize_failure_message(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert sanitize_failure_message("") is None

    def test_whitespace_returns_none(self) -> None:
        assert sanitize_failure_message("   \n\t") is None

    @pytest.mark.parametrize(
        "leaked",
        [
            "[Errno 13] Permission denied: '/var/lib/waisay/uploads/9b4c62b8'",
            "/var/lib/waisay/uploads/foo",
            "/Users/mik/Documents/recording.wav",
            "/tmp/processing-9b4c62b8.wav",
            "/opt/waicomputer/storage/error",
            "[Errno 2] No such file or directory: '/tmp/x'",
            (
                "Traceback (most recent call last):\n"
                '  File "/app/main.py", line 42, in process\n'
                "    raise IOError"
            ),
            "<class 'sqlalchemy.exc.IntegrityError'>",
            "IOError: cannot open file",
            "C:\\\\Users\\\\mik\\\\recordings\\\\x.wav",
        ],
    )
    def test_leaked_os_string_replaced_with_generic(self, leaked: str) -> None:
        assert sanitize_failure_message(leaked) == GENERIC_FAILURE_MESSAGE

    @pytest.mark.parametrize(
        "domain_message",
        [
            "We could not detect clear speech in this recording.",
            "Мы не обнаружили разборчивой речи в этой записи.",
            "Recording processing timed out.",
            "Recording processing failed after retryable provider errors.",
            "Transcription quota exceeded",
            "Audio too short",
            "Uploaded audio file was missing before processing.",
            "Unsupported file type '.zip'. Allowed: m4a, mp3, wav",
            "Failed to start recording processing",
            "Imported audio processing failed",
            "Файл пустой.",
        ],
    )
    def test_domain_messages_pass_through(self, domain_message: str) -> None:
        assert sanitize_failure_message(domain_message) == domain_message

    def test_long_message_truncated_to_500(self) -> None:
        long_message = "x" * 1000
        sanitized = sanitize_failure_message(long_message)
        assert sanitized is not None
        assert len(sanitized) == 500

    def test_strips_surrounding_whitespace(self) -> None:
        assert sanitize_failure_message("  Audio too short  ") == "Audio too short"

    def test_errno_inside_a_larger_message_still_collapses(self) -> None:
        message = (
            "Processing failed: [Errno 13] Permission denied: "
            "'/var/lib/waisay/uploads/9b4c62b8'"
        )
        assert sanitize_failure_message(message) == GENERIC_FAILURE_MESSAGE


class TestFallbackSpeakerDisplayName:
    """``fallback_speaker_display_name`` normalizes raw diarization labels."""

    def test_speaker_zero_becomes_speaker_one(self) -> None:
        from app.core.speaker_labels import fallback_speaker_display_name

        assert fallback_speaker_display_name("speaker_0") == "Speaker 1"

    def test_speaker_one_becomes_speaker_two(self) -> None:
        from app.core.speaker_labels import fallback_speaker_display_name

        assert fallback_speaker_display_name("speaker_1") == "Speaker 2"

    def test_none_returns_none(self) -> None:
        from app.core.speaker_labels import fallback_speaker_display_name

        assert fallback_speaker_display_name(None) is None

    def test_empty_returns_none(self) -> None:
        from app.core.speaker_labels import fallback_speaker_display_name

        assert fallback_speaker_display_name("") is None

    def test_unknown_label_returns_none(self) -> None:
        from app.core.speaker_labels import fallback_speaker_display_name

        # The frontend handles ``speaker_?`` and similar placeholders itself.
        assert fallback_speaker_display_name("speaker_?") is None
        assert fallback_speaker_display_name("Alice") is None

    def test_speaker_with_space_supported(self) -> None:
        from app.core.speaker_labels import fallback_speaker_display_name

        assert fallback_speaker_display_name("Speaker 3") == "Speaker 4"
