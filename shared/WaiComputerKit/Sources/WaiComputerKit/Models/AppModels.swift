import Foundation

// MARK: - JSON Value

/// A type-erased JSON value for handling arbitrary JSONB data from the backend.
public enum JSONValue: Codable, Sendable, Equatable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()

        if container.decodeNil() {
            self = .null
            return
        }
        if let value = try? container.decode(Bool.self) {
            self = .bool(value)
            return
        }
        if let value = try? container.decode(Int.self) {
            self = .int(value)
            return
        }
        if let value = try? container.decode(Double.self) {
            self = .double(value)
            return
        }
        if let value = try? container.decode(String.self) {
            self = .string(value)
            return
        }
        if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
            return
        }
        if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
            return
        }

        throw DecodingError.dataCorruptedError(
            in: container, debugDescription: "Cannot decode JSONValue"
        )
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .int(let value):
            try container.encode(value)
        case .double(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        case .object(let value):
            try container.encode(value)
        case .array(let value):
            try container.encode(value)
        case .null:
            try container.encodeNil()
        }
    }

    /// Convenience: extract as String if this is a .string case.
    public var stringValue: String? {
        if case .string(let v) = self { return v }
        return nil
    }

    /// Convenience: extract as Int if this is an .int case.
    public var intValue: Int? {
        if case .int(let v) = self { return v }
        return nil
    }

    /// Convenience: extract as Bool if this is a .bool case.
    public var boolValue: Bool? {
        if case .bool(let v) = self { return v }
        return nil
    }

    /// Convenience: extract as dictionary if this is an .object case.
    public var objectValue: [String: JSONValue]? {
        if case .object(let v) = self { return v }
        return nil
    }
}

// MARK: - User Apps (Collections)

public enum AppStatus: String, Codable, Sendable, CaseIterable {
    case draft
    case live
    case archived
}

public enum AppVisibility: String, Codable, Sendable, CaseIterable {
    case `private`
    case unlisted
    case `public`
}

/// A user-created mini-app from GET /api/apps
public struct UserApp: Codable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let displayName: String
    public let description: String?
    public let icon: String?
    public let template: String?
    public let schemaDef: [String: JSONValue]?
    public let appUrl: String?
    public let settings: [String: JSONValue]?
    public let status: AppStatus
    public let visibility: AppVisibility
    public let publishedAt: Date?
    public let lastUsedAt: Date?
    public let sortOrder: Int
    public let itemCount: Int
    public let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case displayName = "display_name"
        case description
        case icon
        case template
        case schemaDef = "schema_def"
        case appUrl = "app_url"
        case settings
        case status
        case visibility
        case publishedAt = "published_at"
        case lastUsedAt = "last_used_at"
        case sortOrder = "sort_order"
        case itemCount = "item_count"
        case createdAt = "created_at"
    }
}

/// An item within a user app from GET /api/apps/{id}/items
public struct AppItem: Codable, Identifiable, Sendable {
    public let id: String
    public let data: [String: JSONValue]
    public let createdAt: Date
    public let updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id
        case data
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

/// Request body for POST /api/apps
public struct CreateAppRequest: Codable, Sendable {
    public let name: String
    public let displayName: String
    public let description: String?
    public let icon: String?
    public let template: String?
    public let schemaDef: [String: JSONValue]?
    public let settings: [String: JSONValue]?
    public let visibility: AppVisibility

    public init(
        name: String,
        displayName: String,
        description: String? = nil,
        icon: String? = nil,
        template: String? = nil,
        schemaDef: [String: JSONValue]? = nil,
        settings: [String: JSONValue]? = nil,
        visibility: AppVisibility = .private
    ) {
        self.name = name
        self.displayName = displayName
        self.description = description
        self.icon = icon
        self.template = template
        self.schemaDef = schemaDef
        self.settings = settings
        self.visibility = visibility
    }

    enum CodingKeys: String, CodingKey {
        case name
        case displayName = "display_name"
        case description
        case icon
        case template
        case schemaDef = "schema_def"
        case settings
        case visibility
    }
}

/// Request body for PATCH /api/apps/{id}
struct UpdateAppRequest: Codable, Sendable {
    let displayName: String?
    let description: String?
    let icon: String?
    let schemaDef: [String: JSONValue]?
    let appUrl: String?
    let settings: [String: JSONValue]?
    let status: AppStatus?
    let visibility: AppVisibility?
    let sortOrder: Int?

    init(
        displayName: String? = nil,
        description: String? = nil,
        icon: String? = nil,
        schemaDef: [String: JSONValue]? = nil,
        appUrl: String? = nil,
        settings: [String: JSONValue]? = nil,
        status: AppStatus? = nil,
        visibility: AppVisibility? = nil,
        sortOrder: Int? = nil
    ) {
        self.displayName = displayName
        self.description = description
        self.icon = icon
        self.schemaDef = schemaDef
        self.appUrl = appUrl
        self.settings = settings
        self.status = status
        self.visibility = visibility
        self.sortOrder = sortOrder
    }

    enum CodingKeys: String, CodingKey {
        case displayName = "display_name"
        case description
        case icon
        case schemaDef = "schema_def"
        case appUrl = "app_url"
        case settings
        case status
        case visibility
        case sortOrder = "sort_order"
    }
}

public struct PublishAppRequest: Codable, Sendable {
    public let visibility: AppVisibility?
    public let appUrl: String?

    public init(visibility: AppVisibility? = nil, appUrl: String? = nil) {
        self.visibility = visibility
        self.appUrl = appUrl
    }

    enum CodingKeys: String, CodingKey {
        case visibility
        case appUrl = "app_url"
    }
}

/// Request body for POST /api/apps/{id}/items
public struct CreateAppItemRequest: Codable, Sendable {
    public let data: [String: JSONValue]

    public init(data: [String: JSONValue]) {
        self.data = data
    }
}

/// Response from GET /api/apps/{id}/stats
public struct AppStats: Codable, Sendable {
    public let appId: String
    public let totalItems: Int
    public let createdAt: Date
    public let lastItemAt: Date?

    enum CodingKeys: String, CodingKey {
        case appId = "app_id"
        case totalItems = "total_items"
        case createdAt = "created_at"
        case lastItemAt = "last_item_at"
    }
}
