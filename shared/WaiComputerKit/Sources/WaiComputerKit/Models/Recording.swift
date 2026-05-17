import Foundation

/// Recording types
public enum RecordingType: String, Codable, Sendable, CaseIterable {
    case meeting
    case note
    case reflection
}

/// Recording upload / processing lifecycle.
public enum RecordingStatus: String, Codable, Sendable, CaseIterable {
    case pendingUpload = "pending_upload"
    case uploading
    case processing
    case ready
    case failed

    public var label: String {
        switch self {
        case .pendingUpload:
            return "Waiting to Sync"
        case .uploading:
            return "Syncing in Background"
        case .processing:
            return "Processing"
        case .ready:
            return "Ready"
        case .failed:
            return "Needs Attention"
        }
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        let rawStatus = try container.decode(String.self)
        guard let status = RecordingStatus(rawValue: rawStatus) else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Unknown RecordingStatus value: '\(rawStatus)'"
            )
        }
        self = status
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
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

/// Public share link returned when a recording owner creates a web share.
public struct RecordingShareLink: Codable, Sendable {
    public let recordingId: String
    public let token: String
    public let url: URL
    public let createdAt: Date

    public init(recordingId: String, token: String, url: URL, createdAt: Date = Date()) {
        self.recordingId = recordingId
        self.token = token
        self.url = url
        self.createdAt = createdAt
    }

    private enum CodingKeys: String, CodingKey {
        case recordingId = "recording_id"
        case token
        case url
        case createdAt = "created_at"
    }
}

/// Recording model
public struct Recording: Codable, Identifiable, Sendable {
    public let id: String
    public var title: String?
    public let type: RecordingType
    public let audioUrl: String?
    public let status: RecordingStatus
    public let failureCode: String?
    public let failureMessage: String?
    public let uploadedAt: Date?
    public let durationSeconds: Int?
    public let language: String?
    public let folderId: String?
    public let deletedAt: Date?
    public let starredAt: Date?
    public let createdAt: Date

    public init(
        id: String,
        title: String? = nil,
        type: RecordingType,
        audioUrl: String? = nil,
        status: RecordingStatus = .pendingUpload,
        failureCode: String? = nil,
        failureMessage: String? = nil,
        uploadedAt: Date? = nil,
        durationSeconds: Int? = nil,
        language: String? = nil,
        folderId: String? = nil,
        deletedAt: Date? = nil,
        starredAt: Date? = nil,
        createdAt: Date = Date()
    ) {
        self.id = id
        self.title = title
        self.type = type
        self.audioUrl = audioUrl
        self.status = status
        self.failureCode = failureCode
        self.failureMessage = failureMessage
        self.uploadedAt = uploadedAt
        self.durationSeconds = durationSeconds
        self.language = language
        self.folderId = folderId
        self.deletedAt = deletedAt
        self.starredAt = starredAt
        self.createdAt = createdAt
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case title
        case type
        case audioUrl = "audio_url"
        case status
        case failureCode = "failure_code"
        case failureMessage = "failure_message"
        case uploadedAt = "uploaded_at"
        case durationSeconds = "duration_seconds"
        case language
        case folderId = "folder_id"
        case deletedAt = "deleted_at"
        case starredAt = "starred_at"
        case createdAt = "created_at"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        title = try container.decodeIfPresent(String.self, forKey: .title)
        type = try container.decode(RecordingType.self, forKey: .type)
        audioUrl = try container.decodeIfPresent(String.self, forKey: .audioUrl)
        let decodedStatus = try container.decodeIfPresent(RecordingStatus.self, forKey: .status)
        status = decodedStatus ?? .pendingUpload
        failureCode = try container.decodeIfPresent(String.self, forKey: .failureCode)
        failureMessage = try container.decodeIfPresent(String.self, forKey: .failureMessage)
        uploadedAt = try container.decodeIfPresent(Date.self, forKey: .uploadedAt)
        durationSeconds = try container.decodeIfPresent(Int.self, forKey: .durationSeconds)
        language = try container.decodeIfPresent(String.self, forKey: .language)
        folderId = try container.decodeIfPresent(String.self, forKey: .folderId)
        deletedAt = try container.decodeIfPresent(Date.self, forKey: .deletedAt)
        starredAt = try container.decodeIfPresent(Date.self, forKey: .starredAt)
        createdAt = try container.decode(Date.self, forKey: .createdAt)
    }
}

/// A key moment / highlight from a recording.
public struct RecordingHighlight: Codable, Identifiable, Sendable {
    public let id: String
    public let recordingId: String
    public let category: String
    public let title: String
    public let description: String?
    public let speaker: String?
    public let startMs: Int?
    public let endMs: Int?
    public let importance: String

