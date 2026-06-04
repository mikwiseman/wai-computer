import Foundation

/// A long-term memory block rendered as a wiki section (human/topics/preferences).
public struct BrainMemorySection: Codable, Identifiable, Sendable {
    public let label: String
    public let body: String
    public let updatedAt: String?

    public var id: String { label }

    private enum CodingKeys: String, CodingKey {
        case label
        case body
        case updatedAt = "updated_at"
    }
}

/// One outgoing relation on an entity page.
public struct BrainEntityRelation: Codable, Sendable {
    public let relationType: String?
    public let targetName: String
    public let targetType: String
    public let context: String?

    private enum CodingKeys: String, CodingKey {
        case relationType = "relation_type"
        case targetName = "target_name"
        case targetType = "target_type"
        case context
    }
}

/// An entity page in the compiled-wiki Brain view.
public struct BrainEntityPage: Codable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let type: String
    public let relations: [BrainEntityRelation]
}

/// The compiled-wiki projection of what the brain durably knows.
public struct BrainProjection: Codable, Sendable {
    public let memorySections: [BrainMemorySection]
    public let entityPages: [BrainEntityPage]
    public let entityCount: Int

    private enum CodingKeys: String, CodingKey {
        case memorySections = "memory_sections"
        case entityPages = "entity_pages"
        case entityCount = "entity_count"
    }
}

// MARK: - Knowledge graph (GET /api/brain/graph)

/// A node in the knowledge graph — an entity, or an item/recording source node.
public struct BrainGraphNode: Codable, Identifiable, Sendable {
    public let id: String
    public let label: String
    public let kind: String  // person | topic | project | item | recording
    public let degree: Int
}

/// A graph edge: ``cooccurrence`` (entity<->entity) or ``mention`` (source->entity).
public struct BrainGraphEdge: Codable, Sendable {
    public let source: String
    public let target: String
    public let type: String
    public let weight: Double
}

public struct BrainSourceCoverage: Codable, Sendable {
    public let total: Int
    public let summarized: Int
    public let organized: Int
    public let unorganized: Int
}

public struct BrainOverviewEntity: Codable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let type: String
    public let sourceCount: Int
    public let recordingCount: Int
    public let materialCount: Int

    private enum CodingKeys: String, CodingKey {
        case id, name, type
        case sourceCount = "source_count"
        case recordingCount = "recording_count"
        case materialCount = "material_count"
    }
}

public struct BrainOverviewSource: Codable, Identifiable, Sendable {
    public let id: String
    public let sourceKind: String
    public let sourceId: String
    public let title: String
    public let entityCount: Int
    public let organizedAt: String?

    private enum CodingKeys: String, CodingKey {
        case id
        case sourceKind = "source_kind"
        case sourceId = "source_id"
        case title
        case entityCount = "entity_count"
        case organizedAt = "organized_at"
    }
}

public struct BrainOverview: Codable, Sendable {
    public let recordings: BrainSourceCoverage
    public let materials: BrainSourceCoverage
    public let pendingReviewCount: Int
    public let topEntities: [BrainOverviewEntity]
    public let recentSources: [BrainOverviewSource]
    public let llmRequests: Int

    private enum CodingKeys: String, CodingKey {
        case recordings
        case materials
        case pendingReviewCount = "pending_review_count"
        case topEntities = "top_entities"
        case recentSources = "recent_sources"
        case llmRequests = "llm_requests"
    }
}

public struct BrainGraph: Codable, Sendable {
    public let nodes: [BrainGraphNode]
    public let edges: [BrainGraphEdge]
    public let stats: [String: Int]
    public let overview: BrainOverview?
}

// MARK: - WaiBrain Spaces (GET /api/brain/spaces)

public struct BrainSpace: Codable, Identifiable, Sendable, Equatable {
    public let id: String
    public let ownerUserId: String
    public let name: String
    public let slug: String
    public let kind: String
    public let engineProfile: String
    public let visibility: String
    public let description: String?
    public let metadata: [String: JSONValue]?
    public let role: String?
    public let createdAt: String?
    public let updatedAt: String?

    private enum CodingKeys: String, CodingKey {
        case id
        case ownerUserId = "owner_user_id"
        case name
        case slug
        case kind
        case engineProfile = "engine_profile"
        case visibility
        case description
        case metadata
        case role
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

public struct BrainSpacesResponse: Codable, Sendable, Equatable {
    public let spaces: [BrainSpace]
}

public struct BrainSpaceCreateRequest: Codable, Sendable, Equatable {
    public let name: String
    public let kind: String?
    public let engineProfile: String?
    public let visibility: String?
    public let description: String?

    public init(
        name: String,
        kind: String? = nil,
        engineProfile: String? = nil,
        visibility: String? = nil,
        description: String? = nil
    ) {
        self.name = name
        self.kind = kind
        self.engineProfile = engineProfile
        self.visibility = visibility
        self.description = description
    }

