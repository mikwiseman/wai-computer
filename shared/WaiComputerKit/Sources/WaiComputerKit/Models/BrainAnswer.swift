import Foundation

public struct BrainAskRequest: Codable, Sendable, Equatable {
    public let question: String
    public let sourceScope: [String: JSONValue]?

    public init(question: String, sourceScope: [String: JSONValue]? = nil) {
        self.question = question
        self.sourceScope = sourceScope
    }

    private enum CodingKeys: String, CodingKey {
        case question
        case sourceScope = "source_scope"
    }
}

/// Ask your Brain — one cited answer with honest gaps + a freshness read.
public struct BrainAnswerCitation: Codable, Identifiable, Sendable {
    public let id: String
    public let sourceKind: String
    public let sourceId: String
    public let title: String?
    public let startMs: Int?

    public init(id: String, sourceKind: String, sourceId: String, title: String?, startMs: Int?) {
        self.id = id
        self.sourceKind = sourceKind
        self.sourceId = sourceId
        self.title = title
        self.startMs = startMs
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case sourceKind = "source_kind"
        case sourceId = "source_id"
        case title
        case startMs = "start_ms"
    }
}

public struct BrainAnswerFreshness: Codable, Sendable {
    public let newestSourceAt: String?
    public let weeksSince: Int?
    public let stale: Bool

    public init(newestSourceAt: String?, weeksSince: Int?, stale: Bool) {
        self.newestSourceAt = newestSourceAt
        self.weeksSince = weeksSince
        self.stale = stale
    }

    private enum CodingKeys: String, CodingKey {
        case newestSourceAt = "newest_source_at"
        case weeksSince = "weeks_since"
        case stale
    }
}

public struct BrainAnswer: Codable, Sendable {
    public let answer: String
    public let citations: [BrainAnswerCitation]
    public let gaps: [String]
    public let freshness: BrainAnswerFreshness

    public init(answer: String, citations: [BrainAnswerCitation], gaps: [String], freshness: BrainAnswerFreshness) {
        self.answer = answer
        self.citations = citations
        self.gaps = gaps
        self.freshness = freshness
    }
}