    private enum CodingKeys: String, CodingKey {
        case id
        case recordingId = "recording_id"
        case category
        case title
        case description
        case speaker
        case startMs = "start_ms"
        case endMs = "end_ms"
        case importance
    }
}

/// Recording with full details including segments and summary
public struct RecordingDetail: Codable, Identifiable, Sendable {
    public let id: String
    public var title: String?
    public let type: RecordingType
    public let audioUrl: String?
    public let status: RecordingStatus
    public let failureCode: String?
    public let failureMessage: String?
    public let uploadedAt: Date?
    public let durationSeconds: Int?
    public let language: String?
    public let folderId: String?
    public let deletedAt: Date?
    public let starredAt: Date?
    public let createdAt: Date
    public let segments: [Segment]
    public let summary: Summary?
    public let actionItems: [ActionItem]
    public let highlights: [RecordingHighlight]

    public init(
        id: String,
        title: String? = nil,
        type: RecordingType,
        audioUrl: String? = nil,
        status: RecordingStatus = .pendingUpload,
        failureCode: String? = nil,
        failureMessage: String? = nil,
        uploadedAt: Date? = nil,
        durationSeconds: Int? = nil,
        language: String? = nil,
        folderId: String? = nil,
        deletedAt: Date? = nil,
        starredAt: Date? = nil,
        createdAt: Date = Date(),
        segments: [Segment] = [],
        summary: Summary? = nil,
        actionItems: [ActionItem] = [],
        highlights: [RecordingHighlight] = []
    ) {
        self.id = id
        self.title = title
        self.type = type
        self.audioUrl = audioUrl
        self.status = status
        self.failureCode = failureCode
        self.failureMessage = failureMessage
        self.uploadedAt = uploadedAt
        self.durationSeconds = durationSeconds
        self.language = language
        self.folderId = folderId
        self.deletedAt = deletedAt
        self.starredAt = starredAt
        self.createdAt = createdAt
        self.segments = segments
        self.summary = summary
        self.actionItems = actionItems
        self.highlights = highlights
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case title
        case type
        case audioUrl = "audio_url"
        case status
        case failureCode = "failure_code"
        case failureMessage = "failure_message"
        case uploadedAt = "uploaded_at"
        case durationSeconds = "duration_seconds"
        case language
        case folderId = "folder_id"
        case deletedAt = "deleted_at"
        case starredAt = "starred_at"
        case createdAt = "created_at"
        case segments
        case summary
        case actionItems = "action_items"
        case highlights
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        title = try container.decodeIfPresent(String.self, forKey: .title)
        type = try container.decode(RecordingType.self, forKey: .type)
        audioUrl = try container.decodeIfPresent(String.self, forKey: .audioUrl)
        let decodedStatus = try container.decodeIfPresent(RecordingStatus.self, forKey: .status)
        status = decodedStatus ?? .pendingUpload
        failureCode = try container.decodeIfPresent(String.self, forKey: .failureCode)
        failureMessage = try container.decodeIfPresent(String.self, forKey: .failureMessage)
        uploadedAt = try container.decodeIfPresent(Date.self, forKey: .uploadedAt)
        durationSeconds = try container.decodeIfPresent(Int.self, forKey: .durationSeconds)
        language = try container.decodeIfPresent(String.self, forKey: .language)
        folderId = try container.decodeIfPresent(String.self, forKey: .folderId)
        deletedAt = try container.decodeIfPresent(Date.self, forKey: .deletedAt)
        starredAt = try container.decodeIfPresent(Date.self, forKey: .starredAt)
        createdAt = try container.decode(Date.self, forKey: .createdAt)
        segments = try container.decodeIfPresent([Segment].self, forKey: .segments) ?? []
        summary = try container.decodeIfPresent(Summary.self, forKey: .summary)
        actionItems = try container.decodeIfPresent([ActionItem].self, forKey: .actionItems) ?? []
        highlights = try container.decodeIfPresent([RecordingHighlight].self, forKey: .highlights) ?? []
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

public extension Recording {
    var isFailedUpload: Bool {
        status == .failed
    }

    var failurePreviewText: String? {
        UserFacingErrorFormatter.previewMessage(failureMessage, context: .recording)
    }

    func statusDisplayText(hasLocalRecoveryBackup: Bool = false) -> String? {
        if hasLocalRecoveryBackup && !isFailedUpload {
            return "Saved locally"
        }

        switch status {
        case .failed:
            return "Needs attention"
        case .pendingUpload:
            return "Waiting to sync"
        case .uploading:
            return "Syncing in background"
        case .processing:
            return "Processing"
        case .ready:
            return nil
        }
    }

    var statusDisplayText: String? {
        statusDisplayText()
    }
}
