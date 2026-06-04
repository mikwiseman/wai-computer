import Foundation

public struct Reminder: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let text: String
    public let dueAt: Date
    public let status: String
    public let source: String
    public let sourceRef: String?
    public let sentAt: Date?
    public let failedAt: Date?
    public let error: String?
    public let metadata: [String: JSONValue]
    public let createdAt: Date
    public let updatedAt: Date

    private enum CodingKeys: String, CodingKey {
        case id
        case text
        case dueAt = "due_at"
        case status
        case source
        case sourceRef = "source_ref"
        case sentAt = "sent_at"
        case failedAt = "failed_at"
        case error
        case metadata
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

public struct ReminderListResponse: Codable, Sendable, Equatable {
    public let reminders: [Reminder]
}

public struct ReminderCreateRequest: Codable, Sendable, Equatable {
    public let text: String
    public let dueAt: Date
    public let source: String?
    public let metadata: [String: JSONValue]?

    public init(
        text: String,
        dueAt: Date,
        source: String? = "mac",
        metadata: [String: JSONValue]? = nil
    ) {
        self.text = text
        self.dueAt = dueAt
        self.source = source
        self.metadata = metadata
    }

    private enum CodingKeys: String, CodingKey {
        case text
        case dueAt = "due_at"
        case source
        case metadata
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(text, forKey: .text)

        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        try container.encode(formatter.string(from: dueAt), forKey: .dueAt)

        try container.encodeIfPresent(source, forKey: .source)
        try container.encodeIfPresent(metadata, forKey: .metadata)
    }
}
