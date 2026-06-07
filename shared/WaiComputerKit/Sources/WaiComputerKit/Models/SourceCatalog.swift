import Foundation

/// The Hermes-style data-source catalog (GET /api/source-catalog).
/// Keep in sync with backend `app/core/source_catalog.py` and web
/// `web/src/lib/types.ts` (SourceCatalog*). `authType`/`status` stay plain
/// strings so a new server value never breaks an older client's decoder.
public struct SourceCatalogCategory: Codable, Identifiable, Sendable {
    public let id: String
    public let nameEn: String
    public let nameRu: String

    private enum CodingKeys: String, CodingKey {
        case id
        case nameEn = "name_en"
        case nameRu = "name_ru"
    }
}

public struct SourceCatalogEntry: Codable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let category: String
    public let icon: String
    public let taglineEn: String
    public let taglineRu: String
    public let syncsEn: String
    public let syncsRu: String
    public let authType: String      // none | pat | oauth
    public let serverUrl: String
    public let transport: String
    public let defaultSyncIntervalMinutes: Int
    public let setupHintEn: String?
    public let setupHintRu: String?
    public let status: String        // available | coming_soon

    public var isAvailable: Bool { status == "available" }

    private enum CodingKeys: String, CodingKey {
        case id, name, category, icon, transport, status
        case taglineEn = "tagline_en"
        case taglineRu = "tagline_ru"
        case syncsEn = "syncs_en"
        case syncsRu = "syncs_ru"
        case authType = "auth_type"
        case serverUrl = "server_url"
        case defaultSyncIntervalMinutes = "default_sync_interval_minutes"
        case setupHintEn = "setup_hint_en"
        case setupHintRu = "setup_hint_ru"
    }
}

public struct SourceCatalog: Codable, Sendable {
    public let version: Int
    public let customSupported: Bool
    public let backfillDepths: [String]
    public let defaultBackfillDepth: String
    public let categories: [SourceCatalogCategory]
    public let entries: [SourceCatalogEntry]

    private enum CodingKeys: String, CodingKey {
        case version
        case customSupported = "custom_supported"
        case backfillDepths = "backfill_depths"
        case defaultBackfillDepth = "default_backfill_depth"
        case categories
        case entries
    }
}