    private enum CodingKeys: String, CodingKey {
        case name
        case kind
        case engineProfile = "engine_profile"
        case visibility
        case description
    }
}

public struct BrainClaimInput: Codable, Sendable, Equatable {
    public let kind: String
    public let text: String
    public let confidence: Double?
    public let authority: String?
    public let evidence: [JSONValue]?
    public let salience: Double?
    public let sourceRefs: [JSONValue]?
    public let metadata: [String: JSONValue]?

    public init(
        kind: String,
        text: String,
        confidence: Double? = nil,
        authority: String? = nil,
        evidence: [JSONValue]? = nil,
        salience: Double? = nil,
        sourceRefs: [JSONValue]? = nil,
        metadata: [String: JSONValue]? = nil
    ) {
        self.kind = kind
        self.text = text
        self.confidence = confidence
        self.authority = authority
        self.evidence = evidence
        self.salience = salience
        self.sourceRefs = sourceRefs
        self.metadata = metadata
    }

    private enum CodingKeys: String, CodingKey {
        case kind
        case text
        case confidence
        case authority
        case evidence
        case salience
        case sourceRefs = "source_refs"
        case metadata
    }
}

public struct BrainClaim: Codable, Identifiable, Sendable, Equatable {
    public let id: String
    public let spaceId: String
    public let pageId: String?
    public let kind: String
    public let status: String
    public let text: String
    public let confidence: Double
    public let authority: String
    public let salience: Double?
    public let evidence: [JSONValue]
    public let sourceRefs: [JSONValue]
    public let metadata: [String: JSONValue]?

    private enum CodingKeys: String, CodingKey {
        case id
        case spaceId = "space_id"
        case pageId = "page_id"
        case kind
        case status
        case text
        case confidence
        case authority
        case salience
        case evidence
        case sourceRefs = "source_refs"
        case metadata
    }
}

public struct BrainPage: Codable, Identifiable, Sendable, Equatable {
    public let id: String
    public let spaceId: String
    public let title: String
    public let slug: String
    public let kind: String
    public let status: String
    public let markdown: String
    public let frontmatter: [String: JSONValue]
    public let version: Int
    public let claims: [BrainClaim]
    public let createdAt: String?
    public let updatedAt: String?

    private enum CodingKeys: String, CodingKey {
        case id
        case spaceId = "space_id"
        case title
        case slug
        case kind
        case status
        case markdown
        case frontmatter
        case version
        case claims
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

public struct BrainPagesResponse: Codable, Sendable, Equatable {
    public let pages: [BrainPage]
}

public struct BrainSpacePageCreateRequest: Codable, Sendable, Equatable {
    public let title: String
    public let kind: String?
    public let markdown: String?
    public let claims: [BrainClaimInput]

    public init(
        title: String,
        kind: String? = nil,
        markdown: String? = nil,
        claims: [BrainClaimInput] = []
    ) {
        self.title = title
        self.kind = kind
        self.markdown = markdown
        self.claims = claims
    }
}

public struct BrainReviewPack: Codable, Identifiable, Sendable, Equatable {
    public let id: String
    public let spaceId: String
    public let kind: String
    public let risk: String
    public let status: String
    public let title: String
    public let summary: String
    public let proposals: [JSONValue]
    public let evidence: [JSONValue]?
    public let createdByUserId: String?
    public let decidedByUserId: String?
    public let decisionReason: String?
    public let createdAt: String?
    public let decidedAt: String?

    private enum CodingKeys: String, CodingKey {
        case id
        case spaceId = "space_id"
        case kind
        case risk
        case status
        case title
        case summary
        case proposals
        case evidence
        case createdByUserId = "created_by_user_id"
        case decidedByUserId = "decided_by_user_id"
        case decisionReason = "decision_reason"
        case createdAt = "created_at"
        case decidedAt = "decided_at"
    }
}

public struct BrainReviewPacksResponse: Codable, Sendable, Equatable {
    public let reviewPacks: [BrainReviewPack]
    public let pendingCount: Int

    private enum CodingKeys: String, CodingKey {
        case reviewPacks = "review_packs"
        case pendingCount = "pending_count"
    }
}

public struct BrainSpaceHome: Codable, Sendable, Equatable {
    public let space: BrainSpace
    public let pageCount: Int
    public let sourceCount: Int
    public let claimCounts: [String: Int]
    public let sourceCounts: [String: Int]
    public let pendingReviewCount: Int
    public let recentPages: [BrainPage]
    public let engineProfiles: [String]

