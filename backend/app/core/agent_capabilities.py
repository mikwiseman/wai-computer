"""Agent capability catalog and config validation.

This is the public control-plane contract for what Wai agents can do today and
what must stay behind local/self-host policy before it is user-executable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal
from uuid import UUID

MAX_AGENT_STEPS = 20
MAX_AGENT_SEARCH_LIMIT = 50

CapabilityAvailability = Literal["available", "approval_required", "self_host_only", "planned"]


@dataclass(frozen=True)
class AgentCapability:
    id: str
    label: str
    category: str
    description: str
    availability: CapabilityAvailability
    runtime_tool: str | None
    surfaces: tuple[str, ...]
    requires_approval: bool
    cloud_supported: bool
    self_host_supported: bool
    local_gateway_required: bool
    safety_notes: str

    def to_response(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["surfaces"] = list(self.surfaces)
        return payload


AGENT_CAPABILITIES: tuple[AgentCapability, ...] = (
    AgentCapability(
        id="wai.note",
        label="Journal note",
        category="runtime",
        description="Record an internal run note in the agent journal.",
        availability="available",
        runtime_tool="note",
        surfaces=("web", "mac", "telegram", "api"),
        requires_approval=False,
        cloud_supported=True,
        self_host_supported=True,
        local_gateway_required=False,
        safety_notes="Non-mutating journal entry.",
    ),
    AgentCapability(
        id="wai.artifact.create",
        label="Create Wai artifact",
        category="memory",
        description="Create a Wai item with agent provenance.",
        availability="available",
        runtime_tool="create_artifact",
        surfaces=("web", "mac", "telegram", "api"),
        requires_approval=False,
        cloud_supported=True,
        self_host_supported=True,
        local_gateway_required=False,
        safety_notes="Stores user-visible content in the user's Wai library.",
    ),
    AgentCapability(
        id="wai.search",
        label="Search Wai data",
        category="memory",
        description="Search recordings, transcripts, summaries, and second-brain items.",
        availability="available",
        runtime_tool="search_wai",
        surfaces=("web", "mac", "telegram", "api", "mcp"),
        requires_approval=False,
        cloud_supported=True,
        self_host_supported=True,
        local_gateway_required=False,
        safety_notes="Read-only and owner-scoped.",
    ),
    AgentCapability(
        id="wai.memory.propose",
        label="Propose memory",
        category="memory",
        description="Create a governed memory proposal with evidence.",
        availability="available",
        runtime_tool="propose_memory",
        surfaces=("web", "mac", "telegram", "api"),
        requires_approval=False,
        cloud_supported=True,
        self_host_supported=True,
        local_gateway_required=False,
        safety_notes="Writes only to the proposal queue; human memory approval remains separate.",
    ),
    AgentCapability(
        id="wai.action.propose",
        label="Propose mutating action",
        category="approval",
        description="Queue a Telegram send, external write, or desktop action for approval.",
        availability="approval_required",
        runtime_tool="propose_action",
        surfaces=("web", "mac", "telegram", "api"),
        requires_approval=True,
        cloud_supported=True,
        self_host_supported=True,
        local_gateway_required=False,
        safety_notes="Side effects execute only after the HMAC approval ledger records approval.",
    ),
    AgentCapability(
        id="local.desktop.open",
        label="Open local app or URL",
        category="local_edge",
        description="Ask a paired Mac edge device to open an app, URL, or file target.",
        availability="approval_required",
        runtime_tool="propose_action",
        surfaces=("mac", "telegram", "web", "api"),
        requires_approval=True,
        cloud_supported=True,
        self_host_supported=True,
        local_gateway_required=True,
        safety_notes=(
            "Open actions are approval-gated and delivered only through a paired "
            "Mac edge device."
        ),
    ),
    AgentCapability(
        id="local.desktop.accessibility",
        label="Approved desktop accessibility action",
        category="local_edge",
        description="Ask a paired Mac edge device to type, click, or capture a desktop snapshot.",
        availability="approval_required",
        runtime_tool="propose_action",
        surfaces=("mac", "telegram", "web", "api"),
        requires_approval=True,
        cloud_supported=True,
        self_host_supported=True,
        local_gateway_required=True,
        safety_notes=(
            "Requires explicit approval; native execution re-checks the frontmost "
            "application before typing, clicking, or snapshotting."
        ),
    ),
    AgentCapability(
        id="local.shell",
        label="Local shell",
        category="local_edge",
        description="Run shell commands on a user-owned local gateway or self-host node.",
        availability="planned",
        runtime_tool=None,
        surfaces=("mac", "self_host", "api"),
        requires_approval=True,
        cloud_supported=False,
        self_host_supported=True,
        local_gateway_required=True,
        safety_notes=(
            "Blocked until command policies, leases, redaction, and "
            "rollback/checkpoint UX exist."
        ),
    ),
    AgentCapability(
        id="external.mcp.call_tool",
        label="External MCP tools",
        category="connectors",
        description="Call user-allowed tools exposed by connected MCP servers.",
        availability="planned",
        runtime_tool=None,
        surfaces=("web", "mac", "telegram", "api", "mcp"),
        requires_approval=True,
        cloud_supported=True,
        self_host_supported=True,
        local_gateway_required=False,
        safety_notes=(
            "Requires per-connection allowlists, schemas, and policy filtering "
            "before execution."
        ),
    ),
    AgentCapability(
        id="agent.delegate",
        label="Delegate to sub-agent",
        category="orchestration",
        description=(
            "Spawn isolated child runs for review, research, consensus, "
            "or specialist work."
        ),
        availability="available",
        runtime_tool="delegate_agent",
        surfaces=("web", "mac", "telegram", "api"),
        requires_approval=False,
        cloud_supported=True,
        self_host_supported=True,
        local_gateway_required=False,
        safety_notes=(
            "Creates an owner-scoped child run with a parent edge; nested "
            "delegation is blocked in v1."
        ),
    ),
)

RUNTIME_TOOL_NAMES = frozenset(
    capability.runtime_tool for capability in AGENT_CAPABILITIES if capability.runtime_tool
)
SERVER_ACTION_TOOL_NAMES = frozenset({"send_message_telegram"})
DESKTOP_ACTION_TOOL_NAMES = frozenset(
    {"desktop_open", "desktop_type", "desktop_click", "desktop_snapshot"}
)
ACTION_TOOL_NAMES = SERVER_ACTION_TOOL_NAMES | DESKTOP_ACTION_TOOL_NAMES
MEMORY_OPERATIONS = frozenset({"append", "replace_line", "rewrite"})


def capabilities_response(*, deployment_mode: str) -> dict[str, Any]:
    """Return the agent control-plane contract consumed by all clients."""
    return {
        "schema_version": "2026-06-03",
        "deployment_mode": deployment_mode,
        "max_steps": MAX_AGENT_STEPS,
        "runtime_modes": [
            {
                "id": "wai_cloud",
                "label": "Wai Cloud",
                "description": "Runs on Wai infrastructure with approval-gated actions.",
                "available": deployment_mode == "wai_cloud",
            },
            {
                "id": "self_host",
                "label": "User VPS",
                "description": "Runs the same API, workers, data, and agents on the user's server.",
                "available": True,
            },
            {
                "id": "local_edge",
                "label": "Local Mac edge",
                "description": "Pairs a local device for approved desktop operations.",
                "available": True,
            },
        ],
        "capabilities": [capability.to_response() for capability in AGENT_CAPABILITIES],
    }


def validate_agent_config(config: dict[str, Any]) -> None:
    """Validate user-authored static agent plans before a run can fail late."""
    if not isinstance(config, dict):
        raise ValueError("Agent config must be an object")
    steps = config.get("steps")
    if steps is None:
        return
    if not isinstance(steps, list):
        raise ValueError("Agent config.steps must be an array")
    if len(steps) > MAX_AGENT_STEPS:
        raise ValueError(f"Agent config.steps cannot exceed {MAX_AGENT_STEPS} steps")

    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"Agent config.steps[{idx}] must be an object")
        tool = step.get("tool")
        args = step.get("args") or {}
        if not isinstance(tool, str) or not tool:
            raise ValueError(f"Agent config.steps[{idx}].tool must be a non-empty string")
        if tool not in RUNTIME_TOOL_NAMES:
            raise ValueError(f"Unknown agent tool: {tool}")
        if not isinstance(args, dict):
            raise ValueError(f"Agent config.steps[{idx}].args must be an object")
        _validate_step_args(tool, args, idx)


def _require_text(args: dict[str, Any], field: str, idx: int, tool: str) -> str:
    value = args.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Agent config.steps[{idx}].{tool}.{field} is required")
    return value.strip()


def _validate_step_args(tool: str, args: dict[str, Any], idx: int) -> None:
    if tool == "note":
        _require_text(args, "text", idx, tool)
        return
    if tool == "create_artifact":
        _require_text(args, "title", idx, tool)
        _require_text(args, "body", idx, tool)
        if args.get("kind") is not None and not isinstance(args.get("kind"), str):
            raise ValueError(f"Agent config.steps[{idx}].create_artifact.kind must be a string")
        return
    if tool == "search_wai":
        _require_text(args, "query", idx, tool)
        if args.get("limit") is not None:
            limit = args.get("limit")
            if not isinstance(limit, int) or limit < 1 or limit > MAX_AGENT_SEARCH_LIMIT:
                raise ValueError(
                    f"Agent config.steps[{idx}].search_wai.limit must be "
                    f"1..{MAX_AGENT_SEARCH_LIMIT}"
                )
        return
    if tool == "propose_memory":
        _require_text(args, "content", idx, tool)
        operation = str(args.get("operation") or "append")
        if operation not in MEMORY_OPERATIONS:
            raise ValueError(f"Unsupported memory operation: {operation}")
        return
    if tool == "propose_action":
        tool_name = _require_text(args, "tool_name", idx, tool)
        if tool_name not in ACTION_TOOL_NAMES:
            raise ValueError(f"Unsupported action tool: {tool_name}")
        action_args = args.get("action_args") or {}
        if not isinstance(action_args, dict):
            raise ValueError(
                f"Agent config.steps[{idx}].propose_action.action_args must be an object"
            )
        device_target = args.get("device_target")
        if tool_name.startswith("desktop_") and device_target is None:
            raise ValueError(
                f"Agent config.steps[{idx}].propose_action.device_target is "
                "required for desktop actions"
            )
        if device_target is not None:
            if not isinstance(device_target, str):
                raise ValueError(
                    f"Agent config.steps[{idx}].propose_action.device_target must be a UUID string"
                )
            try:
                UUID(device_target)
            except ValueError as exc:
                raise ValueError(
                    f"Agent config.steps[{idx}].propose_action.device_target must be a UUID string"
                ) from exc
        _require_text(args, "preview", idx, tool)
        return
    if tool == "delegate_agent":
        has_agent_id = bool(str(args.get("agent_id") or "").strip())
        has_agent_name = bool(str(args.get("agent_name") or "").strip())
        if has_agent_id == has_agent_name:
            raise ValueError(
                "delegate_agent requires exactly one of agent_id or agent_name"
            )
        if has_agent_id:
            try:
                UUID(str(args.get("agent_id")).strip())
            except ValueError as exc:
                raise ValueError(
                    f"Agent config.steps[{idx}].delegate_agent.agent_id must be a UUID string"
                ) from exc
        _require_text(args, "objective", idx, tool)
        return
