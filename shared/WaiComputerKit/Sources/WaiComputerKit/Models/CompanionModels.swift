import Foundation

public struct CompanionScope: Codable, Sendable, Equatable {
    public var recordingIds: [String]?
    public var brainSpaceId: String?
    public var folderIds: [String]?
    public var types: [String]?
    public var speakers: [String]?
    public var dateFrom: Date?
    public var dateTo: Date?

    public init(
        recordingIds: [String]? = nil,
        brainSpaceId: String? = nil,
        folderIds: [String]? = nil,
        types: [String]? = nil,
        speakers: [String]? = nil,
        dateFrom: Date? = nil,
        dateTo: Date? = nil
    ) {
        self.recordingIds = recordingIds
        self.brainSpaceId = brainSpaceId
        self.folderIds = folderIds
        self.types = types
        self.speakers = speakers
        self.dateFrom = dateFrom
        self.dateTo = dateTo
    }

    enum CodingKeys: String, CodingKey {
        case recordingIds = "recording_ids"
        case brainSpaceId = "brain_space_id"
        case folderIds = "folder_ids"
        case types
        case speakers
        case dateFrom = "date_from"
        case dateTo = "date_to"
    }
}

public struct CompanionConversation: Codable, Sendable, Identifiable, Equatable {
    public let id: String
    public let title: String?
    public let scope: CompanionScope?
    public let pinnedAt: Date?
    public let lastMessageAt: Date?
    public let archivedAt: Date?
    public let createdAt: Date
    public let updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case scope
        case pinnedAt = "pinned_at"
        case lastMessageAt = "last_message_at"
        case archivedAt = "archived_at"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

public struct CompanionCitation: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let segmentId: String?
    public let recordingId: String?
    public let spanStart: Int
    public let spanEnd: Int
    public let citationIndex: Int

    enum CodingKeys: String, CodingKey {
        case id
        case segmentId = "segment_id"
        case recordingId = "recording_id"
        case spanStart = "span_start"
        case spanEnd = "span_end"
        case citationIndex = "citation_index"
    }
}

public enum CompanionMessageRole: String, Codable, Sendable {
    case user
    case assistant
    case tool
}

public struct CompanionMessage: Codable, Sendable, Identifiable, Equatable {
    public let id: String
    public let role: CompanionMessageRole
    public let content: CompanionContent
    public let toolCalls: [CompanionJSONValue]?
    public let citations: [CompanionCitation]
    public let model: String?
    public let inputTokens: Int?
    public let outputTokens: Int?
    public let cachedTokens: Int?
    public let latencyMs: Int?
    public let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id
        case role
        case content
        case toolCalls = "tool_calls"
        case citations
        case model
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
        case cachedTokens = "cached_tokens"
        case latencyMs = "latency_ms"
        case createdAt = "created_at"
    }

    /// Concatenated plain-text view of the message content for rendering.
    public var plainText: String {
        switch content {
        case .text(let value):
            return value
        case .blocks(let blocks):
            return blocks
                .compactMap { block in
                    block["text"].flatMap { $0.stringValue }
                }
                .joined()
        }
    }
}

/// OpenAI Responses API content blocks come as either a string (for user
/// turns) or an array of typed blocks (for assistant turns).
public enum CompanionContent: Codable, Sendable, Equatable {
    case text(String)
    case blocks([[String: CompanionJSONValue]])

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let str = try? container.decode(String.self) {
            self = .text(str)
            return
        }
        let array = try container.decode([[String: CompanionJSONValue]].self)
        self = .blocks(array)
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .text(let value):
            try container.encode(value)
        case .blocks(let blocks):
            try container.encode(blocks)
        }
    }
}

/// Minimal JSON value used to type-erase JSONB columns coming back from the API.
public enum CompanionJSONValue: Codable, Sendable, Equatable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case null
    case array([CompanionJSONValue])
    case object([String: CompanionJSONValue])

    public var stringValue: String? {
        if case .string(let s) = self { return s }
        return nil
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let v = try? container.decode(Bool.self) {
            self = .bool(v)
        } else if let v = try? container.decode(Int.self) {
            self = .int(v)
        } else if let v = try? container.decode(Double.self) {
            self = .double(v)
        } else if let v = try? container.decode(String.self) {
            self = .string(v)
        } else if let v = try? container.decode([CompanionJSONValue].self) {
            self = .array(v)
        } else {
            let dict = try container.decode([String: CompanionJSONValue].self)
            self = .object(dict)
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let v): try container.encode(v)
        case .int(let v): try container.encode(v)
        case .double(let v): try container.encode(v)
        case .bool(let v): try container.encode(v)
        case .null: try container.encodeNil()
        case .array(let v): try container.encode(v)
        case .object(let v): try container.encode(v)
        }
    }
}

public struct CompanionConversationDetail: Codable, Sendable, Equatable {
    public let id: String
    public let title: String?
    public let scope: CompanionScope?
    public let pinnedAt: Date?
    public let lastMessageAt: Date?
    public let archivedAt: Date?
    public let createdAt: Date
    public let updatedAt: Date
    public let messages: [CompanionMessage]

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case scope
        case pinnedAt = "pinned_at"
        case lastMessageAt = "last_message_at"
        case archivedAt = "archived_at"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case messages
    }
}

public struct CompanionConversationList: Codable, Sendable {
    public let chats: [CompanionConversation]
}

// MARK: - SSE events

public enum CompanionStreamEvent: Sendable, Equatable {
    case turnStart(messageId: String, conversationId: String)
    case thinking(text: String)
    case toolCall(callId: String, tool: String)
    case toolResult(callId: String, summary: String, ok: Bool)
    case plan(steps: [CompanionPlanStep])
    case token(text: String)
    case citation(CompanionStreamCitation)
    case memoryUpdated(block: String, operation: String)
    case actionProposed(CompanionActionProposal)
    case actionResult(actionId: String, status: String, detail: String, undoToken: String?)
    case narration(text: String)
    case desktopAction(actionId: String, command: CompanionJSONValue, deviceTarget: String?)
    case done(messageId: String, model: String, latencyMs: Int)
    case error(code: String, message: String)
}

/// One step in the agent's working checklist, emitted by the update_plan tool
/// and rendered as a live plan card with checkmarks.
public struct CompanionPlanStep: Sendable, Equatable, Codable {
    public let title: String
    public let status: String   // pending | in_progress | done

    public init(title: String, status: String) {
        self.title = title
        self.status = status
    }
}

public struct CompanionStreamCitation: Sendable, Equatable {
    public let index: Int
    public let segmentId: String
    public let recordingId: String
    public let startMs: Int?
    public let endMs: Int?
    public let spanStart: Int
    public let spanEnd: Int
}

/// A mutating action (send / external write / desktop action) proposed by the
/// brain and awaiting the user's explicit approval. The side effect has not run.
public struct CompanionActionProposal: Sendable, Equatable {
    public let actionId: String
    public let kind: String          // send | mutate | desktop_action
    public let tool: String
    public let preview: String       // privacy-safe human-readable dry-run
    public let expiresAt: String     // ISO timestamp; timeout == deny
    public let recipient: String?    // resolved display name, never a raw id

    public init(
        actionId: String,
        kind: String,
        tool: String,
        preview: String,
        expiresAt: String,
        recipient: String?
    ) {
        self.actionId = actionId
        self.kind = kind
        self.tool = tool
        self.preview = preview
        self.expiresAt = expiresAt
        self.recipient = recipient
    }
}
