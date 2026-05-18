import Foundation

// Server-backed dictation history + dictionary. Mirrors the macOS app's
// local stores so they survive logout/login and roam across Macs.
//
// `clientEntryID` / `clientWordID` are client-generated UUIDs that double as
// idempotency keys for POSTs — the server enforces uniqueness per user.

public struct DictationEntryDTO: Codable, Sendable, Identifiable {
    public let clientEntryID: UUID
    public let rawText: String
    public let cleanedText: String?
    public let durationSeconds: Double
    public let wordCount: Int
    public let occurredAt: Date

    public var id: UUID { clientEntryID }

    public init(
        clientEntryID: UUID,
        rawText: String,
        cleanedText: String?,
        durationSeconds: Double,
        wordCount: Int,
        occurredAt: Date
    ) {
        self.clientEntryID = clientEntryID
        self.rawText = rawText
        self.cleanedText = cleanedText
        self.durationSeconds = durationSeconds
        self.wordCount = wordCount
        self.occurredAt = occurredAt
    }

    private enum CodingKeys: String, CodingKey {
        case clientEntryID = "client_entry_id"
        case rawText = "raw_text"
        case cleanedText = "cleaned_text"
        case durationSeconds = "duration_seconds"
        case wordCount = "word_count"
        case occurredAt = "occurred_at"
    }
}

public struct CreateDictationEntryRequest: Codable, Sendable {
    public let clientEntryID: UUID
    public let rawText: String
    public let cleanedText: String?
    public let durationSeconds: Double
    public let wordCount: Int
    /// ISO 8601 string. The shared JSONEncoder has no date strategy, so Date
    /// in a POST body would encode as a numeric reference timestamp Pydantic
    /// rejects — we serialize at the boundary instead.
    public let occurredAt: String

    public init(
        clientEntryID: UUID,
        rawText: String,
        cleanedText: String?,
        durationSeconds: Double,
        wordCount: Int,
        occurredAt: String
    ) {
        self.clientEntryID = clientEntryID
        self.rawText = rawText
        self.cleanedText = cleanedText
        self.durationSeconds = durationSeconds
        self.wordCount = wordCount
        self.occurredAt = occurredAt
    }

    private enum CodingKeys: String, CodingKey {
        case clientEntryID = "client_entry_id"
        case rawText = "raw_text"
        case cleanedText = "cleaned_text"
        case durationSeconds = "duration_seconds"
        case wordCount = "word_count"
        case occurredAt = "occurred_at"
    }
}

public struct DictionaryWordDTO: Codable, Sendable, Identifiable {
    public let clientWordID: UUID
    public let word: String
    public let replacement: String?
    public let occurredAt: Date

    public var id: UUID { clientWordID }

    public init(
        clientWordID: UUID,
        word: String,
        replacement: String?,
        occurredAt: Date
    ) {
        self.clientWordID = clientWordID
        self.word = word
        self.replacement = replacement
        self.occurredAt = occurredAt
    }

    private enum CodingKeys: String, CodingKey {
        case clientWordID = "client_word_id"
        case word
        case replacement
        case occurredAt = "occurred_at"
    }
}

public struct CreateDictionaryWordRequest: Codable, Sendable {
    public let clientWordID: UUID
    public let word: String
    public let replacement: String?
    public let occurredAt: String

    public init(
        clientWordID: UUID,
        word: String,
        replacement: String?,
        occurredAt: String
    ) {
        self.clientWordID = clientWordID
        self.word = word
        self.replacement = replacement
        self.occurredAt = occurredAt
    }

    private enum CodingKeys: String, CodingKey {
        case clientWordID = "client_word_id"
        case word
        case replacement
        case occurredAt = "occurred_at"
    }
}
