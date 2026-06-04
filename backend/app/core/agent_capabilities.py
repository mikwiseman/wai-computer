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
MEMORY_OPERATIONS = frozenset({"append", "replace_line", "rewrite"})
SERVER_ACTION_TOOL_NAMES = frozenset({"send_message_telegram"})
DESKTOP_ACTION_TOOL_NAMES = frozenset(
    {"desktop_open", "desktop_type", "desktop_click", "desktop_snapshot"}
)
ACTION_TOOL_NAMES = SERVER_ACTION_TOOL_NAMES | DESKTOP_ACTION_TOOL_NAMES

CapabilityAvailability = Literal["available", "approval_required", "self_host_only", "planned"]
ToolKind = Literal["runtime", "action"]
SideEffect = Literal[
    "none",
    "user_content_write",
    "approval_request",
    "server_side_effect",
    "local_desktop_effect",
    "orchestration",
]


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
    risk_level: str
    permission_scopes: tuple[str, ...]
    safety_notes: str

    def to_response(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["surfaces"] = list(self.surfaces)
        payload["permission_scopes"] = list(self.permission_scopes)
        return payload


@dataclass(frozen=True)
class AgentToolContract:
    """Executable contract for one runtime tool or approval-gated action tool."""

    name: str
    capability_id: str
    kind: ToolKind
    description: str
    side_effect: SideEffect
    requires_approval: bool
    args_schema: dict[str, Any]
    result_schema: dict[str, Any]
    permission_scopes: tuple[str, ...]

    def to_response(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["permission_scopes"] = list(self.permission_scopes)
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
        risk_level="read_only",
        permission_scopes=("agent:run:read",),
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
        risk_level="user_content_write",
        permission_scopes=("items:write",),
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
        risk_level="read_only",
        permission_scopes=("search:read", "recordings:read", "items:read"),
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
        risk_level="governed_write",
        permission_scopes=("memory:propose",),
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
        risk_level="approval_required",
        permission_scopes=("actions:propose",),
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
        risk_level="local_edge_approval",
        permission_scopes=("actions:propose", "desktop:open"),
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
        risk_level="local_edge_approval",
        permission_scopes=("actions:propose", "desktop:accessibility"),
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
        risk_level="planned_high_risk",
        permission_scopes=("shell:execute",),
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
        risk_level="planned_connector_write",
        permission_scopes=("mcp:call_tool",),
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
        risk_level="orchestration",
        permission_scopes=("agents:run",),
        safety_notes=(
            "Creates an owner-scoped child run with a parent edge; nested "
            "delegation is blocked in v1."
        ),
    ),
)

