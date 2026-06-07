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
    // Catalog provenance + freshness (optional so older payloads still decode).
    public let catalogId: String?
    public let sourceType: String?
    public let backfillDepth: String?
    public let itemCount: Int?
    public let lastSuccessAt: String?
    public let secondsSinceSync: Int?
    public let consecutiveFailures: Int?
    public let lastErrorCode: String?
    public let reconnectRequired: Bool?

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
        case catalogId = "catalog_id"
        case sourceType = "source_type"
        case backfillDepth = "backfill_depth"
        case itemCount = "item_count"
        case lastSuccessAt = "last_success_at"
        case secondsSinceSync = "seconds_since_sync"
        case consecutiveFailures = "consecutive_failures"
        case lastErrorCode = "last_error_code"
        case reconnectRequired = "reconnect_required"
    }
}
