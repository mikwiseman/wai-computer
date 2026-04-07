import Foundation

/// Search result item
public struct SearchResult: Codable, Identifiable, Sendable {
    public let recordingId: String
    public let recordingTitle: String?
    public let recordingType: RecordingType
    public let segmentId: String
    public let speaker: String?
    public let content: String
    public let startMs: Int?
    public let endMs: Int?
    public let score: Double

    public var id: String { segmentId }

    private enum CodingKeys: String, CodingKey {
        case recordingId = "recording_id"
        case recordingTitle = "recording_title"
        case recordingType = "recording_type"
        case segmentId = "segment_id"
        case speaker
        case content
        case startMs = "start_ms"
        case endMs = "end_ms"
        case score
    }
}

/// Search response
public struct SearchResponse: Codable, Sendable {
    public let results: [SearchResult]
    public let total: Int
}
