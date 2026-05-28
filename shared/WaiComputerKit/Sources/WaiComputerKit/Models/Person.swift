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

public struct RematchSpeakersResponse: Codable, Sendable {
    public let recordingId: String
    public let updatedClusters: Int
    public let matchedClusters: Int

    public init(recordingId: String, updatedClusters: Int, matchedClusters: Int) {
        self.recordingId = recordingId
        self.updatedClusters = updatedClusters
        self.matchedClusters = matchedClusters
    }

    private enum CodingKeys: String, CodingKey {
        case recordingId = "recording_id"
        case updatedClusters = "updated_clusters"
        case matchedClusters = "matched_clusters"
    }
}
