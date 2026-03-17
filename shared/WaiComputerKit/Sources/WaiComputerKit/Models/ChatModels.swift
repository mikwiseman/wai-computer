import Foundation

// MARK: - Chat Request/Response

/// Request body for POST /api/chat
public struct ChatRequest: Codable, Sendable {
    public let question: String
    public let sessionId: String?
    public let recordingIds: [String]?

    public init(question: String, sessionId: String? = nil, recordingIds: [String]? = nil) {
        self.question = question
        self.sessionId = sessionId
        self.recordingIds = recordingIds
    }

    enum CodingKeys: String, CodingKey {
        case question
        case sessionId = "session_id"
        case recordingIds = "recording_ids"
    }
}

/// A source segment returned in a chat response
public struct ChatSource: Codable, Identifiable, Sendable {
    public let segmentId: String
    public let recordingId: String
    public let recordingTitle: String?
    public let speaker: String?
    public let content: String
    public let startMs: Int?
    public let endMs: Int?

    public var id: String { segmentId }

    enum CodingKeys: String, CodingKey {
        case segmentId = "segment_id"
        case recordingId = "recording_id"
        case recordingTitle = "recording_title"
        case speaker
        case content
        case startMs = "start_ms"
        case endMs = "end_ms"
    }
}

/// Response from POST /api/chat
public struct ChatResponse: Codable, Sendable {
    public let answer: String
    public let sessionId: String
    public let messageId: String
    public let sources: [ChatSource]

    enum CodingKeys: String, CodingKey {
        case answer
        case sessionId = "session_id"
        case messageId = "message_id"
        case sources
    }
}

// MARK: - Chat Sessions

/// Item in GET /api/chat/sessions list
public struct ChatSessionListItem: Codable, Identifiable, Sendable {
    public let id: String
    public let title: String?
    public let recordingIds: [String]?
    public let createdAt: Date
    public let messageCount: Int
    public let pinnedAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case recordingIds = "recording_ids"
        case createdAt = "created_at"
        case messageCount = "message_count"
        case pinnedAt = "pinned_at"
    }
}

/// A message within a chat session
public struct ChatMessageResponse: Codable, Identifiable, Sendable {
    public let id: String
    public let role: String
    public let content: String
    public let sourceSegmentIds: [String]?
    public let sourceRecordingIds: [String]?
    public let createdAt: Date

    public init(id: String, role: String, content: String, sourceSegmentIds: [String]?, sourceRecordingIds: [String]?, createdAt: Date) {
        self.id = id
        self.role = role
        self.content = content
        self.sourceSegmentIds = sourceSegmentIds
        self.sourceRecordingIds = sourceRecordingIds
        self.createdAt = createdAt
    }

    enum CodingKeys: String, CodingKey {
        case id
        case role
        case content
        case sourceSegmentIds = "source_segment_ids"
        case sourceRecordingIds = "source_recording_ids"
        case createdAt = "created_at"
    }
}

/// Request body for PATCH /api/chat/sessions/{id}
public struct RenameSessionRequest: Codable, Sendable {
    public let title: String?

    public init(title: String?) {
        self.title = title
    }
}

/// Response from PATCH /api/chat/sessions/{id}
public struct RenameSessionResponse: Codable, Sendable {
    public let id: String
    public let title: String?
}

/// Full session detail from GET /api/chat/sessions/{id}
public struct ChatSessionDetail: Codable, Identifiable, Sendable {
    public let id: String
    public let title: String?
    public let recordingIds: [String]?
    public let createdAt: Date
    public let messages: [ChatMessageResponse]

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case recordingIds = "recording_ids"
        case createdAt = "created_at"
        case messages
    }
}
