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
    /// The conversation this action belongs to; the result is reported back
    /// to `/api/companion/chats/{chatId}/actions/{actionId}/desktop_result`.
    public let chatId: String
    public let tool: String
    public let args: [String: CompanionJSONValue]
    public let preview: String

    enum CodingKeys: String, CodingKey {
        case actionId = "action_id"
        case chatId = "chat_id"
        case tool
        case args
        case preview
    }

    public init(
        actionId: String,
        chatId: String,
        tool: String,
        args: [String: CompanionJSONValue],
        preview: String
    ) {
        self.actionId = actionId
        self.chatId = chatId
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
    public let status: DesktopResultStatus
    public let payload: [String: CompanionJSONValue]?

    public init(status: DesktopResultStatus, payload: [String: CompanionJSONValue]? = nil) {
        self.status = status
        self.payload = payload
    }
}

public struct DesktopResultResponse: Decodable, Sendable, Equatable {
    public let actionId: String
    public let status: String

    enum CodingKeys: String, CodingKey {
        case actionId = "action_id"
        case status
    }
}
