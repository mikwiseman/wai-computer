import Foundation

public enum InboxSourceKind: String, Codable, Sendable, Hashable {
    case recording
    case item
    case chat
}

public enum InboxStatus: String, Codable, Sendable, Hashable {
    case ready
    case processing
    case needsInput = "needs_input"
    case failed
    case archived
}

public enum InboxStatusFilter: String, Sendable, Hashable {
    case ready
    case processing
    case needsAttention = "needs_attention"
}

public struct InboxDetailRef: Codable, Sendable, Equatable {
    public let kind: InboxSourceKind
    public let id: String

    public init(kind: InboxSourceKind, id: String) {
        self.kind = kind
        self.id = id
    }
}

public struct InboxError: Codable, Sendable, Equatable {
    public let code: String
    public let message: String

    public init(code: String, message: String) {
        self.code = code
        self.message = message
    }
}

public struct InboxRow: Codable, Identifiable, Sendable, Equatable {
    public let id: String
    public let sourceKind: InboxSourceKind
    public let sourceId: String
    public let detail: InboxDetailRef
    public let title: String?
    public let automaticTitlePending: Bool?
    public let sourceLabel: String
    public let sublabel: String?
    public let activityAt: Date
    public let createdAt: Date
    public let updatedAt: Date?
    public let occurredAt: Date?
    public let status: InboxStatus
    public let sourceStatus: String?
    public let error: InboxError?
    public let folderId: String?
    public let durationSeconds: Int?
    public let language: String?
    public let hasSummary: Bool?
    public let isStarred: Bool
    public let isPinned: Bool
    public let isArchived: Bool
    public let isTrashed: Bool

    public init(
        id: String,
        sourceKind: InboxSourceKind,
        sourceId: String,
        detail: InboxDetailRef,
        title: String?,
        sourceLabel: String,
        sublabel: String?,
        activityAt: Date,
        createdAt: Date,
        updatedAt: Date?,
        occurredAt: Date?,
        status: InboxStatus,
        sourceStatus: String?,
        error: InboxError?,
        folderId: String?,
        durationSeconds: Int?,
        language: String?,
        hasSummary: Bool?,
        isStarred: Bool,
        isPinned: Bool,
        isArchived: Bool,
        isTrashed: Bool,
        automaticTitlePending: Bool? = nil
    ) {
        self.id = id
        self.sourceKind = sourceKind
        self.sourceId = sourceId
        self.detail = detail
        self.title = title
        self.automaticTitlePending = automaticTitlePending
        self.sourceLabel = sourceLabel
        self.sublabel = sublabel
        self.activityAt = activityAt
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.occurredAt = occurredAt
        self.status = status
        self.sourceStatus = sourceStatus
        self.error = error
        self.folderId = folderId
        self.durationSeconds = durationSeconds
        self.language = language
        self.hasSummary = hasSummary
        self.isStarred = isStarred
        self.isPinned = isPinned
        self.isArchived = isArchived
        self.isTrashed = isTrashed
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case sourceKind = "source_kind"
        case sourceId = "source_id"
        case detail
        case title
        case automaticTitlePending = "automatic_title_pending"
        case sourceLabel = "source_label"
        case sublabel
        case activityAt = "activity_at"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case occurredAt = "occurred_at"
        case status
        case sourceStatus = "source_status"
        case error
        case folderId = "folder_id"
        case durationSeconds = "duration_seconds"
        case language
        case hasSummary = "has_summary"
        case isStarred = "is_starred"
        case isPinned = "is_pinned"
        case isArchived = "is_archived"
        case isTrashed = "is_trashed"
    }
}

public struct InboxResponse: Codable, Sendable, Equatable {
    public let rows: [InboxRow]
    public let nextCursor: String?
    public let hasMore: Bool

    private enum CodingKeys: String, CodingKey {
        case rows
        case nextCursor = "next_cursor"
        case hasMore = "has_more"
    }
}
