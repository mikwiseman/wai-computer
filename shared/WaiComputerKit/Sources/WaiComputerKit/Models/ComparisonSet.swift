import Foundation

/// A column in a comparison table (LLM-induced).
public struct ComparisonColumn: Codable, Identifiable, Sendable {
    public let name: String
    public let type: String
    public var id: String { name }
}

/// One item's row in a comparison table. ``values`` maps column name -> value
/// (stringified by the backend; nil means "not specified" — never fabricated).
public struct ComparisonRow: Codable, Identifiable, Sendable {
    public let itemId: String
    public let title: String
    public let values: [String: String?]

    public var id: String { itemId }

    private enum CodingKeys: String, CodingKey {
        case itemId = "item_id"
        case title
        case values
    }
}

/// A multi-item comparison table (forward several items -> compare).
public struct ComparisonSet: Codable, Identifiable, Sendable {
    public let id: String
    public let title: String?
    public let itemIds: [String]
    public let columns: [ComparisonColumn]?
    public let rows: [ComparisonRow]?
    public let schemaRationale: String?
    public let status: String
    public let createdAt: String

    private enum CodingKeys: String, CodingKey {
        case id
        case title
        case itemIds = "item_ids"
        case columns
        case rows
        case schemaRationale = "schema_rationale"
        case status
        case createdAt = "created_at"
    }
}

/// A lightweight comparison-set list entry.
public struct ComparisonListEntry: Codable, Identifiable, Sendable {
    public let id: String
    public let title: String?
    public let itemCount: Int
    public let status: String
    public let createdAt: String

    private enum CodingKeys: String, CodingKey {
        case id
        case title
        case itemCount = "item_count"
        case status
        case createdAt = "created_at"
    }
}