AGENT_TOOL_CONTRACTS: tuple[AgentToolContract, ...] = (
    AgentToolContract(
        name="note",
        capability_id="wai.note",
        kind="runtime",
        description="Append a non-mutating journal note to the run.",
        side_effect="none",
        requires_approval=False,
        permission_scopes=("agent:run:read",),
        args_schema={
            "type": "object",
            "required": ["text"],
            "additionalProperties": False,
            "properties": {"text": {"type": "string", "minLength": 1}},
        },
        result_schema={
            "type": "object",
            "required": ["text"],
            "properties": {"text": {"type": "string"}},
        },
    ),
    AgentToolContract(
        name="create_artifact",
        capability_id="wai.artifact.create",
        kind="runtime",
        description="Create an agent-provenanced Wai library item.",
        side_effect="user_content_write",
        requires_approval=False,
        permission_scopes=("items:write",),
        args_schema={
            "type": "object",
            "required": ["title", "body"],
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "body": {"type": "string", "minLength": 1},
                "kind": {"type": "string", "minLength": 1},
            },
        },
        result_schema={
            "type": "object",
            "required": ["item_id", "created"],
            "properties": {
                "item_id": {"type": "string"},
                "created": {"type": "boolean"},
            },
        },
    ),
    AgentToolContract(
        name="search_wai",
        capability_id="wai.search",
        kind="runtime",
        description="Owner-scoped search over recordings, transcripts, summaries, and items.",
        side_effect="none",
        requires_approval=False,
        permission_scopes=("search:read", "recordings:read", "items:read"),
        args_schema={
            "type": "object",
            "required": ["query"],
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_AGENT_SEARCH_LIMIT},
            },
        },
        result_schema={
            "type": "object",
            "required": ["query", "hits"],
            "properties": {
                "query": {"type": "string"},
                "hits": {"type": "array", "items": {"type": "object"}},
            },
        },
    ),
    AgentToolContract(
        name="propose_memory",
        capability_id="wai.memory.propose",
        kind="runtime",
        description="Propose a governed long-term memory edit.",
        side_effect="user_content_write",
        requires_approval=False,
        permission_scopes=("memory:propose",),
        args_schema={
            "type": "object",
            "required": ["content"],
            "additionalProperties": False,
            "properties": {
                "content": {"type": "string", "minLength": 1},
                "block": {"type": "string", "minLength": 1},
                "operation": {"type": "string", "enum": sorted(MEMORY_OPERATIONS)},
                "target_line": {"type": ["integer", "null"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "authority": {"type": "string", "minLength": 1},
                "summary": {"type": ["string", "null"]},
                "evidence": {},
            },
        },
        result_schema={"type": "object", "properties": {"proposal_id": {"type": "string"}}},
    ),
    AgentToolContract(
        name="propose_action",
        capability_id="wai.action.propose",
        kind="runtime",
        description="Queue one typed action tool for human approval.",
        side_effect="approval_request",
        requires_approval=True,
        permission_scopes=("actions:propose",),
        args_schema={
            "type": "object",
            "required": ["tool_name", "action_args", "preview"],
            "additionalProperties": False,
            "properties": {
                "tool_name": {"type": "string", "enum": sorted(ACTION_TOOL_NAMES)},
                "action_args": {"type": "object"},
                "preview": {"type": "string", "minLength": 1},
                "kind": {"type": "string"},
                "recipient_display": {"type": ["string", "null"]},
                "device_target": {"type": ["string", "null"], "format": "uuid"},
                "ttl_seconds": {"type": "integer", "minimum": 1},
            },
        },
        result_schema={
            "type": "object",
            "required": ["action_id", "tool", "expires_at"],
            "properties": {
                "action_id": {"type": "string"},
                "tool": {"type": "string"},
                "expires_at": {"type": "string", "format": "date-time"},
            },
        },
    ),
    AgentToolContract(
        name="delegate_agent",
        capability_id="agent.delegate",
        kind="runtime",
        description="Create an owner-scoped child run for another enabled agent.",
        side_effect="orchestration",
        requires_approval=False,
        permission_scopes=("agents:run",),
        args_schema={
            "type": "object",
            "required": ["objective"],
            "additionalProperties": False,
            "oneOf": [
                {"required": ["agent_id"], "not": {"required": ["agent_name"]}},
                {"required": ["agent_name"], "not": {"required": ["agent_id"]}},
            ],
            "properties": {
                "agent_id": {"type": "string", "format": "uuid"},
                "agent_name": {"type": "string", "minLength": 1},
                "objective": {"type": "string", "minLength": 1},
            },
        },
        result_schema={
            "type": "object",
            "required": ["child_run_id", "agent_id", "status", "created"],
            "properties": {
                "child_run_id": {"type": "string"},
                "agent_id": {"type": "string"},
                "status": {"type": "string"},
                "created": {"type": "boolean"},
            },
        },
    ),
    AgentToolContract(
        name="send_message_telegram",
        capability_id="wai.action.propose",
        kind="action",
        description="After approval, send text to the user's own linked Telegram DM.",
        side_effect="server_side_effect",
        requires_approval=True,
        permission_scopes=("telegram:send:self",),
        args_schema={
            "type": "object",
            "required": ["text"],
            "additionalProperties": False,
            "properties": {"text": {"type": "string", "minLength": 1}},
        },
        result_schema={
            "type": "object",
            "required": ["channel", "chat_id"],
            "properties": {
                "channel": {"type": "string", "const": "telegram"},
                "chat_id": {"type": "integer"},
                "message_id": {"type": ["integer", "null"]},
            },
        },
    ),
    AgentToolContract(
        name="desktop_open",
        capability_id="local.desktop.open",
        kind="action",
        description="After approval, ask a paired Mac edge to open an app or allowed URL.",
        side_effect="local_desktop_effect",
        requires_approval=True,
        permission_scopes=("desktop:open",),
        args_schema={
            "type": "object",
            "required": ["target"],
            "additionalProperties": False,
            "properties": {"target": {"type": "string", "minLength": 1}},
        },
        result_schema={"type": "object", "properties": {"status": {"type": "string"}}},
    ),
    AgentToolContract(
        name="desktop_type",
        capability_id="local.desktop.accessibility",
        kind="action",
        description="After approval, ask a paired Mac edge to type into the current app.",
        side_effect="local_desktop_effect",
        requires_approval=True,
        permission_scopes=("desktop:accessibility",),
        args_schema={
            "type": "object",
            "required": ["text"],
            "additionalProperties": False,
            "properties": {"text": {"type": "string", "minLength": 1}},
        },
        result_schema={"type": "object", "properties": {"status": {"type": "string"}}},
    ),
    AgentToolContract(
        name="desktop_click",
        capability_id="local.desktop.accessibility",
        kind="action",
        description="After approval, ask a paired Mac edge to click a snapshot element index.",
        side_effect="local_desktop_effect",
        requires_approval=True,
        permission_scopes=("desktop:accessibility",),
        args_schema={
            "type": "object",
            "required": ["index"],
            "additionalProperties": False,
            "properties": {"index": {"type": "integer", "minimum": 0}},
        },
        result_schema={"type": "object", "properties": {"status": {"type": "string"}}},
    ),
    AgentToolContract(
        name="desktop_snapshot",
        capability_id="local.desktop.accessibility",
        kind="action",
        description="After approval, ask a paired Mac edge for a sanitized UI snapshot.",
        side_effect="local_desktop_effect",
        requires_approval=True,
        permission_scopes=("desktop:accessibility",),
        args_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        },
        result_schema={"type": "object", "properties": {"snapshot": {"type": "object"}}},
    ),
)

