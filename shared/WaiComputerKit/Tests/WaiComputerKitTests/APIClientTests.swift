import Foundation
import XCTest
@testable import WaiComputerKit

final class MockURLProtocol: URLProtocol, @unchecked Sendable {
    static var requestHandler: (@Sendable (URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool {
        true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        guard let handler = MockURLProtocol.requestHandler else {
            XCTFail("MockURLProtocol.requestHandler is not set")
            return
        }

        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

final class APIClientTests: XCTestCase {
    override func setUp() {
        super.setUp()
        MockURLProtocol.requestHandler = nil
    }

    private func makeClient(baseURL: URL = URL(string: "https://api.example.com")!) -> APIClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        return APIClient(baseURL: baseURL, session: session)
    }

    /// Reads the body from a URLRequest, checking both httpBody and httpBodyStream.
    private func bodyJSON(from request: URLRequest) -> [String: Any]? {
        if let data = request.httpBody {
            return try? JSONSerialization.jsonObject(with: data) as? [String: Any]
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
            return try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        }
        return nil
    }

    func testFulltextSearchUsesFTSEndpoint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/search/fts")
            XCTAssertEqual(request.url?.query, "q=roadmap&limit=10&offset=5")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"results":[],"total":0}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let result = try await client.fulltextSearch(query: "roadmap", limit: 10, offset: 5)
        XCTAssertEqual(result.total, 0)
        XCTAssertTrue(result.results.isEmpty)
    }

    func testUnauthorizedResponseMapsToUnauthorizedError() async {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 401,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data())
        }

