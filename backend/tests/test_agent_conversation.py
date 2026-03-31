"""Tests for conversation history management."""

from uuid import uuid4

from app.services.agent.conversation import (
    add_message,
    clear_history,
    get_history,
    get_history_for_agent,
)


class TestConversation:
    def test_add_and_get(self):
        uid = uuid4()
        clear_history(uid)
        add_message(uid, "user", "hello")
        add_message(uid, "assistant", "hi")
        history = get_history(uid)
        assert len(history) == 2
        assert history[0].role == "user"
        assert history[0].content == "hello"
        assert history[1].role == "assistant"
        clear_history(uid)

    def test_clear_history(self):
        uid = uuid4()
        add_message(uid, "user", "test")
        clear_history(uid)
        assert len(get_history(uid)) == 0

    def test_max_history_trimming(self):
        uid = uuid4()
        clear_history(uid)
        for i in range(30):
            add_message(uid, "user", f"msg {i}")
        history = get_history(uid)
        assert len(history) <= 20
        clear_history(uid)

    def test_get_history_for_agent(self):
        uid = uuid4()
        clear_history(uid)
        add_message(uid, "user", "question")
        add_message(uid, "assistant", "answer")
        agent_history = get_history_for_agent(uid)
        assert isinstance(agent_history, list)
        assert len(agent_history) == 2
        assert agent_history[0]["role"] == "user"
        assert agent_history[0]["content"] == "question"
        clear_history(uid)

    def test_different_users_isolated(self):
        uid1, uid2 = uuid4(), uuid4()
        clear_history(uid1)
        clear_history(uid2)
        add_message(uid1, "user", "for user 1")
        add_message(uid2, "user", "for user 2")
        assert len(get_history(uid1)) == 1
        assert len(get_history(uid2)) == 1
        assert get_history(uid1)[0].content == "for user 1"
        assert get_history(uid2)[0].content == "for user 2"
        clear_history(uid1)
        clear_history(uid2)

    def test_empty_user(self):
        uid = uuid4()
        assert len(get_history(uid)) == 0
        assert get_history_for_agent(uid) == []
