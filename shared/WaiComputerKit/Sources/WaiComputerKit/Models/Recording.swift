import Foundation

/// Recording types
public enum RecordingType: String, Codable, Sendable, CaseIterable {
    case meeting
    case note
    case reflection
}

/// Recording model
public struct Recording: Codable, Identifiable, Sendable {
    public let id: String
    public var title: String?
    public let type: RecordingType
    public let audioUrl: String?
    public let durationSeconds: Int?
    public let language: String?
    public let createdAt: Date

    public init(
        id: String,
        title: String? = nil,
        type: RecordingType,
        audioUrl: String? = nil,
        durationSeconds: Int? = nil,
        language: String? = nil,
        createdAt: Date = Date()
    ) {
        self.id = id
        self.title = title
        self.type = type
        self.audioUrl = audioUrl
        self.durationSeconds = durationSeconds
        self.language = language
        self.createdAt = createdAt
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case title
        case type
        case audioUrl = "audio_url"
        case durationSeconds = "duration_seconds"
        case language
        case createdAt = "created_at"
    }
}

/// Recording with full details including segments and summary
public struct RecordingDetail: Codable, Identifiable, Sendable {
    public let id: String
    public var title: String?
    public let type: RecordingType
    public let audioUrl: String?
    public let durationSeconds: Int?
    public let language: String?
    public let createdAt: Date
    public let segments: [Segment]
    public let summary: Summary?
    public let actionItems: [ActionItem]

    private enum CodingKeys: String, CodingKey {
        case id
        case title
        case type
        case audioUrl = "audio_url"
        case durationSeconds = "duration_seconds"
        case language
        case createdAt = "created_at"
        case segments
        case summary
        case actionItems = "action_items"
    }
}

/// Request to create a new recording
public struct CreateRecordingRequest: Codable, Sendable {
    public var title: String?
    public var type: RecordingType
    public var language: String

    public init(title: String? = nil, type: RecordingType = .note, language: String = "en") {
        self.title = title
        self.type = type
        self.language = language
    }
}
