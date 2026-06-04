"""Agent capability contract validation."""

import pytest

from app.core.agent_capabilities import (
    ACTION_TOOL_CONTRACTS,
    ACTION_TOOL_NAMES,
    AGENT_CAPABILITIES,
    AGENT_TOOL_CONTRACTS,
    MAX_AGENT_SEARCH_LIMIT,
    MAX_AGENT_STEPS,
    RUNTIME_TOOL_CONTRACTS,
    RUNTIME_TOOL_NAMES,
    capabilities_response,
    validate_agent_config,
)


def test_capabilities_response_serializes_runtime_modes_and_surfaces():
    body = capabilities_response(deployment_mode="self_host")

    assert body["schema_version"] == "2026-06-04"
    assert body["runtime_modes"][0]["available"] is False
    assert body["runtime_modes"][1]["available"] is True
    note = next(capability for capability in body["capabilities"] if capability["id"] == "wai.note")
    assert note["surfaces"] == ["web", "mac", "telegram", "api"]
    assert note["risk_level"] == "read_only"
    assert note["permission_scopes"] == ["agent:run:read"]
    contracts = {contract["name"]: contract for contract in body["tool_contracts"]}
    assert contracts["search_wai"]["args_schema"]["properties"]["limit"]["maximum"] == 50
    assert contracts["propose_action"]["args_schema"]["properties"]["tool_name"]["enum"] == sorted(
        ACTION_TOOL_NAMES
    )


def test_capability_tool_contracts_stay_in_sync():
    capability_ids = {capability.id for capability in AGENT_CAPABILITIES}
    executable_tools = {
        capability.runtime_tool
        for capability in AGENT_CAPABILITIES
        if capability.availability != "planned" and capability.runtime_tool is not None
    }

    assert executable_tools == RUNTIME_TOOL_NAMES
    assert set(RUNTIME_TOOL_CONTRACTS) == {
        "note",
        "create_artifact",
        "search_wai",
        "propose_memory",
        "propose_action",
        "delegate_agent",
    }
    assert set(ACTION_TOOL_CONTRACTS) == ACTION_TOOL_NAMES
    assert all(contract.capability_id in capability_ids for contract in AGENT_TOOL_CONTRACTS)
    assert all(
        contract.requires_approval for contract in AGENT_TOOL_CONTRACTS if contract.kind == "action"
    )
    assert {
        capability.id for capability in AGENT_CAPABILITIES if capability.availability == "planned"
    } == {"local.shell", "external.mcp.call_tool"}


