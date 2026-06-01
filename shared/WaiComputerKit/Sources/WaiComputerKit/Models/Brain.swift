import Foundation

/// A long-term memory block rendered as a wiki section (human/topics/preferences).
public struct BrainMemorySection: Codable, Identifiable, Sendable {
    public let label: String
    public let body: String
    public let updatedAt: String?

    public var id: String { label }

    private enum CodingKeys: String, CodingKey {
        case label
        case body
        case updatedAt = "updated_at"
    }
}

/// One outgoing relation on an entity page.
public struct BrainEntityRelation: Codable, Sendable {
    public let relationType: String?
    public let targetName: String
    public let targetType: String
    public let context: String?

    private enum CodingKeys: String, CodingKey {
        case relationType = "relation_type"
        case targetName = "target_name"
        case targetType = "target_type"
        case context
    }
}

/// An entity page in the compiled-wiki Brain view.
public struct BrainEntityPage: Codable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let type: String
    public let relations: [BrainEntityRelation]
}

/// The compiled-wiki projection of what the brain durably knows.
public struct BrainProjection: Codable, Sendable {
    public let memorySections: [BrainMemorySection]
    public let entityPages: [BrainEntityPage]
    public let entityCount: Int

    private enum CodingKeys: String, CodingKey {
        case memorySections = "memory_sections"
        case entityPages = "entity_pages"
        case entityCount = "entity_count"
    }
}
