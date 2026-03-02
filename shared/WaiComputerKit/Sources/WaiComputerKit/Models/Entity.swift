import Foundation

/// Entity type in knowledge graph
public enum EntityType: String, Codable, Sendable, CaseIterable {
    case person
    case topic
    case project
    case organization
}

/// Entity in the knowledge graph
public struct Entity: Codable, Identifiable, Sendable {
    public let id: String
    public let type: EntityType
    public let name: String
    public let metadata: [String: String]?

    public init(id: String, type: EntityType, name: String, metadata: [String: String]? = nil) {
        self.id = id
        self.type = type
        self.name = name
        self.metadata = metadata
    }
}

/// Entity with relations
public struct EntityDetail: Codable, Identifiable, Sendable {
    public let id: String
    public let type: EntityType
    public let name: String
    public let metadata: [String: String]?
    public let relations: [EntityRelation]
}

/// Relation between entities
public struct EntityRelation: Codable, Identifiable, Sendable {
    public let id: String
    public let targetId: String
    public let targetName: String
    public let targetType: EntityType
    public let relationType: String?
    public let context: String?

    private enum CodingKeys: String, CodingKey {
        case id
        case targetId = "target_id"
        case targetName = "target_name"
        case targetType = "target_type"
        case relationType = "relation_type"
        case context
    }
}