def test_validate_agent_config_accepts_all_enabled_tools():
    validate_agent_config(
        {
            "steps": [
                {"tool": "note", "args": {"text": "journal"}},
                {
                    "tool": "create_artifact",
                    "args": {"title": "Research", "body": "Body", "kind": "note"},
                },
                {
                    "tool": "search_wai",
                    "args": {"query": "roadmap", "limit": MAX_AGENT_SEARCH_LIMIT},
                },
                {
                    "tool": "propose_memory",
                    "args": {"content": "Remember this", "operation": "append"},
                },
                {
                    "tool": "propose_action",
                    "args": {
                        "tool_name": "desktop_open",
                        "action_args": {"target": "https://wai.computer"},
                        "preview": "Open WaiComputer",
                        "device_target": "11111111-1111-4111-8111-111111111111",
                    },
                },
                {
                    "tool": "delegate_agent",
                    "args": {
                        "agent_name": "Reviewer",
                        "objective": "Review the proposed plan.",
                    },
                },
            ]
        }
    )


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ([], "Agent config must be an object"),
        ({"steps": None}, None),
        ({"steps": "bad"}, "Agent config.steps must be an array"),
        (
            {"steps": [{"tool": "note", "args": {"text": "x"}}] * (MAX_AGENT_STEPS + 1)},
            "Agent config.steps cannot exceed",
        ),
        ({"steps": ["bad"]}, "Agent config.steps[0] must be an object"),
        ({"steps": [{"tool": "", "args": {}}]}, "tool must be a non-empty string"),
        ({"steps": [{"tool": "local_shell", "args": {}}]}, "Unknown agent tool"),
        ({"steps": [{"tool": "note", "args": "bad"}]}, "args must be an object"),
        ({"steps": [{"tool": "note", "args": {"text": " "}}]}, "note.text is required"),
        (
            {"steps": [{"tool": "create_artifact", "args": {"title": "T", "body": " "}}]},
            "create_artifact.body is required",
        ),
        (
            {
                "steps": [
                    {
                        "tool": "create_artifact",
                        "args": {"title": "T", "body": "B", "kind": 1},
                    }
                ]
            },
            "create_artifact.kind must be a string",
        ),
        (
            {"steps": [{"tool": "search_wai", "args": {"query": "q", "limit": 0}}]},
            "search_wai.limit must be",
        ),
        (
            {"steps": [{"tool": "search_wai", "args": {"query": "q", "limit": True}}]},
            "search_wai.limit must be",
        ),
        (
            {"steps": [{"tool": "propose_memory", "args": {"content": "x", "operation": "bad"}}]},
            "Unsupported memory operation",
        ),
        (
            {
                "steps": [
                    {
                        "tool": "propose_action",
                        "args": {"tool_name": "bad", "preview": "Preview"},
                    }
                ]
            },
            "Unsupported action tool",
        ),
        (
            {
                "steps": [
                    {
                        "tool": "propose_action",
                        "args": {
                            "tool_name": "desktop_open",
                            "action_args": "bad",
                            "preview": "Preview",
                        },
                    }
                ]
            },
            "propose_action.action_args must be an object",
        ),
        (
            {
                "steps": [
                    {
                        "tool": "propose_action",
                        "args": {
                            "tool_name": "send_message_telegram",
                            "action_args": {},
                            "preview": "Preview",
                        },
                    }
                ]
            },
            "propose_action.action_args.text is required",
        ),
        (
            {
                "steps": [
                    {
                        "tool": "propose_action",
                        "args": {
                            "tool_name": "send_message_telegram",
                            "action_args": {"text": "hello", "extra": "no"},
                            "preview": "Preview",
                        },
                    }
                ]
            },
            "unsupported fields: extra",
        ),
        (
            {
                "steps": [
                    {
                        "tool": "propose_action",
                        "args": {
                            "tool_name": "desktop_snapshot",
                            "action_args": {"target": "Mail"},
                            "preview": "Snapshot",
                            "device_target": "11111111-1111-4111-8111-111111111111",
                        },
                    }
                ]
            },
            "unsupported fields: target",
        ),
        (
            {
                "steps": [
                    {
                        "tool": "propose_action",
                        "args": {
                            "tool_name": "desktop_click",
                            "action_args": {"index": True},
                            "preview": "Click",
                            "device_target": "11111111-1111-4111-8111-111111111111",
                        },
                    }
                ]
            },
            "action_args.index must be a non-negative integer",
        ),
        (
            {
                "steps": [
                    {
                        "tool": "propose_action",
                        "args": {
                            "tool_name": "desktop_click",
                            "action_args": {"index": -1},
                            "preview": "Click",
                            "device_target": "11111111-1111-4111-8111-111111111111",
                        },
                    }
                ]
            },
            "action_args.index must be a non-negative integer",
        ),
        (
            {"steps": [{"tool": "propose_action", "args": {"tool_name": "desktop_open"}}]},
            "propose_action.device_target is required for desktop actions",
        ),
        (
            {
                "steps": [
                    {
                        "tool": "propose_action",
                        "args": {"tool_name": "send_message_telegram"},
                    }
                ]
            },
            "propose_action.preview is required",
        ),
        (
            {
                "steps": [
                    {
                        "tool": "propose_action",
                        "args": {
                            "tool_name": "desktop_open",
                            "action_args": {"target": "https://wai.computer"},
                            "preview": "Open WaiComputer",
                            "device_target": "mac:primary",
                        },
                    }
                ]
            },
            "propose_action.device_target must be a UUID string",
        ),
        (
            {"steps": [{"tool": "delegate_agent", "args": {"objective": "x"}}]},
            "delegate_agent requires exactly one of agent_id or agent_name",
        ),
        (
            {"steps": [{"tool": "delegate_agent", "args": {"agent_name": "Reviewer"}}]},
            "delegate_agent.objective is required",
        ),
    ],
)
def test_validate_agent_config_rejects_bad_configs(config, message):
    if message is None:
        validate_agent_config(config)
        return

    with pytest.raises(ValueError) as exc:
        validate_agent_config(config)
    assert message in str(exc.value)
