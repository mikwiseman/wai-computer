import Foundation

public struct SchemePosition: Codable, Sendable, Equatable {
    public var x: Double
    public var y: Double

    public init(x: Double, y: Double) {
        self.x = x
        self.y = y
    }
}

public struct SchemeViewport: Codable, Sendable, Equatable {
    public var x: Double
    public var y: Double
    public var zoom: Double

    public init(x: Double = 0, y: Double = 0, zoom: Double = 1) {
        self.x = x
        self.y = y
        self.zoom = zoom
    }
}

public struct SchemeStroke: Codable, Identifiable, Sendable, Equatable {
    public var id: String
    public var points: [SchemePosition]
    public var color: String
    public var width: Double
    public var locked: Bool

    private enum CodingKeys: String, CodingKey {
        case id
        case points
        case color
        case width
        case locked
    }

    public init(id: String, points: [SchemePosition], color: String = "#111827", width: Double = 3, locked: Bool = false) {
        self.id = id
        self.points = points
        self.color = color
        self.width = width
        self.locked = locked
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        points = try container.decode([SchemePosition].self, forKey: .points)
        color = try container.decodeIfPresent(String.self, forKey: .color) ?? "#111827"
        width = try container.decodeIfPresent(Double.self, forKey: .width) ?? 3
        locked = try container.decodeIfPresent(Bool.self, forKey: .locked) ?? false
    }
}

public struct SchemeCanvasCard: Codable, Identifiable, Sendable, Equatable {
    public var id: String
    public var x: Double
    public var y: Double
    public var width: Double
    public var height: Double
    public var text: String
    public var color: String
    public var locked: Bool

    private enum CodingKeys: String, CodingKey {
        case id
        case x
        case y
        case width
        case height
        case text
        case color
        case locked
    }

    public init(
        id: String,
        x: Double,
        y: Double,
        width: Double,
        height: Double,
        text: String,
        color: String = "#f7d774",
        locked: Bool = false
    ) {
        self.id = id
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.text = text
        self.color = color
        self.locked = locked
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        x = try container.decode(Double.self, forKey: .x)
        y = try container.decode(Double.self, forKey: .y)
        width = try container.decode(Double.self, forKey: .width)
        height = try container.decode(Double.self, forKey: .height)
        text = try container.decode(String.self, forKey: .text)
        color = try container.decodeIfPresent(String.self, forKey: .color) ?? "#f7d774"
        locked = try container.decodeIfPresent(Bool.self, forKey: .locked) ?? false
    }
}

public struct SchemeCanvasShape: Codable, Identifiable, Sendable, Equatable {
    public var id: String
    public var kind: String
    public var x: Double
    public var y: Double
    public var width: Double
    public var height: Double
    public var color: String
    public var fill: String
    public var locked: Bool

    private enum CodingKeys: String, CodingKey {
        case id
        case kind
        case x
        case y
        case width
        case height
        case color
        case fill
        case locked
    }

    public init(
        id: String,
        kind: String,
        x: Double,
        y: Double,
        width: Double,
        height: Double,
        color: String = "#2563eb",
        fill: String = "transparent",
        locked: Bool = false
    ) {
        self.id = id
        self.kind = kind
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.color = color
        self.fill = fill
        self.locked = locked
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        kind = try container.decode(String.self, forKey: .kind)
        x = try container.decode(Double.self, forKey: .x)
        y = try container.decode(Double.self, forKey: .y)
        width = try container.decode(Double.self, forKey: .width)
        height = try container.decode(Double.self, forKey: .height)
        color = try container.decodeIfPresent(String.self, forKey: .color) ?? "#2563eb"
        fill = try container.decodeIfPresent(String.self, forKey: .fill) ?? "transparent"
        locked = try container.decodeIfPresent(Bool.self, forKey: .locked) ?? false
    }
}

public struct SchemeCanvasFrame: Codable, Identifiable, Sendable, Equatable {
    public var id: String
    public var x: Double
    public var y: Double
    public var width: Double
    public var height: Double
    public var title: String
    public var color: String
    public var fill: String
    public var locked: Bool

