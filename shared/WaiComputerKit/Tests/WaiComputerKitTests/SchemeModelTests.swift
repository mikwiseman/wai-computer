import Foundation
import XCTest
@testable import WaiComputerKit

final class SchemeModelTests: XCTestCase {
    private final class RequestRecorder: @unchecked Sendable {
        typealias Event = (method: String, path: String, body: [String: Any]?)

        private let lock = NSLock()
        private var events: [Event] = []

        func record(_ request: URLRequest) {
            let event = (
                method: request.httpMethod ?? "",
                path: request.url?.path ?? "",
                body: Self.bodyJSON(from: request)
            )
            lock.lock()
            events.append(event)
            lock.unlock()
        }

        func snapshot() -> [Event] {
            lock.lock()
            defer { lock.unlock() }
            return events
        }

        private static func bodyData(from request: URLRequest) -> Data? {
            if let data = request.httpBody {
                return data
            }
            if let stream = request.httpBodyStream {
                stream.open()
                defer { stream.close() }
                let bufferSize = 4096
                var data = Data()
                let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: bufferSize)
                defer { buffer.deallocate() }
                while stream.hasBytesAvailable {
                    let read = stream.read(buffer, maxLength: bufferSize)
                    if read <= 0 { break }
                    data.append(buffer, count: read)
                }
                return data
            }
            return nil
        }

