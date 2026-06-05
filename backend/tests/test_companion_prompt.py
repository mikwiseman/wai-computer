"""Agent-aware system prompt.

Read-only turns must stay byte-for-byte identical (prompt-cache preserving);
action-capable turns gain the capability identity + <action_policy>. A final
test pins the contract the policy promises: reads/web_search NEVER enter the
approval gate, but the action hands always do.
"""

from app.core.companion import (
    _ACTION_POLICY_SECTION,
    _IDENTITY_SECTION,
    _IDENTITY_SECTION_WITH_ACTIONS,
    system_prompt_for,
)
from app.core.tool_safety import is_mutating_tool_call


def test_read_only_prompt_keeps_original_identity_and_no_action_policy():
    prompt = system_prompt_for()
    assert _IDENTITY_SECTION in prompt
    assert _IDENTITY_SECTION_WITH_ACTIONS not in prompt
    assert "<action_policy>" not in prompt
    # web_search and the action hands are never advertised on a read-only turn.
    assert "web_search" not in prompt


def test_with_actions_false_is_byte_identical_to_default():
    # The default (historical) call and the explicit read-only call must match
    # exactly so existing read turns keep their warm prompt cache.
    assert system_prompt_for(with_actions=False) == system_prompt_for()


def test_action_turn_swaps_identity_and_adds_policy():
    prompt = system_prompt_for(with_actions=True)
    assert _IDENTITY_SECTION_WITH_ACTIONS in prompt
    assert _IDENTITY_SECTION not in prompt  # swapped, not appended
    assert _ACTION_POLICY_SECTION in prompt
    # The policy names the automatic-read tool and the act-vs-ask contract.
    assert "web_search" in prompt
    assert "PROPOSED first" in prompt


def test_action_policy_is_strictly_gated_by_with_actions():
    assert "<action_policy>" not in system_prompt_for(with_actions=False)
    assert "<action_policy>" in system_prompt_for(with_actions=True)


def test_user_profile_and_memory_still_render_with_actions():
    # with_actions must not drop the per-user sections.
    prompt = system_prompt_for(
        memory_blocks={"human": "Prefers terse answers."}, with_actions=True
    )
    assert "<memory>" in prompt
    assert "Prefers terse answers." in prompt
    assert _ACTION_POLICY_SECTION in prompt


def test_reads_and_web_search_never_gate_but_action_hands_always_do():
    # The prompt PROMISES reads/web_search run automatically — the code must agree.
    for read_tool in (
        "search",
        "fetch",
        "list_recordings",
        "list_action_items",
        "list_folders",
        "web_search",
        "request_tool_group",
    ):
        assert is_mutating_tool_call(read_tool, {}) is False
    # ...and every hand the policy calls "gated" must actually gate.
    assert is_mutating_tool_call("send_message_telegram", {"text": "hi"}) is True
    assert is_mutating_tool_call("desktop_open", {"target": "https://x"}) is True
    assert is_mutating_tool_call("desktop_type", {"text": "hi"}) is True
    assert is_mutating_tool_call("desktop_click", {"index": 1}) is True