    private enum CodingKeys: String, CodingKey {
        case id
        case x
        case y
        case width
        case height
        case title
        case color
        case fill
        case locked
    }

    public init(
        id: String,
        x: Double,
        y: Double,
        width: Double,
        height: Double,
        title: String,
        color: String = "#0f766e",
        fill: String = "transparent",
        locked: Bool = false
    ) {
        self.id = id
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.title = title
        self.color = color
        self.fill = fill
        self.locked = locked
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        x = try container.decode(Double.self, forKey: .x)
        y = try container.decode(Double.self, forKey: .y)
        width = try container.decode(Double.self, forKey: .width)
        height = try container.decode(Double.self, forKey: .height)
        title = try container.decode(String.self, forKey: .title)
        color = try container.decodeIfPresent(String.self, forKey: .color) ?? "#0f766e"
        fill = try container.decodeIfPresent(String.self, forKey: .fill) ?? "transparent"
        locked = try container.decodeIfPresent(Bool.self, forKey: .locked) ?? false
    }
}

public struct SchemeTextBlock: Codable, Identifiable, Sendable, Equatable {
    public var id: String
    public var x: Double
    public var y: Double
    public var width: Double
    public var height: Double
    public var text: String
    public var color: String
    public var fontSize: Double
    public var locked: Bool

    private enum CodingKeys: String, CodingKey {
        case id
        case x
        case y
        case width
        case height
        case text
        case color
        case fontSize = "font_size"
        case locked
    }

    public init(
        id: String,
        x: Double,
        y: Double,
        width: Double,
        height: Double,
        text: String,
        color: String = "#111827",
        fontSize: Double = 20,
        locked: Bool = false
    ) {
        self.id = id
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.text = text
        self.color = color
        self.fontSize = fontSize
        self.locked = locked
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        x = try container.decode(Double.self, forKey: .x)
        y = try container.decode(Double.self, forKey: .y)
        width = try container.decode(Double.self, forKey: .width)
        height = try container.decode(Double.self, forKey: .height)
        text = try container.decode(String.self, forKey: .text)
        color = try container.decodeIfPresent(String.self, forKey: .color) ?? "#111827"
        fontSize = try container.decodeIfPresent(Double.self, forKey: .fontSize) ?? 20
        locked = try container.decodeIfPresent(Bool.self, forKey: .locked) ?? false
    }
}

public struct SchemeConnector: Codable, Identifiable, Sendable, Equatable {
    public var id: String
    public var sourceId: String?
    public var targetId: String?
    public var points: [SchemePosition]
    public var label: String?
    public var color: String
    public var locked: Bool

    private enum CodingKeys: String, CodingKey {
        case id
        case sourceId = "source_id"
        case targetId = "target_id"
        case points
        case label
        case color
        case locked
    }

    public init(
        id: String,
        sourceId: String?,
        targetId: String?,
        points: [SchemePosition] = [],
        label: String? = nil,
        color: String = "#475569",
        locked: Bool = false
    ) {
        self.id = id
        self.sourceId = sourceId
        self.targetId = targetId
        self.points = points
        self.label = label
        self.color = color
        self.locked = locked
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        sourceId = try container.decodeIfPresent(String.self, forKey: .sourceId)
        targetId = try container.decodeIfPresent(String.self, forKey: .targetId)
        points = try container.decodeIfPresent([SchemePosition].self, forKey: .points) ?? []
        label = try container.decodeIfPresent(String.self, forKey: .label)
        color = try container.decodeIfPresent(String.self, forKey: .color) ?? "#475569"
        locked = try container.decodeIfPresent(Bool.self, forKey: .locked) ?? false
    }
}

public struct SchemeCanvasLayout: Codable, Sendable, Equatable {
    public var version: Int
    public var viewport: SchemeViewport
    public var nodePositions: [String: SchemePosition]
    public var strokes: [SchemeStroke]
    public var cards: [SchemeCanvasCard]
    public var shapes: [SchemeCanvasShape]
    public var frames: [SchemeCanvasFrame]
    public var texts: [SchemeTextBlock]
    public var connectors: [SchemeConnector]

