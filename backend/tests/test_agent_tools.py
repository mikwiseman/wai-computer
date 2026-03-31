"""Tests for individual agent tool implementations."""


from app.services.agent.conversation import add_message, clear_history, get_history
from app.services.agent.entities import EntityType, extract_entities_fast
from app.services.agent.language import detect_language
from app.services.agent.rate_limit import check_rate_limit, clear_rate_limits


class TestEntityExtraction:
    def test_extract_person(self):
        entities = extract_entities_fast("I met with Alice about the project")
        person_entities = [e for e in entities if e.type == EntityType.PERSON]
        assert len(person_entities) >= 1

    def test_extract_amount(self):
        entities = extract_entities_fast("The budget is $5000 for Q1")
        amount_entities = [e for e in entities if e.type == EntityType.AMOUNT]
        assert len(amount_entities) >= 1

    def test_extract_decision(self):
        entities = extract_entities_fast("We decided to launch the MVP next month")
        decision_entities = [e for e in entities if e.type == EntityType.DECISION]
        assert len(decision_entities) >= 1

    def test_empty_text(self):
        entities = extract_entities_fast("")
        assert entities == []


class TestLanguageDetection:
    def test_english(self):
        assert detect_language("Hello, how are you?") == "en"

    def test_russian(self):
        assert detect_language("Привет, как дела?") == "ru"

    def test_ukrainian(self):
        assert detect_language("Привіт, як справи?") == "uk"

    def test_chinese(self):
        assert detect_language("你好世界") == "zh"

    def test_japanese(self):
        assert detect_language("こんにちは世界") == "ja"

    def test_korean(self):
        assert detect_language("안녕하세요") == "ko"

    def test_arabic(self):
        assert detect_language("مرحبا بالعالم") == "ar"

    def test_short_text_defaults_english(self):
        result = detect_language("hi")
        assert result in ("en", "unknown")


class TestConversation:
    def test_add_and_get(self):
        from uuid import uuid4

        user_id = uuid4()
        clear_history(user_id)
        add_message(user_id, "user", "hello")
        add_message(user_id, "assistant", "hi there")

        history = get_history(user_id)
        assert len(history) == 2
        assert history[0].role == "user"
        assert history[1].role == "assistant"
        clear_history(user_id)

    def test_max_history_trim(self):
        from uuid import uuid4

        user_id = uuid4()
        clear_history(user_id)
        for i in range(25):
            add_message(user_id, "user", f"message {i}")

        history = get_history(user_id)
        assert len(history) <= 20
        clear_history(user_id)


class TestRateLimit:
    def test_allows_under_limit(self):
        clear_rate_limits()
        assert check_rate_limit(12345) is True

    def test_blocks_over_limit(self):
        clear_rate_limits()
        for _ in range(35):
            check_rate_limit(99999)
        assert check_rate_limit(99999) is False
        clear_rate_limits()

    def test_different_users_independent(self):
        clear_rate_limits()
        for _ in range(35):
            check_rate_limit(11111)
        assert check_rate_limit(22222) is True
        clear_rate_limits()
