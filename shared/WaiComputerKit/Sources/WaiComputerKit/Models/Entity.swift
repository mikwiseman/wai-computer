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
    /// How many sources mention this entity — powers Pages ranking + "N sources".
    public let mentionCount: Int?
    public let sourceCount: Int?

    public init(
        id: String,
        type: EntityType,
        name: String,
        metadata: [String: String]? = nil,
        mentionCount: Int? = nil,
        sourceCount: Int? = nil
    ) {
        self.id = id
        self.type = type
        self.name = name
        self.metadata = metadata
        self.mentionCount = mentionCount
        self.sourceCount = sourceCount
    }

    private enum CodingKeys: String, CodingKey {
        case id, type, name, metadata
        case mentionCount = "mention_count"
        case sourceCount = "source_count"
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