    private enum CodingKeys: String, CodingKey {
        case version
        case viewport
        case nodePositions = "node_positions"
        case strokes
        case cards
        case shapes
        case frames
        case texts
        case connectors
    }

    public init(
        version: Int = 4,
        viewport: SchemeViewport = SchemeViewport(),
        nodePositions: [String: SchemePosition] = [:],
        strokes: [SchemeStroke] = [],
        cards: [SchemeCanvasCard] = [],
        shapes: [SchemeCanvasShape] = [],
        frames: [SchemeCanvasFrame] = [],
        texts: [SchemeTextBlock] = [],
        connectors: [SchemeConnector] = []
    ) {
        self.version = version
        self.viewport = viewport
        self.nodePositions = nodePositions
        self.strokes = strokes
        self.cards = cards
        self.shapes = shapes
        self.frames = frames
        self.texts = texts
        self.connectors = connectors
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        if container.contains(.version) || container.contains(.nodePositions) {
            let decodedVersion = try container.decodeIfPresent(Int.self, forKey: .version) ?? 4
            version = max(decodedVersion, 4)
            viewport = try container.decodeIfPresent(SchemeViewport.self, forKey: .viewport) ?? SchemeViewport()
            nodePositions = try container.decodeIfPresent([String: SchemePosition].self, forKey: .nodePositions) ?? [:]
            strokes = try container.decodeIfPresent([SchemeStroke].self, forKey: .strokes) ?? []
            cards = try container.decodeIfPresent([SchemeCanvasCard].self, forKey: .cards) ?? []
            shapes = try container.decodeIfPresent([SchemeCanvasShape].self, forKey: .shapes) ?? []
            frames = try container.decodeIfPresent([SchemeCanvasFrame].self, forKey: .frames) ?? []
            texts = try container.decodeIfPresent([SchemeTextBlock].self, forKey: .texts) ?? []
            connectors = try container.decodeIfPresent([SchemeConnector].self, forKey: .connectors) ?? []
            return
        }

        let legacyPositions = try [String: SchemePosition](from: decoder)
        version = 4
        viewport = SchemeViewport()
        nodePositions = legacyPositions
        strokes = []
        cards = []
        shapes = []
        frames = []
        texts = []
        connectors = []
    }
}

public struct SchemeNode: Codable, Identifiable, Sendable, Equatable {
    public let id: String
    public let kind: String
    public let title: String
    public let body: String?
    public let lane: String?
    public let citationIds: [String]
    public let position: SchemePosition

    private enum CodingKeys: String, CodingKey {
        case id
        case kind
        case title
        case body
        case lane
        case citationIds = "citation_ids"
        case position
    }

    public init(
        id: String,
        kind: String,
        title: String,
        body: String?,
        lane: String?,
        citationIds: [String],
        position: SchemePosition
    ) {
        self.id = id
        self.kind = kind
        self.title = title
        self.body = body
        self.lane = lane
        self.citationIds = citationIds
        self.position = position
    }
}

public struct SchemeEdge: Codable, Identifiable, Sendable, Equatable {
    public let id: String
    public let source: String
    public let target: String
    public let kind: String
    public let label: String?
    public let citationIds: [String]

    private enum CodingKeys: String, CodingKey {
        case id
        case source
        case target
        case kind
        case label
        case citationIds = "citation_ids"
    }
}

public struct SchemeProjection: Codable, Sendable, Equatable {
    public let version: Int
    public let schemeType: String?
    public let mapType: String?
    public let title: String
    public let prompt: String
    public let summary: String
    public let nodes: [SchemeNode]
    public let edges: [SchemeEdge]
    public let stats: [String: JSONValue]
    public let briefing: [String: JSONValue]?
    public let citations: [[String: JSONValue]]
    public let freshness: [String: JSONValue]

    private enum CodingKeys: String, CodingKey {
        case version
        case schemeType = "scheme_type"
        case mapType = "map_type"
        case title
        case prompt
        case summary
        case nodes
        case edges
        case stats
        case briefing
        case citations
        case freshness
    }
}

