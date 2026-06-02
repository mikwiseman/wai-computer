import Foundation

/// A third-party MCP server the user has connected as an ingestion source
/// (the outbound "pull data into my brain" direction — distinct from the
/// inbound OAuth connectors that connect external apps TO Wai).
public struct McpIngestionConnection: Codable, Identifiable, Sendable {
    public let id: String
    public let serverLabel: String
    public let serverUrl: String
    public let transport: String
    public let authType: String
    public let hasToken: Bool
    public let allowedTools: [String]?
    public let privacyLevel: String
    public let syncIntervalMinutes: Int
    public let status: String
    public let enabled: Bool
    public let lastSyncAt: String?
    public let lastError: String?
    public let createdAt: String

    private enum CodingKeys: String, CodingKey {
        case id
        case serverLabel = "server_label"
        case serverUrl = "server_url"
        case transport
        case authType = "auth_type"
        case hasToken = "has_token"
        case allowedTools = "allowed_tools"
        case privacyLevel = "privacy_level"
        case syncIntervalMinutes = "sync_interval_minutes"
        case status
        case enabled
        case lastSyncAt = "last_sync_at"
        case lastError = "last_error"
        case createdAt = "created_at"
    }
}
