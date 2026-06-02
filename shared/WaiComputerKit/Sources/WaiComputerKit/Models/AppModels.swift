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
