import Foundation
import WaiComputerKit

struct MacBrainGraphFilters: Equatable {
    var query = ""
    var showSources = true
    var includedEntityKinds: Set<String> = ["person", "topic", "project", "organization"]
    var includeOtherEntityKinds = true
    var minimumCooccurrenceWeight = 1

    var normalizedQuery: String {
        query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }
}

struct MacBrainGraphSummary: Equatable {
    let entities: Int
    let sources: Int
    let links: Int
    let people: Int
    let topics: Int
    let projects: Int
}

struct MacBrainGraphNeighbor: Identifiable {
    let node: BrainGraphNode
    let edge: BrainGraphEdge

    var id: String { "\(node.id):\(edge.source):\(edge.target)" }

    var sharedCount: Int {
        max(1, Int(edge.weight.rounded()))
    }
}

struct MacBrainGraphNodeDetails {
    let node: BrainGraphNode
    let entityNeighbors: [MacBrainGraphNeighbor]
    let sourceNeighbors: [MacBrainGraphNeighbor]
}

struct MacBrainGraphPresentation {
    let graph: BrainGraph
    let filters: MacBrainGraphFilters
    let selectedNodeId: String?

    private let nodesById: [String: BrainGraphNode]
    private let visibleNodeIds: Set<String>

    init(
        graph: BrainGraph,
        filters: MacBrainGraphFilters = MacBrainGraphFilters(),
        selectedNodeId: String? = nil
    ) {
        self.graph = graph
        self.filters = filters
        self.selectedNodeId = selectedNodeId
        nodesById = Dictionary(uniqueKeysWithValues: graph.nodes.map { ($0.id, $0) })

        let baseIds = Set(graph.nodes.filter { node in
            Self.nodePassesBaseFilters(node, filters: filters)
        }.map(\.id))

        let query = filters.normalizedQuery
        if query.isEmpty {
            visibleNodeIds = baseIds
        } else {
            let matches = Set(graph.nodes.filter { node in
                baseIds.contains(node.id)
                    && node.label.lowercased().contains(query)
            }.map(\.id))
            if matches.isEmpty {
                visibleNodeIds = []
            } else {
                var expanded = matches
                for edge in graph.edges where Self.edgePassesFilters(edge, filters: filters) {
                    guard baseIds.contains(edge.source), baseIds.contains(edge.target) else { continue }
                    if matches.contains(edge.source) {
                        expanded.insert(edge.target)
                    }
                    if matches.contains(edge.target) {
                        expanded.insert(edge.source)
                    }
                }
                visibleNodeIds = expanded
            }
        }
    }

    var visibleNodes: [BrainGraphNode] {
        graph.nodes.filter { visibleNodeIds.contains($0.id) }
    }

    var visibleEdges: [BrainGraphEdge] {
        graph.edges.filter { edge in
            visibleNodeIds.contains(edge.source)
                && visibleNodeIds.contains(edge.target)
                && Self.edgePassesFilters(edge, filters: filters)
        }
    }

    var summary: MacBrainGraphSummary {
        let nodes = visibleNodes
        return MacBrainGraphSummary(
            entities: nodes.filter { Self.isEntity($0.kind) }.count,
            sources: nodes.filter { Self.isSource($0.kind) }.count,
            links: visibleEdges.count,
            people: nodes.filter { $0.kind == "person" }.count,
            topics: nodes.filter { $0.kind == "topic" }.count,
            projects: nodes.filter { $0.kind == "project" }.count
        )
    }

    var topEntityNodes: [BrainGraphNode] {
        visibleNodes
            .filter { Self.isEntity($0.kind) }
            .sorted { lhs, rhs in
                if lhs.degree != rhs.degree { return lhs.degree > rhs.degree }
                return lhs.label.localizedCaseInsensitiveCompare(rhs.label) == .orderedAscending
            }
            .prefix(12)
            .map { $0 }
    }

    var layoutSignature: String {
        let nodePart = visibleNodes.map(\.id).joined(separator: ",")
        let edgePart = visibleEdges.map { "\($0.source)>\($0.target):\($0.type):\($0.weight)" }
            .joined(separator: ",")
        return "\(nodePart)|\(edgePart)"
    }

    func details(for nodeId: String) -> MacBrainGraphNodeDetails? {
        guard let node = nodesById[nodeId], visibleNodeIds.contains(nodeId) else { return nil }
        var entityNeighbors: [MacBrainGraphNeighbor] = []
        var sourceNeighbors: [MacBrainGraphNeighbor] = []

        for edge in visibleEdges {
            let otherId: String
            if edge.source == nodeId {
                otherId = edge.target
            } else if edge.target == nodeId {
                otherId = edge.source
            } else {
                continue
            }
            guard let other = nodesById[otherId] else { continue }
            let neighbor = MacBrainGraphNeighbor(node: other, edge: edge)
            if Self.isSource(other.kind) {
                sourceNeighbors.append(neighbor)
            } else {
                entityNeighbors.append(neighbor)
            }
        }

        entityNeighbors.sort { lhs, rhs in
            if lhs.sharedCount != rhs.sharedCount { return lhs.sharedCount > rhs.sharedCount }
            if lhs.node.degree != rhs.node.degree { return lhs.node.degree > rhs.node.degree }
            return lhs.node.label.localizedCaseInsensitiveCompare(rhs.node.label) == .orderedAscending
        }
        sourceNeighbors.sort { lhs, rhs in
            let lhsRank = Self.sourceSortRank(lhs.node.kind)
            let rhsRank = Self.sourceSortRank(rhs.node.kind)
            if lhsRank != rhsRank { return lhsRank < rhsRank }
            return lhs.node.label.localizedCaseInsensitiveCompare(rhs.node.label) == .orderedAscending
        }

        return MacBrainGraphNodeDetails(
            node: node,
            entityNeighbors: entityNeighbors,
            sourceNeighbors: sourceNeighbors
        )
    }

    func isHighlighted(nodeId: String) -> Bool {
        guard let selectedNodeId else { return true }
        if selectedNodeId == nodeId { return true }
        return visibleEdges.contains { edge in
            (edge.source == selectedNodeId && edge.target == nodeId)
                || (edge.target == selectedNodeId && edge.source == nodeId)
        }
    }

    func isHighlighted(edge: BrainGraphEdge) -> Bool {
        guard let selectedNodeId else { return true }
        return edge.source == selectedNodeId || edge.target == selectedNodeId
    }

    static func isEntity(_ kind: String) -> Bool {
        !isSource(kind)
    }

    static func isSource(_ kind: String) -> Bool {
        kind == "item" || kind == "recording" || kind == "chat"
    }

    static func nodePassesBaseFilters(
        _ node: BrainGraphNode,
        filters: MacBrainGraphFilters
    ) -> Bool {
        if isSource(node.kind) {
            return filters.showSources
        }
        if filters.includedEntityKinds.contains(node.kind) {
            return true
        }
        return filters.includeOtherEntityKinds
    }

    static func edgePassesFilters(
        _ edge: BrainGraphEdge,
        filters: MacBrainGraphFilters
    ) -> Bool {
        if edge.type == "mention" {
            return filters.showSources
        }
        if edge.type == "cooccurrence" {
            return edge.weight >= Double(filters.minimumCooccurrenceWeight)
        }
        return true
    }

    private static func sourceSortRank(_ kind: String) -> Int {
        switch kind {
        case "item": return 0
        case "recording": return 1
        case "chat": return 2
        default: return 2
        }
    }
}
