import Foundation

/// Transcript segment with speaker info
public struct Segment: Codable, Identifiable, Sendable {
    public let id: String
    public let speaker: String?
    public let content: String
    public let startMs: Int?
    public let endMs: Int?
    public let confidence: Double?

    public init(
        id: String,
        speaker: String? = nil,
        content: String,
        startMs: Int? = nil,
        endMs: Int? = nil,
        confidence: Double? = nil
    ) {
        self.id = id
        self.speaker = speaker
        self.content = content
        self.startMs = startMs
        self.endMs = endMs
        self.confidence = confidence
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case speaker
        case content
        case startMs = "start_ms"
        case endMs = "end_ms"
        case confidence
    }

    /// Duration in milliseconds
    public var durationMs: Int? {
        guard let start = startMs, let end = endMs else { return nil }
        return end - start
    }

    /// Formatted timestamp (MM:SS)
    public var formattedTimestamp: String {
        guard let start = startMs else { return "--:--" }
        let seconds = start / 1000
        let minutes = seconds / 60
        let remainingSeconds = seconds % 60
        return String(format: "%02d:%02d", minutes, remainingSeconds)
    }
}

/// Summary of a recording
public struct Summary: Codable, Sendable {
    public let summary: String?
    public let keyPoints: [String]?
    public let decisions: [Decision]?
    public let topics: [String]?
    public let peopleMentioned: [String]?
    public let sentiment: String?

    public init(
        summary: String? = nil,
        keyPoints: [String]? = nil,
        decisions: [Decision]? = nil,
        topics: [String]? = nil,
        peopleMentioned: [String]? = nil,
        sentiment: String? = nil
    ) {
        self.summary = summary
        self.keyPoints = keyPoints
        self.decisions = decisions
        self.topics = topics
        self.peopleMentioned = peopleMentioned
        self.sentiment = sentiment
    }

    private enum CodingKeys: String, CodingKey {
        case summary
        case keyPoints = "key_points"
        case decisions
        case topics
        case peopleMentioned = "people_mentioned"
        case sentiment
    }
}

/// Decision extracted from transcript
public struct Decision: Codable, Sendable {
    public let decision: String
    public let context: String?

    public init(decision: String, context: String? = nil) {
        self.decision = decision
        self.context = context
    }
}

/// Action item
public struct ActionItem: Codable, Identifiable, Sendable {
    public let id: String
    public let recordingId: String?
    public let task: String
    public let owner: String?
    public let dueDate: String?
    public let priority: Priority?
    public var status: Status
    public let createdAt: String?

    public enum Priority: String, Codable, Sendable, CaseIterable {
        case high
        case medium
        case low
    }

    public enum Status: String, Codable, Sendable, CaseIterable {
        case pending
        case inProgress = "in_progress"
        case completed
        case cancelled
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case recordingId = "recording_id"
        case task
        case owner
        case dueDate = "due_date"
        case priority
        case status
        case createdAt = "created_at"
    }
}