    private enum CodingKeys: String, CodingKey {
        case space
        case pageCount = "page_count"
        case sourceCount = "source_count"
        case claimCounts = "claim_counts"
        case sourceCounts = "source_counts"
        case pendingReviewCount = "pending_review_count"
        case recentPages = "recent_pages"
        case engineProfiles = "engine_profiles"
    }
}

public struct BrainSpaceMatchRequest: Codable, Sendable, Equatable {
    public let otherSpaceId: String

    public init(otherSpaceId: String) {
        self.otherSpaceId = otherSpaceId
    }

    private enum CodingKeys: String, CodingKey {
        case otherSpaceId = "other_space_id"
    }
}

public struct BrainSpaceContextRequest: Codable, Sendable, Equatable {
    public let task: String?
    public let limit: Int?

    public init(task: String? = nil, limit: Int? = nil) {
        self.task = task
        self.limit = limit
    }
}

public struct BrainContextResponse: Codable, Sendable, Equatable {
    public let space: BrainSpace
    public let markdown: String
    public let claimCount: Int

    private enum CodingKeys: String, CodingKey {
        case space
        case markdown
        case claimCount = "claim_count"
    }
}

public struct BrainExportFile: Codable, Sendable, Equatable {
    public let path: String
    public let markdown: String
}

public struct BrainExportResponse: Codable, Sendable, Equatable {
    public let space: BrainSpace
    public let profile: String
    public let files: [BrainExportFile]
}

// MARK: - Entity wiki page (GET /api/entities/{id}/page)

/// A source backlink on an entity's wiki page.
public struct EntityPageSource: Codable, Identifiable, Sendable {
    public let sourceKind: String
    public let sourceId: String
    public let title: String
    public let context: String?
    public let occurredAt: String?

    public var id: String { "\(sourceKind):\(sourceId)" }

    private enum CodingKeys: String, CodingKey {
        case sourceKind = "source_kind"
        case sourceId = "source_id"
        case title
        case context
        case occurredAt = "occurred_at"
    }
}

/// A related entity (co-occurrence) on a wiki page.
public struct EntityPageRelated: Codable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let type: String
    public let shared: Int
}

public struct EntityPageCitation: Codable, Identifiable, Sendable {
    public let id: String
    public let sourceKind: String
    public let sourceId: String
    public let title: String
    public let context: String?
    public let occurredAt: String?

    private enum CodingKeys: String, CodingKey {
        case id
        case sourceKind = "source_kind"
        case sourceId = "source_id"
        case title
        case context
        case occurredAt = "occurred_at"
    }
}

public struct EntityPageFact: Codable, Identifiable, Sendable {
    public let id: String
    public let text: String
    public let citationIds: [String]

    private enum CodingKeys: String, CodingKey {
        case id
        case text
        case citationIds = "citation_ids"
    }
}

public struct EntityPageTimelineEvent: Codable, Identifiable, Sendable {
    public let id: String
    public let title: String
    public let description: String?
    public let occurredAt: String?
    public let citationIds: [String]

    private enum CodingKeys: String, CodingKey {
        case id
        case title
        case description
        case occurredAt = "occurred_at"
        case citationIds = "citation_ids"
    }
}

public struct EntityPageRelatedExplanation: Codable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let type: String
    public let shared: Int
    public let explanation: String
    public let citationIds: [String]

    private enum CodingKeys: String, CodingKey {
        case id, name, type, shared, explanation
        case citationIds = "citation_ids"
    }
}

public struct EntityPageQuestion: Codable, Identifiable, Sendable {
    public let id: String
    public let text: String
    public let citationIds: [String]

    private enum CodingKeys: String, CodingKey {
        case id
        case text
        case citationIds = "citation_ids"
    }
}

public struct EntityPageAction: Codable, Identifiable, Sendable {
    public let id: String
    public let text: String
    public let owner: String?
    public let dueDate: String?
    public let status: String?
    public let citationIds: [String]

    private enum CodingKeys: String, CodingKey {
        case id
        case text
        case owner
        case dueDate = "due_date"
        case status
        case citationIds = "citation_ids"
    }
}

public struct EntityPage: Codable, Sendable {
    public let id: String
    public let name: String
    public let type: String
    public let mentionCount: Int
    public let sources: [EntityPageSource]
    public let related: [EntityPageRelated]
    public let overview: String
    public let facts: [EntityPageFact]
    public let citations: [EntityPageCitation]
    public let timeline: [EntityPageTimelineEvent]
    public let relatedExplanations: [EntityPageRelatedExplanation]
    public let questions: [EntityPageQuestion]
    public let actions: [EntityPageAction]
    public let cacheStatus: String

    private enum CodingKeys: String, CodingKey {
        case id, name, type
        case mentionCount = "mention_count"
        case sources, related, overview, facts, citations, timeline, questions, actions
        case relatedExplanations = "related_explanations"
        case cacheStatus = "cache_status"
    }
}
