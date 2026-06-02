import WaiComputerKit
import XCTest

final class MacBrainGraphPresentationTests: XCTestCase {
    func testPresentationHidesSourcesWhenDisabled() throws {
        let graph = try sampleGraph()

        let presentation = MacBrainGraphPresentation(
            graph: graph,
            filters: MacBrainGraphFilters(showSources: false)
        )

        XCTAssertEqual(presentation.visibleNodes.map(\.id).sorted(), ["anna", "gpu", "wai"])
        XCTAssertEqual(
            presentation.visibleEdges
                .map { "\($0.source)->\($0.target):\($0.type)" }
                .sorted(),
            ["anna->gpu:cooccurrence", "anna->wai:cooccurrence"]
        )
        XCTAssertEqual(presentation.summary.sources, 0)
    }

    func testSearchKeepsMatchingNodesAndImmediateContext() throws {
        let graph = try sampleGraph()

        let presentation = MacBrainGraphPresentation(
            graph: graph,
            filters: MacBrainGraphFilters(
                query: "anna",
                showSources: true,
                minimumCooccurrenceWeight: 2
            )
        )

        XCTAssertEqual(
            Set(presentation.visibleNodes.map(\.id)),
            Set(["anna", "gpu", "item:note-1", "recording:call-1"])
        )
        XCTAssertTrue(presentation.visibleEdges.contains { $0.source == "anna" && $0.target == "gpu" })
        XCTAssertFalse(presentation.visibleNodes.contains { $0.id == "wai" })
    }

    func testNodeDetailsSortNeighborsByRelationshipStrength() throws {
        let graph = try sampleGraph()
        let presentation = MacBrainGraphPresentation(graph: graph)

        let details = try XCTUnwrap(presentation.details(for: "anna"))

        XCTAssertEqual(details.node.label, "Anna")
        XCTAssertEqual(details.entityNeighbors.map(\.node.id), ["gpu", "wai"])
        XCTAssertEqual(details.entityNeighbors.map(\.sharedCount), [2, 1])
        XCTAssertEqual(details.sourceNeighbors.map(\.node.id), ["item:note-1", "recording:call-1"])
    }

    func testSelectedEdgesExposeSelectedNodeNeighborhoodOnly() throws {
        let graph = try sampleGraph()
        let presentation = MacBrainGraphPresentation(graph: graph, selectedNodeId: "anna")

        XCTAssertTrue(presentation.isHighlighted(nodeId: "anna"))
        XCTAssertTrue(presentation.isHighlighted(nodeId: "gpu"))
        XCTAssertTrue(presentation.isHighlighted(nodeId: "item:note-1"))
        XCTAssertFalse(presentation.isHighlighted(nodeId: "recording:unrelated"))
        XCTAssertTrue(presentation.isHighlighted(edge: edge(source: "anna", target: "gpu", type: "cooccurrence")))
        XCTAssertFalse(presentation.isHighlighted(edge: edge(source: "recording:unrelated", target: "wai", type: "mention")))
    }

    private func sampleGraph() throws -> BrainGraph {
        let payload = """
        {
          "nodes": [
            {"id": "anna", "label": "Anna", "kind": "person", "degree": 3},
            {"id": "gpu", "label": "GPU Architecture", "kind": "topic", "degree": 2},
            {"id": "wai", "label": "WaiComputer", "kind": "project", "degree": 1},
            {"id": "item:note-1", "label": "Architecture note", "kind": "item", "degree": 0},
            {"id": "recording:call-1", "label": "Anna call", "kind": "recording", "degree": 0},
            {"id": "recording:unrelated", "label": "Unrelated call", "kind": "recording", "degree": 0}
          ],
          "edges": [
            {"source": "anna", "target": "gpu", "type": "cooccurrence", "weight": 2.0},
            {"source": "anna", "target": "wai", "type": "cooccurrence", "weight": 1.0},
            {"source": "item:note-1", "target": "anna", "type": "mention", "weight": 1.0},
            {"source": "item:note-1", "target": "gpu", "type": "mention", "weight": 1.0},
            {"source": "recording:call-1", "target": "anna", "type": "mention", "weight": 1.0},
            {"source": "recording:unrelated", "target": "wai", "type": "mention", "weight": 1.0}
          ],
          "stats": {"entities": 3, "people": 1, "topics": 1, "projects": 1, "items": 1, "recordings": 2}
        }
        """.data(using: .utf8)!
        return try JSONDecoder().decode(BrainGraph.self, from: payload)
    }

    private func edge(source: String, target: String, type: String) -> BrainGraphEdge {
        let payload = """
        {"source":"\(source)","target":"\(target)","type":"\(type)","weight":1.0}
        """.data(using: .utf8)!
        return try! JSONDecoder().decode(BrainGraphEdge.self, from: payload)
    }
}
