"""Tests for language detection module."""

from app.services.agent.language import detect_language


class TestLanguageDetection:
    def test_english(self):
        assert detect_language("Hello, how are you doing today?") == "en"

    def test_russian(self):
        assert detect_language("Привет, как дела? Всё хорошо.") == "ru"

    def test_ukrainian(self):
        assert detect_language("Привіт, як справи? Все добре.") == "uk"

    def test_chinese(self):
        assert detect_language("你好世界，这是一个测试") == "zh"

    def test_japanese(self):
        assert detect_language("こんにちは世界、これはテストです") == "ja"

    def test_korean(self):
        assert detect_language("안녕하세요 세계입니다") == "ko"

    def test_arabic(self):
        assert detect_language("مرحبا بالعالم هذا اختبار") == "ar"

    def test_mixed_defaults_to_dominant(self):
        result = detect_language("Привет hello мир world")
        assert result in ("ru", "en")

    def test_empty_string(self):
        result = detect_language("")
        assert isinstance(result, str)

    def test_short_text(self):
        result = detect_language("ok")
        assert isinstance(result, str) and len(result) == 2

    def test_numbers_only(self):
        result = detect_language("12345")
        assert isinstance(result, str)