public struct SchemeRevision: Codable, Identifiable, Sendable, Equatable {
    public let id: String
    public let schemeId: String
    public let revisionIndex: Int
    public let projection: SchemeProjection
    public let sourceFingerprint: String
    public let sourceCount: Int
    public let freshness: [String: JSONValue]
    public let diff: [String: JSONValue]
    public let citations: [[String: JSONValue]]
    public let compiledAt: String
    public let createdAt: String

    private enum CodingKeys: String, CodingKey {
        case id
        case schemeId = "scheme_id"
        case revisionIndex = "revision_index"
        case projection
        case sourceFingerprint = "source_fingerprint"
        case sourceCount = "source_count"
        case freshness
        case diff
        case citations
        case compiledAt = "compiled_at"
        case createdAt = "created_at"
    }
}

public struct Scheme: Codable, Identifiable, Sendable, Equatable {
    public let id: String
    public let spaceId: String?
    public let title: String
    public let prompt: String
    public let schemeType: String
    public let origin: String
    public let status: String
    public let sourceScope: [String: JSONValue]?
    public let layout: SchemeCanvasLayout
    public let currentRevisionId: String?
    public let currentRevision: SchemeRevision?
    public let createdAt: String
    public let updatedAt: String

    private enum CodingKeys: String, CodingKey {
        case id
        case spaceId = "space_id"
        case title
        case prompt
        case schemeType = "scheme_type"
        case origin
        case status
        case sourceScope = "source_scope"
        case layout
        case currentRevisionId = "current_revision_id"
        case currentRevision = "current_revision"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }

    public init(
        id: String,
        spaceId: String?,
        title: String,
        prompt: String,
        schemeType: String,
        origin: String,
        status: String,
        sourceScope: [String: JSONValue]?,
        layout: SchemeCanvasLayout,
        currentRevisionId: String?,
        currentRevision: SchemeRevision?,
        createdAt: String,
        updatedAt: String
    ) {
        self.id = id
        self.spaceId = spaceId
        self.title = title
        self.prompt = prompt
        self.schemeType = schemeType
        self.origin = origin
        self.status = status
        self.sourceScope = sourceScope
        self.layout = layout
        self.currentRevisionId = currentRevisionId
        self.currentRevision = currentRevision
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        spaceId = try container.decodeIfPresent(String.self, forKey: .spaceId)
        title = try container.decode(String.self, forKey: .title)
        prompt = try container.decode(String.self, forKey: .prompt)
        schemeType = try container.decode(String.self, forKey: .schemeType)
        origin = try container.decode(String.self, forKey: .origin)
        status = try container.decode(String.self, forKey: .status)
        sourceScope = try container.decodeIfPresent([String: JSONValue].self, forKey: .sourceScope)
        layout = try container.decodeIfPresent(SchemeCanvasLayout.self, forKey: .layout) ?? SchemeCanvasLayout()
        currentRevisionId = try container.decodeIfPresent(String.self, forKey: .currentRevisionId)
        currentRevision = try container.decodeIfPresent(SchemeRevision.self, forKey: .currentRevision)
        createdAt = try container.decode(String.self, forKey: .createdAt)
        updatedAt = try container.decode(String.self, forKey: .updatedAt)
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encodeIfPresent(spaceId, forKey: .spaceId)
        try container.encode(title, forKey: .title)
        try container.encode(prompt, forKey: .prompt)
        try container.encode(schemeType, forKey: .schemeType)
        try container.encode(origin, forKey: .origin)
        try container.encode(status, forKey: .status)
        try container.encodeIfPresent(sourceScope, forKey: .sourceScope)
        try container.encode(layout, forKey: .layout)
        try container.encodeIfPresent(currentRevisionId, forKey: .currentRevisionId)
        try container.encodeIfPresent(currentRevision, forKey: .currentRevision)
        try container.encode(createdAt, forKey: .createdAt)
        try container.encode(updatedAt, forKey: .updatedAt)
    }
}

public struct SchemesResponse: Codable, Sendable, Equatable {
    public let schemes: [Scheme]
}
