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
            return "Pending Save"
        case .uploading:
            return "Syncing"
        case .processing:
            return "Processing"
        case .ready:
            return "Ready"
        case .failed:
            return "Save Failed"
        }
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        let rawStatus = try container.decode(String.self)

        switch rawStatus {
        case "pending", "pending_upload":
            self = .pendingUpload
        case "uploading":
            self = .uploading
        case "uploaded", "processing":
            self = .processing
        case "ready":
            self = .ready
        case "failed", "upload_failed":
            self = .failed
        default:
            self = .pendingUpload
        }
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
        case createdAt = "created_at"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        title = try container.decodeIfPresent(String.self, forKey: .title)
        type = try container.decode(RecordingType.self, forKey: .type)
        audioUrl = try container.decodeIfPresent(String.self, forKey: .audioUrl)
        let decodedStatus = try container.decodeIfPresent(RecordingStatus.self, forKey: .status)
        status = decodedStatus ?? .ready
        failureCode = try container.decodeIfPresent(String.self, forKey: .failureCode)
        failureMessage = try container.decodeIfPresent(String.self, forKey: .failureMessage)
        uploadedAt = try container.decodeIfPresent(Date.self, forKey: .uploadedAt)
        durationSeconds = try container.decodeIfPresent(Int.self, forKey: .durationSeconds)
        language = try container.decodeIfPresent(String.self, forKey: .language)
        folderId = try container.decodeIfPresent(String.self, forKey: .folderId)
        deletedAt = try container.decodeIfPresent(Date.self, forKey: .deletedAt)
        createdAt = try container.decode(Date.self, forKey: .createdAt)
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
    public let createdAt: Date
    public let segments: [Segment]
    public let summary: Summary?
    public let actionItems: [ActionItem]

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
        createdAt: Date = Date(),
        segments: [Segment] = [],
        summary: Summary? = nil,
        actionItems: [ActionItem] = []
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
        case status
        case failureCode = "failure_code"
        case failureMessage = "failure_message"
        case uploadedAt = "uploaded_at"
        case durationSeconds = "duration_seconds"
        case language
        case folderId = "folder_id"
        case deletedAt = "deleted_at"
        case createdAt = "created_at"
        case segments
        case summary
        case actionItems = "action_items"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        title = try container.decodeIfPresent(String.self, forKey: .title)
        type = try container.decode(RecordingType.self, forKey: .type)
        audioUrl = try container.decodeIfPresent(String.self, forKey: .audioUrl)
        let decodedStatus = try container.decodeIfPresent(RecordingStatus.self, forKey: .status)
        status = decodedStatus ?? .ready
        failureCode = try container.decodeIfPresent(String.self, forKey: .failureCode)
        failureMessage = try container.decodeIfPresent(String.self, forKey: .failureMessage)
        uploadedAt = try container.decodeIfPresent(Date.self, forKey: .uploadedAt)
        durationSeconds = try container.decodeIfPresent(Int.self, forKey: .durationSeconds)
        language = try container.decodeIfPresent(String.self, forKey: .language)
        folderId = try container.decodeIfPresent(String.self, forKey: .folderId)
        deletedAt = try container.decodeIfPresent(Date.self, forKey: .deletedAt)
        createdAt = try container.decode(Date.self, forKey: .createdAt)
        segments = try container.decodeIfPresent([Segment].self, forKey: .segments) ?? []
        summary = try container.decodeIfPresent(Summary.self, forKey: .summary)
        actionItems = try container.decodeIfPresent([ActionItem].self, forKey: .actionItems) ?? []
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
        status == .failed || (failureMessage?.isEmpty == false)
    }

    var statusDisplayText: String? {
        switch status {
        case .failed:
            return "Save failed"
        case .pendingUpload:
            return "Pending save"
        case .uploading:
            return "Syncing"
        case .processing:
            return "Processing"
        case .ready:
            return nil
        }
    }
}
