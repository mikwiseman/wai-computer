import Foundation

/// Recording types
public enum RecordingType: String, Codable, Sendable, CaseIterable {
    case meeting
    case note
    case reflection
}

/// Folder for organizing recordings.
public struct Folder: Codable, Identifiable, Sendable {
    public let id: String
    public var name: String
    public let createdAt: Date

    public init(id: String, name: String, createdAt: Date = Date()) {
        self.id = id
        self.name = name
        self.createdAt = createdAt
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case name
        case createdAt = "created_at"
    }
}

/// Recording model
public struct Recording: Codable, Identifiable, Sendable {
    public let id: String
    public var title: String?
    public let type: RecordingType
    public let audioUrl: String?
    public let durationSeconds: Int?
    public let language: String?
    public let folderId: String?
    public let deletedAt: Date?
    public let createdAt: Date

    public init(
        id: String,
        title: String? = nil,
        type: RecordingType,
        audioUrl: String? = nil,
        durationSeconds: Int? = nil,
        language: String? = nil,
        folderId: String? = nil,
        deletedAt: Date? = nil,
        createdAt: Date = Date()
    ) {
        self.id = id
        self.title = title
        self.type = type
        self.audioUrl = audioUrl
        self.durationSeconds = durationSeconds
        self.language = language
        self.folderId = folderId
        self.deletedAt = deletedAt
        self.createdAt = createdAt
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case title
        case type
        case audioUrl = "audio_url"
        case durationSeconds = "duration_seconds"
        case language
        case folderId = "folder_id"
        case deletedAt = "deleted_at"
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
    public let folderId: String?
    public let deletedAt: Date?
    public let createdAt: Date
    public let segments: [Segment]
    public let summary: Summary?
    public let actionItems: [ActionItem]

    public init(
        id: String,
        title: String? = nil,
        type: RecordingType,
        audioUrl: String? = nil,
        durationSeconds: Int? = nil,
        language: String? = nil,
        folderId: String? = nil,
        deletedAt: Date? = nil,
        createdAt: Date = Date(),
        segments: [Segment] = [],
        summary: Summary? = nil,
        actionItems: [ActionItem] = []
    ) {
        self.id = id
        self.title = title
        self.type = type
        self.audioUrl = audioUrl
        self.durationSeconds = durationSeconds
        self.language = language
        self.folderId = folderId
        self.deletedAt = deletedAt
        self.createdAt = createdAt
        self.segments = segments
        self.summary = summary
        self.actionItems = actionItems
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case title
        case type
        case audioUrl = "audio_url"
        case durationSeconds = "duration_seconds"
        case language
        case folderId = "folder_id"
        case deletedAt = "deleted_at"
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
    public var folderId: String?

    public init(
        title: String? = nil,
        type: RecordingType = .note,
        language: String = "en",
        folderId: String? = nil
    ) {
        self.title = title
        self.type = type
        self.language = language
        self.folderId = folderId
    }

    private enum CodingKeys: String, CodingKey {
        case title
        case type
        case language
        case folderId = "folder_id"
    }
}