        do {
            _ = try await client.getCurrentUser()
            XCTFail("Expected unauthorized error")
        } catch let error as APIError {
            switch error {
            case .unauthorized:
                break
            default:
                XCTFail("Expected unauthorized error, got \(error)")
            }
        } catch {
            XCTFail("Expected APIError, got \(error)")
        }
    }

    func testDateDecodingSupportsNonFractionalISO8601() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "id":"u1",
              "email":"user@example.com",
              "created_at":"2026-02-25T22:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let user = try await client.getCurrentUser()
        XCTAssertEqual(user.id, "u1")
        XCTAssertEqual(user.email, "user@example.com")
    }

    // MARK: - Auth Endpoint Tests

    func testRegisterSendsCorrectPayload() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/auth/register")

            let body = bodyJSON(from: request)
            XCTAssertEqual(body?["email"] as? String, "test@example.com")
            XCTAssertEqual(body?["password"] as? String, "secret123")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"access_token":"tok-abc","token_type":"bearer"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let result = try await client.register(email: "test@example.com", password: "secret123")
        XCTAssertEqual(result.accessToken, "tok-abc")
        XCTAssertEqual(result.tokenType, "bearer")
    }

    func testLoginSendsCorrectPayload() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/auth/login")

            let body = bodyJSON(from: request)
            XCTAssertEqual(body?["email"] as? String, "user@example.com")
            XCTAssertEqual(body?["password"] as? String, "pass456")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"access_token":"tok-xyz","token_type":"bearer"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let result = try await client.login(email: "user@example.com", password: "pass456")
        XCTAssertEqual(result.accessToken, "tok-xyz")
        XCTAssertEqual(result.tokenType, "bearer")
    }

    // MARK: - Recording Endpoint Tests

    func testListRecordingsUsesGetMethod() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/recordings")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            [
                {"id":"rec-1","title":"Test","type":"meeting","created_at":"2026-01-01T00:00:00Z"},
                {"id":"rec-2","title":"Note","type":"note","created_at":"2026-01-02T00:00:00Z"}
            ]
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recordings = try await client.listRecordings()
        XCTAssertEqual(recordings.count, 2)
        XCTAssertEqual(recordings[0].id, "rec-1")
        XCTAssertEqual(recordings[0].title, "Test")
        XCTAssertEqual(recordings[0].type, .meeting)
        XCTAssertEqual(recordings[1].id, "rec-2")
        XCTAssertEqual(recordings[1].type, .note)
    }

    func testCreateRecordingUsesPostMethod() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings")

            let body = self.bodyJSON(from: request)
            XCTAssertEqual(body?["title"] as? String, "My Meeting")
            XCTAssertEqual(body?["type"] as? String, "meeting")
            XCTAssertEqual(body?["language"] as? String, "en")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 201,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"id":"rec-new","title":"My Meeting","type":"meeting","created_at":"2026-01-15T10:00:00Z"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recording = try await client.createRecording(title: "My Meeting", type: .meeting)
        XCTAssertEqual(recording.id, "rec-new")
        XCTAssertEqual(recording.title, "My Meeting")
        XCTAssertEqual(recording.type, .meeting)
    }

    func testDeleteRecordingUsesDeleteMethod() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-del")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 204,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data())
        }

        try await client.deleteRecording(id: "rec-del")
    }

    func testGetTranscriptReturnsSegments() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-1/transcript")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            [
                {"id":"seg-1","content":"Hello world","start_ms":0,"end_ms":1000},
                {"id":"seg-2","speaker":"Alice","content":"Hi there","start_ms":1000,"end_ms":2500,"confidence":0.95}
            ]
            """.data(using: .utf8)!
            return (response, payload)
        }

        let segments = try await client.getTranscript(recordingId: "rec-1")
        XCTAssertEqual(segments.count, 2)
        XCTAssertEqual(segments[0].id, "seg-1")
        XCTAssertEqual(segments[0].content, "Hello world")
        XCTAssertEqual(segments[0].startMs, 0)
        XCTAssertEqual(segments[0].endMs, 1000)
        XCTAssertNil(segments[0].speaker)
        XCTAssertEqual(segments[1].speaker, "Alice")
        XCTAssertEqual(segments[1].confidence, 0.95)
    }

    // MARK: - Search Endpoint Tests

    func testSearchUsesCorrectEndpoint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/search")
            XCTAssertTrue(request.url?.query?.contains("q=hello") == true)

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"results":[],"total":0}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let result = try await client.search(query: "hello")
        XCTAssertEqual(result.total, 0)
        XCTAssertTrue(result.results.isEmpty)
    }

    func testSemanticSearchUsesCorrectEndpoint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/search/semantic")
            XCTAssertTrue(request.url?.query?.contains("q=meaning") == true)

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "results":[
                    {
                        "recording_id":"rec-1",
                        "recording_title":"Meeting",
                        "recording_type":"meeting",
                        "segment_id":"seg-1",
                        "content":"Meaningful discussion",
                        "start_ms":500,
                        "end_ms":3000,
                        "score":0.87
                    }
                ],
                "total":1
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let result = try await client.semanticSearch(query: "meaning")
        XCTAssertEqual(result.total, 1)
        XCTAssertEqual(result.results.count, 1)
        XCTAssertEqual(result.results[0].recordingId, "rec-1")
        XCTAssertEqual(result.results[0].content, "Meaningful discussion")
        XCTAssertEqual(result.results[0].score, 0.87)
    }

    // MARK: - Entity Endpoint Tests

    func testListEntitiesUsesGetMethod() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/entities")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            [
                {"id":"ent-1","type":"person","name":"John"},
                {"id":"ent-2","type":"topic","name":"Architecture"}
            ]
            """.data(using: .utf8)!
            return (response, payload)
        }

        let entities = try await client.listEntities()
        XCTAssertEqual(entities.count, 2)
        XCTAssertEqual(entities[0].id, "ent-1")
        XCTAssertEqual(entities[0].type, .person)
        XCTAssertEqual(entities[0].name, "John")
        XCTAssertEqual(entities[1].type, .topic)
    }

    func testGetEntityReturnsDetail() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/entities/ent-1")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"ent-1",
                "type":"person",
                "name":"John",
                "relations":[
                    {
                        "id":"rel-1",
                        "target_id":"ent-2",
                        "target_name":"Architecture",
                        "target_type":"topic",
                        "relation_type":"discusses",
                        "context":"In the meeting"
                    }
                ]
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let detail = try await client.getEntity(id: "ent-1")
        XCTAssertEqual(detail.id, "ent-1")
        XCTAssertEqual(detail.name, "John")
        XCTAssertEqual(detail.type, .person)
        XCTAssertEqual(detail.relations.count, 1)
        XCTAssertEqual(detail.relations[0].targetId, "ent-2")
        XCTAssertEqual(detail.relations[0].targetName, "Architecture")
        XCTAssertEqual(detail.relations[0].relationType, "discusses")
    }

    // MARK: - Action Items Endpoint Tests

    func testListActionItemsUsesGetMethod() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/action-items")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            [
                {
                    "id":"ai-1",
                    "task":"Do something",
                    "status":"pending",
                    "recording_id":"rec-1",
                    "priority":"high"
                },
                {
                    "id":"ai-2",
                    "task":"Another task",
                    "status":"in_progress",
                    "recording_id":"rec-1",
                    "priority":"low"
                }
            ]
            """.data(using: .utf8)!
            return (response, payload)
        }

        let items = try await client.listActionItems()
        XCTAssertEqual(items.count, 2)
        XCTAssertEqual(items[0].id, "ai-1")
        XCTAssertEqual(items[0].task, "Do something")
        XCTAssertEqual(items[0].status, .pending)
        XCTAssertEqual(items[0].priority, .high)
        XCTAssertEqual(items[0].recordingId, "rec-1")
        XCTAssertEqual(items[1].status, .inProgress)
        XCTAssertEqual(items[1].priority, .low)
    }

    // MARK: - Error Mapping Tests

    func testHttpError400MapsToHttpError() async {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 400,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"detail":"Bad request"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        do {
            _ = try await client.listRecordings()
            XCTFail("Expected httpError")
        } catch let error as APIError {
            switch error {
            case .httpError(let statusCode, _):
                XCTAssertEqual(statusCode, 400)
            default:
                XCTFail("Expected httpError(400), got \(error)")
            }
        } catch {
            XCTFail("Expected APIError, got \(error)")
        }
    }

    func testHttpError404MapsToHttpError() async {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 404,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"detail":"Not found"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        do {
            _ = try await client.getRecording(id: "nonexistent")
            XCTFail("Expected httpError")
        } catch let error as APIError {
            switch error {
            case .httpError(let statusCode, _):
                XCTAssertEqual(statusCode, 404)
            default:
                XCTFail("Expected httpError(404), got \(error)")
            }
        } catch {
            XCTFail("Expected APIError, got \(error)")
        }
    }

    func testHttpError500MapsToHttpError() async {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 500,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"detail":"Internal server error"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        do {
            _ = try await client.listRecordings()
            XCTFail("Expected httpError")
        } catch let error as APIError {
            switch error {
            case .httpError(let statusCode, _):
                XCTAssertEqual(statusCode, 500)
            default:
                XCTFail("Expected httpError(500), got \(error)")
            }
        } catch {
            XCTFail("Expected APIError, got \(error)")
        }
    }

    // MARK: - Authentication Header Tests

    func testSetAccessTokenAddsAuthorizationHeader() async throws {
        let client = makeClient()
        await client.setAccessToken("my-secret-token")

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer my-secret-token")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"id":"u1","email":"user@example.com","created_at":"2026-01-01T00:00:00Z"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let user = try await client.getCurrentUser()
        XCTAssertEqual(user.id, "u1")
    }
}
