import Foundation

/// Result of `POST /api/items/upload`. Documents extract inline into an `Item`
/// (201); audio/video are staged and transcribed into a Recording in the
/// background (202) — there is no `Item` to poll, it surfaces under Recordings.
public enum ItemUploadOutcome: Sendable {
    case item(Item)
    case recording(status: String)
}

/// One row of an item's key-moments table (the hero "forward → table" output).
public struct KeyMoment: Codable, Identifiable, Sendable {
    public let timestamp: String?
    public let moment: String
    public let whyItMatters: String
    public let quote: String?
    public let importance: String
    public let startMs: Int?
    public let endMs: Int?

    public var id: String { "\(timestamp ?? "")-\(moment)" }

    private enum CodingKeys: String, CodingKey {
        case timestamp
        case moment
        case whyItMatters = "why_it_matters"
        case quote
        case importance
        case startMs = "start_ms"
        case endMs = "end_ms"
    }
}

/// AI summary + key-moments table for a non-recording Item.
public struct ItemSummary: Codable, Sendable {
    public let summary: String?
    public let keyPoints: [String]?
    public let topics: [String]?
    public let keyMoments: [KeyMoment]?
    public let sentiment: String?

    private enum CodingKeys: String, CodingKey {
        case summary
        case keyPoints = "key_points"
        case topics
        case keyMoments = "key_moments"
        case sentiment
    }
}

public struct ItemError: Codable, Sendable {
    public let code: String
    public let message: String
}

/// Any non-recording piece of content in the second brain (article, link,
/// note, PDF, MCP-pulled resource).
public struct Item: Codable, Identifiable, Sendable {
    public let id: String
    public let source: String
    public let sourceRef: String?
    public let url: String?
    public let kind: String
    public let title: String?
    public let body: String?
    public let occurredAt: String?
    public let state: String
    public let status: String
    public let error: ItemError?
    public let folderId: String?
    public let createdAt: String
    public let summary: ItemSummary?

    private enum CodingKeys: String, CodingKey {
        case id
        case source
        case sourceRef = "source_ref"
        case url
        case kind
        case title
        case body
        case occurredAt = "occurred_at"
        case state
        case status
        case error
        case folderId = "folder_id"
        case createdAt = "created_at"
        case summary
    }
}

/// A lightweight row in the unified content feed.
public struct ItemListEntry: Codable, Identifiable, Sendable {
    public let id: String
    public let source: String
    public let url: String?
    public let kind: String
    public let title: String?
    public let state: String
    public let status: String
    public let error: ItemError?
    public let folderId: String?
    public let occurredAt: String?
    public let createdAt: String
    public let hasSummary: Bool

    private enum CodingKeys: String, CodingKey {
        case id
        case source
        case url
        case kind
        case title
        case state
        case status
        case error
        case folderId = "folder_id"
        case occurredAt = "occurred_at"
        case createdAt = "created_at"
        case hasSummary = "has_summary"
    }
}

public struct ItemListResponse: Codable, Sendable {
    public let items: [ItemListEntry]
    public let total: Int
}

/// One hit in the unified (recordings + items) search.
public struct UnifiedHit: Codable, Identifiable, Sendable {
    public let sourceKind: String  // "recording" | "item"
    public let parentId: String
    public let chunkId: String
    public let title: String?
    public let kind: String
    public let snippet: String
    public let score: Double
    public let createdAt: String?

    public var id: String { chunkId }

    private enum CodingKeys: String, CodingKey {
        case sourceKind = "source_kind"
        case parentId = "parent_id"
        case chunkId = "chunk_id"
        case title
        case kind
        case snippet
        case score
        case createdAt = "created_at"
    }
}

public struct UnifiedSearchResponse: Codable, Sendable {
    public let results: [UnifiedHit]
    public let total: Int
}
