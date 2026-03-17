"""Tests for recording route helper functions."""

import pytest

from app.api.routes.recordings import (
    _extension_from_upload,
    _format_duration_mmss,
    _format_timestamp_short,
    _format_timestamp_srt,
    _normalize_failure_message,
    _sanitize_filename,
    _upload_limit_message,
)


class TestFormatDurationMmss:
    """Tests for _format_duration_mmss."""

    def test_none_returns_zero(self):
        assert _format_duration_mmss(None) == "0:00"

    def test_negative_returns_zero(self):
        assert _format_duration_mmss(-5) == "0:00"

    def test_zero_seconds(self):
        assert _format_duration_mmss(0) == "0:00"

    def test_under_minute(self):
        assert _format_duration_mmss(45) == "0:45"

    def test_exact_minute(self):
        assert _format_duration_mmss(60) == "1:00"

    def test_minutes_and_seconds(self):
        assert _format_duration_mmss(125) == "2:05"

    def test_one_hour_exactly(self):
        assert _format_duration_mmss(3600) == "1:00:00"

    def test_hours_minutes_seconds(self):
        assert _format_duration_mmss(3661) == "1:01:01"

    def test_large_duration(self):
        assert _format_duration_mmss(7384) == "2:03:04"


class TestFormatTimestampShort:
    """Tests for _format_timestamp_short."""

    def test_none_returns_empty(self):
        assert _format_timestamp_short(None) == ""

    def test_zero_ms(self):
        assert _format_timestamp_short(0) == "0:00"

    def test_exact_minute(self):
        assert _format_timestamp_short(60000) == "1:00"

    def test_ms_with_seconds(self):
        assert _format_timestamp_short(95000) == "1:35"


class TestFormatTimestampSrt:
    """Tests for _format_timestamp_srt."""

    def test_none_returns_zero(self):
        assert _format_timestamp_srt(None) == "00:00:00,000"

    def test_zero(self):
        assert _format_timestamp_srt(0) == "00:00:00,000"

    def test_milliseconds_only(self):
        assert _format_timestamp_srt(500) == "00:00:00,500"

    def test_seconds_and_millis(self):
        assert _format_timestamp_srt(5123) == "00:00:05,123"

    def test_minutes(self):
        assert _format_timestamp_srt(65000) == "00:01:05,000"

    def test_hours(self):
        assert _format_timestamp_srt(3661500) == "01:01:01,500"


class TestSanitizeFilename:
    """Tests for _sanitize_filename."""

    def test_none_returns_recording(self):
        assert _sanitize_filename(None) == "recording"

    def test_empty_string_returns_recording(self):
        assert _sanitize_filename("") == "recording"

    def test_simple_title(self):
        assert _sanitize_filename("My Meeting") == "My_Meeting"

    def test_special_characters_removed(self):
        assert _sanitize_filename("Meeting: Q1 Review <2024>") == "Meeting_Q1_Review_2024"

    def test_long_title_truncated(self):
        long_title = "A" * 200
        result = _sanitize_filename(long_title)
        assert len(result) <= 100

    def test_preserves_hyphens_underscores(self):
        assert _sanitize_filename("my-meeting_notes") == "my-meeting_notes"

    def test_only_special_chars_preserves_non_fs_chars(self):
        # !@# are not filesystem-unsafe, so they're preserved
        assert _sanitize_filename("!!!@@@###") == "!!!@@@###"

    def test_only_fs_unsafe_chars_returns_recording(self):
        # All filesystem-unsafe chars stripped → empty → falls back to "recording"
        assert _sanitize_filename('/:*?"<>|') == "recording"


class TestNormalizeFailureMessage:
    """Tests for _normalize_failure_message."""

    def test_string_input(self):
        assert _normalize_failure_message("Some error", "fallback") == "Some error"

    def test_exception_input(self):
        err = ValueError("Bad value")
        assert _normalize_failure_message(err, "fallback") == "Bad value"

    def test_empty_string_returns_fallback(self):
        assert _normalize_failure_message("", "fallback") == "fallback"

    def test_whitespace_returns_fallback(self):
        assert _normalize_failure_message("   ", "fallback") == "fallback"

    def test_long_message_truncated(self):
        long_msg = "x" * 1000
        result = _normalize_failure_message(long_msg, "fallback")
        assert len(result) == 500


class TestExtensionFromUpload:
    """Tests for _extension_from_upload."""

    def test_known_extension(self):
        assert _extension_from_upload("audio.mp3", "audio/mpeg") == "mp3"

    def test_wav_extension(self):
        assert _extension_from_upload("audio.wav", "audio/wav") == "wav"

    def test_flac_extension(self):
        assert _extension_from_upload("audio.flac", "audio/flac") == "flac"

    def test_falls_back_to_content_type(self):
        assert _extension_from_upload("audiofile", "audio/mpeg") == "mp3"

    def test_unknown_type_raises(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _extension_from_upload("file.xyz", "application/octet-stream")
        assert exc_info.value.status_code == 415

    def test_case_insensitive(self):
        assert _extension_from_upload("audio.MP3", "audio/mpeg") == "mp3"


class TestUploadLimitMessage:
    """Tests for _upload_limit_message."""

    def test_returns_readable_message(self):
        msg = _upload_limit_message()
        assert "Maximum size" in msg
        assert "MB" in msg
