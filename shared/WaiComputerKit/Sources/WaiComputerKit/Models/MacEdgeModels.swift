import Foundation

/// Models for the Mac-edge channel: presence heartbeat, the desktop-action
/// drain queue, and the result back-channel. The Mac client heartbeats, drains
/// approved desktop actions, runs them via the native actuator, and reports
/// the outcome here.

public struct DeviceHeartbeatRequest: Encodable, Sendable {
    public let platform: String
    public let name: String?
    public let deviceId: String?

    enum CodingKeys: String, CodingKey {
        case platform
        case name
        case deviceId = "device_id"
    }

    public init(platform: String, name: String? = nil, deviceId: String? = nil) {
        self.platform = platform
        self.name = name
        self.deviceId = deviceId
    }
}

public struct DeviceHeartbeatResponse: Decodable, Sendable, Equatable {
    public let deviceId: String
    public let online: Bool

    enum CodingKeys: String, CodingKey {
        case deviceId = "device_id"
        case online
    }
}

public struct DesktopActionItem: Decodable, Sendable, Equatable {
    public let actionId: String
    /// Chat-originated actions report to `/api/companion/chats/{chatId}/...`.
    public let chatId: String?
    /// Agent-originated actions report to `/api/agents/{agentId}/runs/{agentRunId}/...`.
    public let agentId: String?
    public let agentRunId: String?
    public let tool: String
    public let args: [String: CompanionJSONValue]
    public let preview: String

    enum CodingKeys: String, CodingKey {
        case actionId = "action_id"
        case chatId = "chat_id"
        case agentId = "agent_id"
        case agentRunId = "agent_run_id"
        case tool
        case args
        case preview
    }

    public init(
        actionId: String,
        chatId: String? = nil,
        agentId: String? = nil,
        agentRunId: String? = nil,
        tool: String,
        args: [String: CompanionJSONValue],
        preview: String
    ) {
        self.actionId = actionId
        self.chatId = chatId
        self.agentId = agentId
        self.agentRunId = agentRunId
        self.tool = tool
        self.args = args
        self.preview = preview
    }
}

public struct DesktopActionQueue: Decodable, Sendable, Equatable {
    public let actions: [DesktopActionItem]
}

public enum DesktopResultStatus: String, Codable, Sendable {
    case executed
    case failed
    case refused
}

public struct DesktopResultRequest: Encodable, Sendable {
    public let deviceId: String
    public let status: DesktopResultStatus
    public let payload: [String: CompanionJSONValue]?

    enum CodingKeys: String, CodingKey {
        case deviceId = "device_id"
        case status
        case payload
    }

    public init(
        deviceId: String,
        status: DesktopResultStatus,
        payload: [String: CompanionJSONValue]? = nil
    ) {
        self.deviceId = deviceId
        self.status = status
        self.payload = payload
    }
}

public struct DesktopResultResponse: Decodable, Sendable, Equatable {
    public let actionId: String
    public let status: String
    public let runStatus: String?

    enum CodingKeys: String, CodingKey {
        case actionId = "action_id"
        case status
        case runStatus = "run_status"
    }

    public init(actionId: String, status: String, runStatus: String? = nil) {
        self.actionId = actionId
        self.status = status
        self.runStatus = runStatus
    }
}