RUNTIME_TOOL_CONTRACTS = {
    contract.name: contract for contract in AGENT_TOOL_CONTRACTS if contract.kind == "runtime"
}
ACTION_TOOL_CONTRACTS = {
    contract.name: contract for contract in AGENT_TOOL_CONTRACTS if contract.kind == "action"
}
RUNTIME_TOOL_NAMES = frozenset(RUNTIME_TOOL_CONTRACTS)


def capabilities_response(*, deployment_mode: str) -> dict[str, Any]:
    """Return the agent control-plane contract consumed by all clients."""
    return {
        "schema_version": "2026-06-04",
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
        "tool_contracts": [contract.to_response() for contract in AGENT_TOOL_CONTRACTS],
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
            if (
                not isinstance(limit, int)
                or isinstance(limit, bool)
                or limit < 1
                or limit > MAX_AGENT_SEARCH_LIMIT
            ):
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
        _validate_action_args(tool_name, action_args, idx)
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


def _reject_unknown_action_args(
    args: dict[str, Any], allowed: set[str], idx: int, tool_name: str
) -> None:
    unknown = sorted(set(args) - allowed)
    if unknown:
        raise ValueError(
            f"Agent config.steps[{idx}].propose_action.action_args for "
            f"{tool_name} has unsupported fields: {', '.join(unknown)}"
        )


def _validate_action_args(tool_name: str, action_args: dict[str, Any], idx: int) -> None:
    if tool_name == "send_message_telegram":
        _reject_unknown_action_args(action_args, {"text"}, idx, tool_name)
        value = action_args.get("text")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Agent config.steps[{idx}].propose_action.action_args.text is required"
            )
        return
    if tool_name == "desktop_open":
        _reject_unknown_action_args(action_args, {"target"}, idx, tool_name)
        value = action_args.get("target")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Agent config.steps[{idx}].propose_action.action_args.target is required"
            )
        return
    if tool_name == "desktop_type":
        _reject_unknown_action_args(action_args, {"text"}, idx, tool_name)
        value = action_args.get("text")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Agent config.steps[{idx}].propose_action.action_args.text is required"
            )
        return
    if tool_name == "desktop_click":
        _reject_unknown_action_args(action_args, {"index"}, idx, tool_name)
        value = action_args.get("index")
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"Agent config.steps[{idx}].propose_action.action_args.index must be "
                "a non-negative integer"
            )
        return
    if tool_name == "desktop_snapshot":
        _reject_unknown_action_args(action_args, set(), idx, tool_name)
        return
