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
        XCTAssertEqual(scheme.layout.version, 3)
        XCTAssertEqual(scheme.layout.nodePositions["lens:root"]?.x, 12)
        XCTAssertEqual(scheme.currentRevision?.projection.nodes.first?.position.y, -8)
        XCTAssertEqual(scheme.currentRevision?.projection.edges.first?.label, "Decision")
    }

    func testSchemeDecodesCanvasLayoutPrimitives() throws {
        let json = """
        {
          "version": 3,
          "viewport": {"x": 10, "y": -20, "zoom": 1.4},
          "node_positions": {"lens:root": {"x": 12, "y": -8}},
          "strokes": [
            {
              "id": "stroke-1",
              "points": [{"x": 0, "y": 0}, {"x": 20, "y": 30}],
              "color": "#111827",
              "width": 4
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
              "color": "#f7d774"
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
        XCTAssertEqual(layout.nodePositions["lens:root"]?.y, -8)
        XCTAssertEqual(layout.strokes.first?.points.last?.x, 20)
        XCTAssertEqual(layout.cards.first?.text, "Open issue")
        XCTAssertEqual(layout.shapes.first?.kind, "ellipse")
        XCTAssertEqual(layout.frames.first?.title, "Launch plan")
        XCTAssertEqual(layout.texts.first?.fontSize, 22)
        XCTAssertEqual(layout.connectors.first?.targetId, "card-1")
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
                viewport: SchemeViewport(x: 1, y: 2, zoom: 1.2),
                nodePositions: ["lens:root": SchemePosition(x: 20, y: -10)],
                strokes: [
                    SchemeStroke(
                        id: "stroke-1",
                        points: [SchemePosition(x: 0, y: 0), SchemePosition(x: 10, y: 12)]
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
        XCTAssertEqual(layout?["version"] as? Int, 3)
        let viewport = layout?["viewport"] as? [String: Any]
        XCTAssertEqual(viewport?["zoom"] as? Double, 1.2)
        let positions = layout?["node_positions"] as? [String: Any]
        let root = positions?["lens:root"] as? [String: Any]
        XCTAssertEqual(root?["x"] as? Double, 20)
        XCTAssertEqual(root?["y"] as? Double, -10)
        let strokes = layout?["strokes"] as? [[String: Any]]
        XCTAssertEqual(strokes?.first?["id"] as? String, "stroke-1")
    }
}
