"""Tests for agent intent router — pattern matching and classification."""

import pytest

from app.services.agent.router import Intent, classify_intent, get_model_for_intent


class TestPatternMatching:
    """Test fast pattern matching (no LLM calls)."""

    async def test_search_intent_english(self):
        assert await classify_intent("find what Alex said about pricing") == Intent.SEARCH

    async def test_search_intent_what_did(self):
        assert await classify_intent("what did we discuss yesterday?") == Intent.SEARCH

    async def test_search_intent_russian(self):
        assert await classify_intent("найди обсуждение про бюджет") == Intent.SEARCH

    async def test_search_intent_who_said(self):
        assert await classify_intent("who said we need to launch by Friday?") == Intent.SEARCH

    async def test_digest_intent(self):
        assert await classify_intent("what happened this week?") == Intent.DIGEST

    async def test_digest_intent_russian(self):
        assert await classify_intent("дайджест за вчера") == Intent.DIGEST

    async def test_build_intent(self):
        assert await classify_intent("build a landing page for our product") == Intent.BUILD

    async def test_build_intent_tracker(self):
        assert await classify_intent("create a habit tracker") == Intent.BUILD

    async def test_build_intent_russian(self):
        assert await classify_intent("создай сайт для продукта") == Intent.BUILD

    async def test_edit_intent(self):
        assert await classify_intent("change the button color to blue") == Intent.EDIT

    async def test_edit_intent_russian(self):
        assert await classify_intent("измени заголовок на главной") == Intent.EDIT

    async def test_action_intent(self):
        assert await classify_intent("send email to the team") == Intent.ACTION

    async def test_commitment_routes_to_search(self):
        assert await classify_intent("what did I promise Alex?") == Intent.SEARCH

    async def test_voice_summary(self):
        assert await classify_intent("hello", has_voice=True) == Intent.VOICE_SUMMARY

    async def test_voice_overrides_text_intent(self):
        assert await classify_intent("find pricing info", has_voice=True) == Intent.VOICE_SUMMARY


class TestModelRouting:
    """Test model selection for intents."""

    def test_build_uses_sonnet(self):
        model = get_model_for_intent(Intent.BUILD)
        assert "sonnet" in model.lower() or "claude" in model.lower()

    def test_chat_uses_agent_model(self):
        model = get_model_for_intent(Intent.CHAT)
        assert model  # Should return a valid model name

    def test_search_uses_agent_model(self):
        model = get_model_for_intent(Intent.SEARCH)
        assert model
