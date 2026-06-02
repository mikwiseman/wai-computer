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

// MARK: - Knowledge graph (GET /api/brain/graph)

/// A node in the knowledge graph — an entity, or an item/recording source node.
public struct BrainGraphNode: Codable, Identifiable, Sendable {
    public let id: String
    public let label: String
    public let kind: String  // person | topic | project | item | recording
    public let degree: Int
}

/// A graph edge: ``cooccurrence`` (entity<->entity) or ``mention`` (source->entity).
public struct BrainGraphEdge: Codable, Sendable {
    public let source: String
    public let target: String
    public let type: String
    public let weight: Double
}

public struct BrainGraph: Codable, Sendable {
    public let nodes: [BrainGraphNode]
    public let edges: [BrainGraphEdge]
    public let stats: [String: Int]
}

// MARK: - Entity wiki page (GET /api/entities/{id}/page)

/// A source backlink on an entity's wiki page.
public struct EntityPageSource: Codable, Identifiable, Sendable {
    public let sourceKind: String
    public let sourceId: String
    public let title: String
    public let context: String?

    public var id: String { "\(sourceKind):\(sourceId)" }

    private enum CodingKeys: String, CodingKey {
        case sourceKind = "source_kind"
        case sourceId = "source_id"
        case title
        case context
    }
}

/// A related entity (co-occurrence) on a wiki page.
public struct EntityPageRelated: Codable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let type: String
    public let shared: Int
}

public struct EntityPage: Codable, Sendable {
    public let id: String
    public let name: String
    public let type: String
    public let mentionCount: Int
    public let sources: [EntityPageSource]
    public let related: [EntityPageRelated]

    private enum CodingKeys: String, CodingKey {
        case id, name, type
        case mentionCount = "mention_count"
        case sources, related
    }
}