        private static func bodyJSON(from request: URLRequest) -> [String: Any]? {
            guard let data = bodyData(from: request) else { return nil }
            return try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        }
    }

    override func tearDown() {
        MockURLProtocol.requestHandler = nil
        super.tearDown()
    }

    private func makeClient(baseURL: URL = URL(string: "https://api.example.com")!) -> APIClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        return APIClient(baseURL: baseURL, session: session)
    }

    func testSchemeDecodesProjectionNodesAndEdges() throws {
        let json = """
        {
          "id": "scheme-1",
          "title": "Launch map",
          "prompt": "Map launch decisions",
          "scheme_type": "decision",
          "origin": "brain",
          "status": "draft",
          "source_scope": null,
          "layout": {"lens:root": {"x": 12, "y": -8}},
          "current_revision_id": "rev-1",
          "current_revision": {
            "id": "rev-1",
            "scheme_id": "scheme-1",
            "revision_index": 1,
            "projection": {
              "version": 1,
              "scheme_type": "decision",
              "title": "Launch map",
              "prompt": "Map launch decisions",
              "summary": "Decision from 1 source.",
              "nodes": [
                {
                  "id": "lens:root",
                  "kind": "lens",
                  "title": "Launch map",
                  "body": "Map launch decisions",
                  "lane": "center",
                  "citation_ids": [],
                  "position": {"x": 12, "y": -8}
                },
                {
                  "id": "source:item:1",
                  "kind": "source",
                  "title": "Launch memo",
                  "body": "The launch memo approved the launch.",
                  "lane": "sources",
                  "source_kind": "item",
                  "source_id": "1",
                  "citation_ids": ["item:1"],
                  "position": {"x": -360, "y": 120}
                }
              ],
              "edges": [
                {
                  "id": "edge-1",
                  "source": "lens:root",
                  "target": "signal:decision:1",
                  "kind": "decision",
                  "label": "Decision",
                  "citation_ids": ["item:1"]
                }
              ],
              "stats": {"total_source_count": 1},
              "briefing": null,
              "citations": [],
              "freshness": {}
            },
            "source_fingerprint": "fp",
            "source_count": 1,
            "freshness": {},
            "diff": {"changed": true},
            "citations": [],
            "compiled_at": "2026-06-17T10:00:00Z",
            "created_at": "2026-06-17T10:00:00Z"
          },
          "created_at": "2026-06-17T10:00:00Z",
          "updated_at": "2026-06-17T10:00:00Z"
        }
        """.data(using: .utf8)!

        let scheme = try JSONDecoder().decode(Scheme.self, from: json)

        XCTAssertEqual(scheme.id, "scheme-1")
        XCTAssertEqual(scheme.schemeType, "decision")
        XCTAssertEqual(scheme.layout.version, 10)
        XCTAssertFalse(scheme.layout.snapToGrid)
        XCTAssertEqual(scheme.layout.gridSize, 40)
        XCTAssertFalse(scheme.layout.presentation.active)
        XCTAssertNil(scheme.layout.presentation.frameId)
        XCTAssertEqual(scheme.layout.frameOrder, [String]())
        XCTAssertEqual(scheme.layout.nodePositions["lens:root"]?.x, 12)
        XCTAssertEqual(scheme.currentRevision?.projection.nodes.first?.position.y, -8)
        XCTAssertEqual(scheme.currentRevision?.projection.nodes.last?.sourceKind, "item")
        XCTAssertEqual(scheme.currentRevision?.projection.nodes.last?.sourceId, "1")
        XCTAssertEqual(scheme.currentRevision?.projection.edges.first?.label, "Decision")
    }

    func testSchemeDecodesCanvasLayoutPrimitives() throws {
        let json = """
        {
          "version": 10,
          "snap_to_grid": true,
          "grid_size": 32,
          "viewport": {"x": 10, "y": -20, "zoom": 1.4},
          "presentation": {"active": true, "frame_id": "frame-1"},
          "node_positions": {"lens:root": {"x": 12, "y": -8}},
          "strokes": [
            {
              "id": "stroke-1",
              "points": [{"x": 0, "y": 0, "pressure": 0.5}, {"x": 20, "y": 30, "pressure": 0.8}],
              "kind": "highlighter",
              "color": "#facc15",
              "width": 14,
              "opacity": 0.35,
              "locked": true,
              "z_index": 11
            }
          ],
          "cards": [
            {
              "id": "card-1",
              "x": 100,
              "y": 120,
              "width": 220,
              "height": 150,
              "text": "Open issue",
              "color": "#f7d774",
              "locked": true,
              "z_index": 60
            }
          ],
          "shapes": [
            {
              "id": "shape-1",
              "kind": "ellipse",
              "x": 40,
              "y": 50,
              "width": 180,
              "height": 100,
              "color": "#7c3aed",
              "fill": "transparent"
            }
          ],
          "frames": [
            {
              "id": "frame-1",
              "x": -120,
              "y": -80,
              "width": 520,
              "height": 360,
              "title": "Launch plan",
              "color": "#0f766e",
              "fill": "transparent"
            }
          ],
          "frame_order": ["frame-1"],
          "texts": [
            {
              "id": "text-1",
              "x": 260,
              "y": 180,
              "width": 260,
              "height": 120,
              "text": "Decision context",
              "color": "#111827",
              "font_size": 22
            }
          ],
          "sources": [
            {
              "id": "source-block-1",
              "source_kind": "item",
              "source_id": "11111111-1111-1111-1111-111111111111",
              "citation_id": "item:11111111-1111-1111-1111-111111111111",
              "x": -420,
              "y": 220,
              "width": 320,
              "height": 170,
              "title": "Launch memo",
              "subtitle": "material",
              "excerpt": "Evidence captured from materials.",
              "color": "#eef2ff",
              "locked": true,
              "z_index": 40
            }
          ],
          "connectors": [
            {
              "id": "connector-1",
              "source_id": "lens:root",
              "target_id": "card-1",
              "points": [],
              "label": "blocks",
              "color": "#475569"
            }
          ]
        }
        """.data(using: .utf8)!

        let layout = try JSONDecoder().decode(SchemeCanvasLayout.self, from: json)

        XCTAssertEqual(layout.viewport.zoom, 1.4)
        XCTAssertEqual(layout.version, 10)
        XCTAssertTrue(layout.snapToGrid)
        XCTAssertEqual(layout.gridSize, 32)
        XCTAssertTrue(layout.presentation.active)
        XCTAssertEqual(layout.presentation.frameId, "frame-1")
        XCTAssertEqual(layout.frameOrder, ["frame-1"])
        XCTAssertEqual(layout.nodePositions["lens:root"]?.y, -8)
        XCTAssertEqual(layout.strokes.first?.points.last?.x, 20)
        XCTAssertEqual(layout.strokes.first?.points.last?.pressure, 0.8)
        XCTAssertEqual(layout.strokes.first?.kind, "highlighter")
        XCTAssertEqual(layout.strokes.first?.opacity, 0.35)
        XCTAssertEqual(layout.strokes.first?.locked, true)
        XCTAssertEqual(layout.strokes.first?.zIndex, 11)
        XCTAssertEqual(layout.cards.first?.text, "Open issue")
        XCTAssertEqual(layout.cards.first?.locked, true)
        XCTAssertEqual(layout.cards.first?.zIndex, 60)
        XCTAssertEqual(layout.shapes.first?.kind, "ellipse")
        XCTAssertEqual(layout.shapes.first?.locked, false)
        XCTAssertEqual(layout.shapes.first?.zIndex, 0)
        XCTAssertEqual(layout.frames.first?.title, "Launch plan")
        XCTAssertEqual(layout.frames.first?.locked, false)
        XCTAssertEqual(layout.frames.first?.zIndex, 0)
        XCTAssertEqual(layout.texts.first?.fontSize, 22)
        XCTAssertEqual(layout.texts.first?.locked, false)
        XCTAssertEqual(layout.texts.first?.zIndex, 0)
        XCTAssertEqual(layout.sources.first?.sourceKind, "item")
        XCTAssertEqual(layout.sources.first?.citationId, "item:11111111-1111-1111-1111-111111111111")
        XCTAssertEqual(layout.sources.first?.locked, true)
        XCTAssertEqual(layout.sources.first?.zIndex, 40)
        XCTAssertEqual(layout.connectors.first?.targetId, "card-1")
        XCTAssertEqual(layout.connectors.first?.locked, false)
        XCTAssertEqual(layout.connectors.first?.zIndex, 0)
    }

    func testAPIClientSchemeEndpoints() async throws {
        let client = makeClient()
        let recorder = RequestRecorder()

        MockURLProtocol.requestHandler = { request in
            recorder.record(request)
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: request.url?.path == "/api/schemes" && request.httpMethod == "POST" ? 201 : 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "id": "scheme-1",
              "title": "Launch map",
              "prompt": "Map launch decisions",
              "scheme_type": "decision",
              "origin": "brain",
              "status": "draft",
              "source_scope": null,
              "layout": {},
              "current_revision_id": null,
              "current_revision": null,
              "created_at": "2026-06-17T10:00:00Z",
              "updated_at": "2026-06-17T10:00:00Z"
            }
            """.data(using: .utf8)!
            if request.url?.path == "/api/schemes", request.httpMethod == "GET" {
                return (response, #"{"schemes":[]}"#.data(using: .utf8)!)
            }
            if request.url?.path == "/api/schemes/scheme-1/refresh" {
                let revisionPayload = """
                {
                  "id": "rev-1",
                  "scheme_id": "scheme-1",
                  "revision_index": 1,
                  "projection": {
                    "version": 1,
                    "scheme_type": "decision",
                    "title": "Launch map",
                    "prompt": "Map launch decisions",
                    "summary": "Decision from 1 source.",
                    "nodes": [],
                    "edges": [],
                    "stats": {},
                    "briefing": null,
                    "citations": [],
                    "freshness": {}
                  },
                  "source_fingerprint": "fp",
                  "source_count": 1,
                  "freshness": {},
                  "diff": {},
                  "citations": [],
                  "compiled_at": "2026-06-17T10:00:00Z",
                  "created_at": "2026-06-17T10:00:00Z"
                }
                """.data(using: .utf8)!
                return (response, revisionPayload)
            }
            return (response, payload)
        }

        _ = try await client.listSchemes()
        _ = try await client.createScheme(prompt: "Map launch decisions")
        _ = try await client.getScheme(id: "scheme-1")
        _ = try await client.updateSchemeLayout(
            id: "scheme-1",
            layout: SchemeCanvasLayout(
                snapToGrid: true,
                gridSize: 32,
                presentation: SchemePresentationState(active: true, frameId: "frame-1"),
                frameOrder: ["frame-1"],
                viewport: SchemeViewport(x: 1, y: 2, zoom: 1.2),
                nodePositions: ["lens:root": SchemePosition(x: 20, y: -10)],
                strokes: [
                    SchemeStroke(
                        id: "stroke-1",
                        points: [SchemePosition(x: 0, y: 0, pressure: 1), SchemePosition(x: 10, y: 12, pressure: 0.7)],
                        kind: "pen",
                        color: "#2563eb",
                        width: 5,
                        opacity: 1
                    )
                ],
                frames: [
                    SchemeCanvasFrame(
                        id: "frame-1",
                        x: -120,
                        y: -80,
                        width: 520,
                        height: 360,
                        title: "Launch plan"
                    )
                ],
                sources: [
                    SchemeCanvasSourceBlock(
                        id: "source-block-1",
                        sourceKind: "recording",
                        sourceId: "22222222-2222-2222-2222-222222222222",
                        citationId: "recording:22222222-2222-2222-2222-222222222222",
                        x: -420,
                        y: 120,
                        width: 320,
                        height: 170,
                        title: "Planning call",
                        subtitle: "recording",
                        excerpt: "Recorded decision context."
                    )
                ]
            )
        )
        _ = try await client.refreshScheme(id: "scheme-1")

        let seen = recorder.snapshot()
        XCTAssertEqual(seen.map { "\($0.method) \($0.path)" }, [
            "GET /api/schemes",
            "POST /api/schemes",
            "GET /api/schemes/scheme-1",
            "PATCH /api/schemes/scheme-1",
            "POST /api/schemes/scheme-1/refresh",
        ])
        XCTAssertEqual(seen[1].body?["prompt"] as? String, "Map launch decisions")
        let layout = seen[3].body?["layout"] as? [String: Any]
        XCTAssertEqual(layout?["version"] as? Int, 10)
        XCTAssertEqual(layout?["snap_to_grid"] as? Bool, true)
        XCTAssertEqual(layout?["grid_size"] as? Double, 32)
        let presentation = layout?["presentation"] as? [String: Any]
        XCTAssertEqual(presentation?["active"] as? Bool, true)
        XCTAssertEqual(presentation?["frame_id"] as? String, "frame-1")
        XCTAssertEqual(layout?["frame_order"] as? [String], ["frame-1"])
        let viewport = layout?["viewport"] as? [String: Any]
        XCTAssertEqual(viewport?["zoom"] as? Double, 1.2)
        let positions = layout?["node_positions"] as? [String: Any]
        let root = positions?["lens:root"] as? [String: Any]
        XCTAssertEqual(root?["x"] as? Double, 20)
        XCTAssertEqual(root?["y"] as? Double, -10)
        let strokes = layout?["strokes"] as? [[String: Any]]
        XCTAssertEqual(strokes?.first?["id"] as? String, "stroke-1")
        XCTAssertEqual(strokes?.first?["kind"] as? String, "pen")
        XCTAssertEqual(strokes?.first?["color"] as? String, "#2563eb")
        XCTAssertEqual(strokes?.first?["width"] as? Double, 5)
        XCTAssertEqual(strokes?.first?["opacity"] as? Double, 1)
        XCTAssertEqual(strokes?.first?["locked"] as? Bool, false)
        XCTAssertEqual(strokes?.first?["z_index"] as? Int, 0)
        let sources = layout?["sources"] as? [[String: Any]]
        XCTAssertEqual(sources?.first?["source_kind"] as? String, "recording")
        XCTAssertEqual(sources?.first?["citation_id"] as? String, "recording:22222222-2222-2222-2222-222222222222")
    }
}
