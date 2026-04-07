import Foundation

// MARK: - Agent Chat

/// Request body for POST /api/agent/chat
public struct AgentChatRequest: Codable, Sendable {
    public let message: String
    public let sessionId: String?
    public let voiceTranscript: String?

    public init(message: String, sessionId: String? = nil, voiceTranscript: String? = nil) {
        self.message = message
        self.sessionId = sessionId
        self.voiceTranscript = voiceTranscript
    }

    enum CodingKeys: String, CodingKey {
        case message
        case sessionId = "session_id"
        case voiceTranscript = "voice_transcript"
    }
}

/// Response from POST /api/agent/chat
public struct AgentChatResponse: Codable, Sendable {
    public let response: String
    public let intent: String
    public let modelUsed: String
    public let sessionId: String
    public let toolCalls: Int
    public let inputTokens: Int
    public let outputTokens: Int

    enum CodingKeys: String, CodingKey {
        case response
        case intent
        case modelUsed = "model_used"
        case sessionId = "session_id"
        case toolCalls = "tool_calls"
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
    }
}

// MARK: - Digital Agents

/// A digital agent from GET /api/agents
public struct DigitalAgent: Codable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let description: String
    public let scheduleType: String
    public let cronExpression: String?
    public let status: String
    public let deliveryChannel: String
    public let runCount: Int
    public let errorCount: Int
    public let lastRunAt: Date?
    public let nextRunAt: Date?
    public let lastResult: String?
    public let lastError: String?
    public let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case description
        case scheduleType = "schedule_type"
        case cronExpression = "cron_expression"
        case status
        case deliveryChannel = "delivery_channel"
        case runCount = "run_count"
        case errorCount = "error_count"
        case lastRunAt = "last_run_at"
        case nextRunAt = "next_run_at"
        case lastResult = "last_result"
        case lastError = "last_error"
        case createdAt = "created_at"
    }
}

/// Request body for POST /api/agents
public struct CreateAgentRequest: Codable, Sendable {
    public let description: String

    public init(description: String) {
        self.description = description
    }
}

/// Response from POST /api/agents/{id}/run
public struct AgentRunResponse: Codable, Sendable {
    public let status: String
    public let agentId: String

    enum CodingKeys: String, CodingKey {
        case status
        case agentId = "agent_id"
    }
}

/// Request body for PATCH /api/agents/{id}
struct UpdateAgentRequest: Codable, Sendable {
    let status: String?

    init(status: String? = nil) {
        self.status = status
    }
}
