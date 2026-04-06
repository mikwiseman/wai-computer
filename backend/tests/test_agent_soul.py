"""Tests for soul prompt assembly."""

from app.services.agent.soul import build_soul_prompt


class TestBuildSoulPrompt:
    def test_basic_prompt_has_identity(self):
        prompt = build_soul_prompt()
        assert "Wai" in prompt
        assert "[Identity]" in prompt
        assert "[Rules]" in prompt
        assert "[Context]" in prompt
        assert "[Available actions]" in prompt

    def test_user_name_included(self):
        prompt = build_soul_prompt(user_name="Mik")
        assert "for Mik" in prompt

    def test_no_user_name(self):
        prompt = build_soul_prompt(user_name=None)
        assert "for None" not in prompt

    def test_russian_language(self):
        prompt = build_soul_prompt(user_language="ru")
        assert "русском" in prompt

    def test_english_fallback(self):
        prompt = build_soul_prompt(user_language="en")
        assert "same language" in prompt

    def test_unknown_language_uses_default(self):
        prompt = build_soul_prompt(user_language="xx")
        assert "same language" in prompt

    def test_connected_services_listed(self):
        prompt = build_soul_prompt(connected_services=["telegram", "email"])
        assert "telegram" in prompt
        assert "email" in prompt

    def test_no_connected_services(self):
        prompt = build_soul_prompt(connected_services=[])
        assert "none yet" in prompt

    def test_identity_memories_section(self):
        prompt = build_soul_prompt(identity_memories=["Likes coffee", "Works at WaiWai"])
        assert "[About the user]" in prompt
        assert "Likes coffee" in prompt
        assert "Works at WaiWai" in prompt

    def test_working_context_section(self):
        prompt = build_soul_prompt(working_context=["Working on sidebar refactor"])
        assert "[Current context]" in prompt
        assert "sidebar refactor" in prompt

    def test_recalled_memories_section(self):
        prompt = build_soul_prompt(recalled_memories=["Previous meeting about budgets"])
        assert "[Recalled memories]" in prompt
        assert "budgets" in prompt

    def test_all_optional_sections(self):
        prompt = build_soul_prompt(
            user_name="Test",
            user_language="es",
            timezone="America/New_York",
            connected_services=["slack"],
            identity_memories=["Developer"],
            working_context=["Sprint review"],
            recalled_memories=["Last standup notes"],
        )
        assert "[About the user]" in prompt
        assert "[Current context]" in prompt
        assert "[Recalled memories]" in prompt
        assert "español" in prompt
        assert "America/New_York" in prompt

    def test_no_optional_sections_when_empty(self):
        prompt = build_soul_prompt()
        assert "[About the user]" not in prompt
        assert "[Current context]" not in prompt
        assert "[Recalled memories]" not in prompt

    def test_tools_listed(self):
        prompt = build_soul_prompt()
        assert "search_recordings" in prompt
        assert "track_commitment" in prompt
        assert "search_web" in prompt
