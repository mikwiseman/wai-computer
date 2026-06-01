"""ToolRouter: groups, profiles, lazy group attach, deny-always (P2)."""

from app.core import tool_router as tr


def test_voice_default_profile_is_reads_only():
    assert tr.default_groups("voice_default") == frozenset({"read", "memory", "web"})
    # Write/OS groups are NOT in the default profile (opt-in).
    assert "telegram" not in tr.default_groups("voice_default")
    assert "desktop" not in tr.default_groups("voice_default")


def test_group_of_maps_tools_to_groups():
    assert tr.group_of("search_transcripts") == "read"
    assert tr.group_of("send_message_telegram") == "telegram"
    assert tr.group_of("remember") == "memory"
    assert tr.group_of("does_not_exist") is None


def test_visible_tool_names_for_default_excludes_write_groups():
    visible = tr.visible_tool_names(tr.default_groups("voice_default"))
    assert "search_transcripts" in visible
    assert "web_search" in visible
    assert "remember" in visible
    # No telegram send tool until the group is requested.
    assert "send_message_telegram" not in visible


def test_resolve_active_groups_adds_requested_and_drops_denied():
    active = tr.resolve_active_groups("voice_default", requested=["telegram"])
    assert "telegram" in active
    assert "read" in active
    # An unknown requested group is ignored.
    active2 = tr.resolve_active_groups("voice_default", requested=["nope"])
    assert "nope" not in active2
    # Denied groups are removed even if defaulted.
    active3 = tr.resolve_active_groups("voice_default", denied=["web"])
    assert "web" not in active3


def test_requesting_telegram_exposes_its_send_tools():
    active = tr.resolve_active_groups("voice_default", requested=["telegram"])
    visible = tr.visible_tool_names(active)
    assert "send_message_telegram" in visible
    assert "reply_to_message_telegram" in visible


def test_request_tool_group_meta_tool_offers_only_nonempty_optin_groups():
    tool = tr.request_tool_group_tool("voice_default")
    assert tool["name"] == "request_tool_group"
    enum = tool["parameters"]["properties"]["group"]["enum"]
    assert "telegram" in enum  # has tools, not default → offered
    assert "read" not in enum  # default group → not offered
    assert "desktop" not in enum  # empty group → not offered (yet)
    assert "gmail" not in enum


def test_filter_tool_defs_keeps_only_visible():
    defs = [
        {"name": "search_transcripts"},
        {"name": "send_message_telegram"},
        {"name": "web_search"},
    ]
    # Default (no telegram): the send tool is filtered out.
    kept = {t["name"] for t in tr.filter_tool_defs(defs, tr.default_groups())}
    assert kept == {"search_transcripts", "web_search"}
    # After requesting telegram: it appears.
    active = tr.resolve_active_groups("voice_default", requested=["telegram"])
    kept2 = {t["name"] for t in tr.filter_tool_defs(defs, active)}
    assert "send_message_telegram" in kept2


def test_deny_always_is_respected(monkeypatch):
    # Even if a tool is in an active group, DENY_ALWAYS removes it.
    monkeypatch.setattr(tr, "DENY_ALWAYS", frozenset({"send_message_telegram"}))
    active = tr.resolve_active_groups("voice_default", requested=["telegram"])
    assert "send_message_telegram" not in tr.visible_tool_names(active)
