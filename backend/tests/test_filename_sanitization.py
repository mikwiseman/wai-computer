"""Tests for filename sanitization and Content-Disposition header building."""

import pytest

from app.api.routes.recordings import _content_disposition, _sanitize_filename


class TestSanitizeFilename:
    """Tests for _sanitize_filename."""

    def test_plain_ascii_title(self):
        assert _sanitize_filename("Team Standup") == "Team_Standup"

    def test_none_title_returns_default(self):
        assert _sanitize_filename(None) == "recording"

    def test_empty_string_returns_default(self):
        assert _sanitize_filename("") == "recording"

    def test_whitespace_only_returns_default(self):
        assert _sanitize_filename("   ") == "recording"

    def test_quotes_are_stripped(self):
        assert _sanitize_filename('He said "hello"') == "He_said_hello"

    def test_single_quotes_are_preserved(self):
        # Single quotes are safe in filenames
        result = _sanitize_filename("Mike's Recording")
        assert result == "Mike's_Recording"

    def test_slashes_are_stripped(self):
        assert _sanitize_filename("notes/2024") == "notes2024"

    def test_backslashes_are_stripped(self):
        assert _sanitize_filename("C:\\Users\\file") == "CUsersfile"

    def test_colons_are_stripped(self):
        assert _sanitize_filename("Meeting: Monday") == "Meeting_Monday"

    def test_angle_brackets_stripped(self):
        assert _sanitize_filename("report <final>") == "report_final"

    def test_pipe_stripped(self):
        assert _sanitize_filename("A | B") == "A__B"

    def test_asterisk_stripped(self):
        assert _sanitize_filename("important*") == "important"

    def test_question_mark_stripped(self):
        assert _sanitize_filename("what?") == "what"

    def test_control_characters_stripped(self):
        assert _sanitize_filename("test\x00\x01\x1f") == "test"

    def test_unicode_letters_preserved(self):
        assert _sanitize_filename("café résumé") == "café_résumé"

    def test_cjk_characters_preserved(self):
        assert _sanitize_filename("会議ノート") == "会議ノート"

    def test_emoji_preserved(self):
        # Emojis are valid in filenames on modern OSes
        result = _sanitize_filename("Notes 📝")
        assert "Notes" in result
        assert "📝" in result

    def test_mixed_unicode_and_unsafe_chars(self):
        result = _sanitize_filename('Réunion "lundi" 15:00')
        assert result == "Réunion_lundi_1500"

    def test_truncated_to_100_chars(self):
        long_title = "a" * 200
        assert len(_sanitize_filename(long_title)) == 100

    def test_leading_trailing_spaces_stripped(self):
        assert _sanitize_filename("  hello  ") == "hello"

    def test_hyphens_and_underscores_preserved(self):
        assert _sanitize_filename("my-file_name") == "my-file_name"


class TestContentDisposition:
    """Tests for _content_disposition."""

    def test_ascii_filename(self):
        result = _content_disposition("Team_Standup.md")
        assert 'filename="Team_Standup.md"' in result
        assert "filename*=UTF-8''Team_Standup.md" in result

    def test_quotes_in_filename_are_escaped(self):
        result = _content_disposition('He_said_"hello".md')
        # The ASCII fallback must escape the quotes
        assert 'filename="He_said_\\"hello\\".md"' in result

    def test_non_ascii_filename_uses_utf8_encoding(self):
        result = _content_disposition("café_résumé.md")
        # ASCII fallback replaces non-ASCII with ?
        assert 'filename="caf?_r?sum?.md"' in result
        # UTF-8 version must percent-encode
        assert "filename*=UTF-8''" in result
        assert "caf%C3%A9" in result
        assert "r%C3%A9sum%C3%A9" in result

    def test_cjk_filename(self):
        result = _content_disposition("会議ノート.md")
        # ASCII fallback replaces CJK with ?
        assert "filename=" in result
        # UTF-8 version must percent-encode
        assert "filename*=UTF-8''" in result
        # The CJK chars should be percent-encoded, not literal
        assert "%E4%BC%9A%E8%AD%B0" in result

    def test_starts_with_attachment(self):
        result = _content_disposition("test.md")
        assert result.startswith("attachment; ")

    def test_both_filename_params_present(self):
        result = _content_disposition("test.md")
        assert "filename=" in result
        assert "filename*=" in result


class TestSanitizeAndDispositionIntegration:
    """Integration tests: sanitize -> disposition pipeline."""

    @pytest.mark.parametrize(
        "title,ext",
        [
            ("Normal Title", "md"),
            ('Title with "quotes"', "txt"),
            ("日本語タイトル", "srt"),
            ("café résumé", "md"),
            (None, "md"),
            ("", "txt"),
            ("a/b\\c:d*e?f", "srt"),
        ],
    )
    def test_pipeline_produces_valid_header(self, title: str | None, ext: str):
        filename = f"{_sanitize_filename(title)}.{ext}"
        header = _content_disposition(filename)
        # Must start with attachment
        assert header.startswith("attachment; ")
        # Must contain both filename and filename*
        assert "filename=" in header
        assert "filename*=UTF-8''" in header
        # The ASCII filename= value must be properly quoted (no unescaped quotes)
        # Extract the ASCII filename value between the first pair of quotes
        import re

        match = re.search(r'filename="((?:[^"\\]|\\.)*)"', header)
        assert match is not None, f"Could not parse filename from: {header}"
