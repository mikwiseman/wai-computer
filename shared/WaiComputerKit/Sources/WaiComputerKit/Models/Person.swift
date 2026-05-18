import Foundation

/// A known speaker the user has assigned in their address book.
public struct Person: Codable, Identifiable, Sendable {
    public let id: String
    public let displayName: String
    public let color: String?
    public let aliases: [String]?
    public let voiceprintCount: Int
    public let createdAt: String
    public let updatedAt: String

    public init(
        id: String,
        displayName: String,
        color: String? = nil,
        aliases: [String]? = nil,
        voiceprintCount: Int = 0,
        createdAt: String,
        updatedAt: String
    ) {
        self.id = id
        self.displayName = displayName
        self.color = color
        self.aliases = aliases
        self.voiceprintCount = voiceprintCount
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case displayName = "display_name"
        case color
        case aliases
        case voiceprintCount = "voiceprint_count"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}
