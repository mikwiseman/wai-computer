import Foundation

/// A proposed change to canonical user memory, awaiting an auto/human decision.
///
/// The nightly consolidator parks destructive corrections and low-confidence
/// guesses here as `pending`; the user accepts (promote into memory) or rejects
/// (a durable "no") with one tap. `risk` is `low` for additive `append`s and
/// `high` for `replace_line` / `rewrite` (overwrites prior truth).
public struct MemoryProposal: Codable, Identifiable, Sendable {
    public let id: String
    public let kind: String
    public let risk: String
    public let blockLabel: String
    public let operation: String
    public let content: String
    public let targetLine: String?
    public let summary: String
    public let confidence: Double
    public let authority: String
    public let evidence: [JSONValue]?
    public let status: String
    public let decisionReason: String?
    public let createdAt: String?
    public let decidedAt: String?

    public var isPending: Bool { status == "pending" }
    public var isHighRisk: Bool { risk == "high" }

    private enum CodingKeys: String, CodingKey {
        case id
        case kind
        case risk
        case blockLabel = "block_label"
        case operation
        case content
        case targetLine = "target_line"
        case summary
        case confidence
        case authority
        case evidence
        case status
        case decisionReason = "decision_reason"
        case createdAt = "created_at"
        case decidedAt = "decided_at"
    }
}

/// The review queue: pending (or filtered) proposals plus a live pending count
/// for the sidebar badge.
public struct MemoryProposalList: Codable, Sendable {
    public let proposals: [MemoryProposal]
    public let pendingCount: Int

    private enum CodingKeys: String, CodingKey {
        case proposals
        case pendingCount = "pending_count"
    }
}

/// Optional reason carried with a reject decision.
public struct RejectProposalRequest: Codable, Sendable {
    public let reason: String?

    public init(reason: String? = nil) {
        self.reason = reason
    }
}
