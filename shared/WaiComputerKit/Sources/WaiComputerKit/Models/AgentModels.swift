import Foundation

public enum AgentTriggerType: String, Codable, Sendable, Equatable {
    case manual
    case cron
    case event
    case signal
    case chat
}

public enum AgentRunTriggerKind: String, Codable, Sendable, Equatable {
    case manual
    case cron
    case event
    case signal
    case chat
    case telegram
    case agent
}

public struct AgentDefinition: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let name: String
    public let kind: String
    public let triggerType: AgentTriggerType
    public let config: [String: JSONValue]
    public let autonomy: String
    public let enabled: Bool
    public let nextRunAt: Date?
    public let lastRunAt: Date?
    public let createdAt: Date
    public let updatedAt: Date

    private enum CodingKeys: String, CodingKey {
        case id
        case name
        case kind
        case triggerType = "trigger_type"
        case config
        case autonomy
        case enabled
        case nextRunAt = "next_run_at"
        case lastRunAt = "last_run_at"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

public struct AgentListResponse: Codable, Sendable, Equatable {
    public let agents: [AgentDefinition]
}

public struct AgentCreateRequest: Codable, Sendable, Equatable {
    public let name: String
    public let kind: String?
    public let triggerType: AgentTriggerType?
    public let config: [String: JSONValue]?
    public let autonomy: String?
    public let enabled: Bool?
    public let nextRunAt: Date?

    public init(
        name: String,
        kind: String? = nil,
        triggerType: AgentTriggerType? = nil,
        config: [String: JSONValue]? = nil,
        autonomy: String? = "propose",
        enabled: Bool? = nil,
        nextRunAt: Date? = nil
    ) {
        self.name = name
        self.kind = kind
        self.triggerType = triggerType
        self.config = config
        self.autonomy = autonomy
        self.enabled = enabled
        self.nextRunAt = nextRunAt
    }

    private enum CodingKeys: String, CodingKey {
        case name
        case kind
        case triggerType = "trigger_type"
        case config
        case autonomy
        case enabled
        case nextRunAt = "next_run_at"
    }
}

public struct AgentUpdateRequest: Codable, Sendable, Equatable {
    public let name: String?
    public let kind: String?
    public let triggerType: AgentTriggerType?
    public let config: [String: JSONValue]?
    public let autonomy: String?
    public let enabled: Bool?
    public let nextRunAt: Date?

    public init(
        name: String? = nil,
        kind: String? = nil,
        triggerType: AgentTriggerType? = nil,
        config: [String: JSONValue]? = nil,
        autonomy: String? = nil,
        enabled: Bool? = nil,
        nextRunAt: Date? = nil
    ) {
        self.name = name
        self.kind = kind
        self.triggerType = triggerType
        self.config = config
        self.autonomy = autonomy
        self.enabled = enabled
        self.nextRunAt = nextRunAt
    }

    private enum CodingKeys: String, CodingKey {
        case name
        case kind
        case triggerType = "trigger_type"
        case config
        case autonomy
        case enabled
        case nextRunAt = "next_run_at"
    }
}

public struct AgentRun: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let agentId: String
    public let parentRunId: String?
    public let parentStepIdx: Int?
    public let triggerKey: String
    public let triggerKind: AgentRunTriggerKind
    public let triggerPayload: [String: JSONValue]?
    public let status: String
    public let plan: [String: JSONValue]?
    public let doneSpec: [String: JSONValue]?
    public let result: [String: JSONValue]?
    public let contentHash: String?
    public let error: String?
    public let nextStepIdx: Int
    public let heartbeatAt: Date?
    public let startedAt: Date?
    public let finishedAt: Date?
    public let cancelRequestedAt: Date?
    public let createdAt: Date
    public let updatedAt: Date

    private enum CodingKeys: String, CodingKey {
        case id
        case agentId = "agent_id"
        case parentRunId = "parent_run_id"
        case parentStepIdx = "parent_step_idx"
        case triggerKey = "trigger_key"
        case triggerKind = "trigger_kind"
        case triggerPayload = "trigger_payload"
        case status
        case plan
        case doneSpec = "done_spec"
        case result
        case contentHash = "content_hash"
        case error
        case nextStepIdx = "next_step_idx"
        case heartbeatAt = "heartbeat_at"
        case startedAt = "started_at"
        case finishedAt = "finished_at"
        case cancelRequestedAt = "cancel_requested_at"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

public struct AgentRunListResponse: Codable, Sendable, Equatable {
    public let runs: [AgentRun]
}

public struct StartAgentRunRequest: Codable, Sendable, Equatable {
    public let triggerKind: AgentRunTriggerKind?
    public let triggerPayload: [String: JSONValue]?
    public let contentHash: String?
    public let idempotencyKey: String?
    public let runInline: Bool?

    public init(
        triggerKind: AgentRunTriggerKind? = nil,
        triggerPayload: [String: JSONValue]? = nil,
        contentHash: String? = nil,
        idempotencyKey: String? = nil,
        runInline: Bool? = nil
    ) {
        self.triggerKind = triggerKind
        self.triggerPayload = triggerPayload
        self.contentHash = contentHash
        self.idempotencyKey = idempotencyKey
        self.runInline = runInline
    }

    private enum CodingKeys: String, CodingKey {
        case triggerKind = "trigger_kind"
        case triggerPayload = "trigger_payload"
        case contentHash = "content_hash"
        case idempotencyKey = "idempotency_key"
        case runInline = "run_inline"
    }
}

public struct AgentStep: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let runId: String
    public let idx: Int
    public let kind: String
    public let payload: [String: JSONValue]
    public let idempotencyKey: String?
    public let createdAt: Date
    public let updatedAt: Date

    private enum CodingKeys: String, CodingKey {
        case id
        case runId = "run_id"
        case idx
        case kind
        case payload
        case idempotencyKey = "idempotency_key"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

public struct AgentStepListResponse: Codable, Sendable, Equatable {
    public let steps: [AgentStep]
}

public struct AgentAction: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let agentId: String?
    public let runId: String?
    public let stepIdx: Int?
    public let kind: String
    public let tool: String
    public let status: String
    public let preview: String
    public let recipient: String?
    public let expiresAt: Date
    public let resolvedAt: Date?
    public let receipt: [String: JSONValue]?

    private enum CodingKeys: String, CodingKey {
        case id
        case agentId = "agent_id"
        case runId = "run_id"
        case stepIdx = "step_idx"
        case kind
        case tool
        case status
        case preview
        case recipient
        case expiresAt = "expires_at"
        case resolvedAt = "resolved_at"
        case receipt
    }
}

public struct AgentActionListResponse: Codable, Sendable, Equatable {
    public let actions: [AgentAction]
}

public struct ResolveAgentActionRequest: Codable, Sendable, Equatable {
    public let decision: String
    public let editedArgs: [String: JSONValue]?

    public init(decision: String, editedArgs: [String: JSONValue]? = nil) {
        self.decision = decision
        self.editedArgs = editedArgs
    }

    private enum CodingKeys: String, CodingKey {
        case decision
        case editedArgs = "edited_args"
    }
}

public struct ResolveAgentActionResponse: Codable, Sendable, Equatable {
    public let actionId: String
    public let status: String
    public let runStatus: String
    public let recipient: String?

    private enum CodingKeys: String, CodingKey {
        case actionId = "action_id"
        case status
        case runStatus = "run_status"
        case recipient
    }
}

public struct AgentCapability: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let label: String
    public let category: String
    public let description: String
    public let availability: String
    public let runtimeTool: String?
    public let surfaces: [String]
    public let requiresApproval: Bool
    public let cloudSupported: Bool
    public let selfHostSupported: Bool
    public let localGatewayRequired: Bool
    public let riskLevel: String
    public let permissionScopes: [String]
    public let safetyNotes: String

    private enum CodingKeys: String, CodingKey {
        case id
        case label
        case category
        case description
        case availability
        case runtimeTool = "runtime_tool"
        case surfaces
        case requiresApproval = "requires_approval"
        case cloudSupported = "cloud_supported"
        case selfHostSupported = "self_host_supported"
        case localGatewayRequired = "local_gateway_required"
        case riskLevel = "risk_level"
        case permissionScopes = "permission_scopes"
        case safetyNotes = "safety_notes"
    }
}

public struct AgentToolContract: Codable, Sendable, Equatable, Identifiable {
    public var id: String { name }

    public let name: String
    public let capabilityId: String
    public let kind: String
    public let description: String
    public let sideEffect: String
    public let requiresApproval: Bool
    public let argsSchema: [String: JSONValue]
    public let resultSchema: [String: JSONValue]
    public let permissionScopes: [String]

    private enum CodingKeys: String, CodingKey {
        case name
        case capabilityId = "capability_id"
        case kind
        case description
        case sideEffect = "side_effect"
        case requiresApproval = "requires_approval"
        case argsSchema = "args_schema"
        case resultSchema = "result_schema"
        case permissionScopes = "permission_scopes"
    }
}

public struct AgentRuntimeMode: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let label: String
    public let description: String
    public let available: Bool
}

public struct AgentCapabilitiesResponse: Codable, Sendable, Equatable {
    public let schemaVersion: String
    public let deploymentMode: DeploymentMode
    public let maxSteps: Int
    public let runtimeModes: [AgentRuntimeMode]
    public let capabilities: [AgentCapability]
    public let toolContracts: [AgentToolContract]

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case deploymentMode = "deployment_mode"
        case maxSteps = "max_steps"
        case runtimeModes = "runtime_modes"
        case capabilities
        case toolContracts = "tool_contracts"
    }
}
