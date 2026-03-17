import Foundation
import XCTest
@testable import WaiComputerKit

final class APIClientNewEndpointsTests: XCTestCase {
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

    // MARK: - Star Recording

    func testStarRecordingSendsPostToCorrectPath() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-42/star")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"rec-42",
                "title":"Starred Recording",
                "type":"note",
                "starred_at":"2026-03-15T12:00:00Z",
                "created_at":"2026-03-01T10:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recording = try await client.starRecording(id: "rec-42")
        XCTAssertEqual(recording.id, "rec-42")
        XCTAssertEqual(recording.title, "Starred Recording")
        XCTAssertNotNil(recording.starredAt)
    }

    func testStarRecordingReturnsUpdatedRecordingWithStarredAt() async throws {
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
                "id":"rec-7",
                "title":"Meeting Notes",
                "type":"meeting",
                "starred_at":"2026-03-17T08:30:00Z",
                "created_at":"2026-03-10T09:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recording = try await client.starRecording(id: "rec-7")
        XCTAssertEqual(recording.type, .meeting)
        XCTAssertNotNil(recording.starredAt)
    }

    // MARK: - Unstar Recording

    func testUnstarRecordingSendsDeleteToCorrectPath() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-42/star")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"rec-42",
                "title":"Unstarred Recording",
                "type":"note",
                "starred_at":null,
                "created_at":"2026-03-01T10:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recording = try await client.unstarRecording(id: "rec-42")
        XCTAssertEqual(recording.id, "rec-42")
        XCTAssertNil(recording.starredAt)
    }

    func testUnstarRecordingClearsStarredAtField() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"rec-99",
                "title":"Was Starred",
                "type":"reflection",
                "created_at":"2026-02-20T14:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recording = try await client.unstarRecording(id: "rec-99")
        XCTAssertEqual(recording.type, .reflection)
        XCTAssertNil(recording.starredAt)
    }

    // MARK: - List Starred Recordings

    func testListStarredRecordingsSendsGetWithStarredQueryParam() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/recordings")
            let query = request.url?.query ?? ""
            XCTAssertTrue(query.contains("starred=true"),
                          "Expected starred=true in query, got: \(query)")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            [
                {
                    "id":"rec-1",
                    "title":"Fav 1",
                    "type":"note",
                    "starred_at":"2026-03-15T12:00:00Z",
                    "created_at":"2026-03-01T10:00:00Z"
                },
                {
                    "id":"rec-2",
                    "title":"Fav 2",
                    "type":"meeting",
                    "starred_at":"2026-03-16T09:00:00Z",
                    "created_at":"2026-03-02T11:00:00Z"
                }
            ]
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recordings = try await client.listStarredRecordings()
        XCTAssertEqual(recordings.count, 2)
        XCTAssertEqual(recordings[0].id, "rec-1")
        XCTAssertNotNil(recordings[0].starredAt)
        XCTAssertEqual(recordings[1].id, "rec-2")
        XCTAssertNotNil(recordings[1].starredAt)
    }

    func testListStarredRecordingsReturnsEmptyArrayWhenNoneStarred() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertTrue(request.url?.query?.contains("starred=true") == true)

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data("[]".utf8))
        }

        let recordings = try await client.listStarredRecordings()
        XCTAssertTrue(recordings.isEmpty)
    }

    // MARK: - Pin Chat Session

    func testPinChatSessionSendsPostToCorrectPath() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/chat/sessions/sess-10/pin")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"sess-10",
                "title":"Pinned Chat",
                "message_count":5,
                "pinned_at":"2026-03-17T10:00:00Z",
                "created_at":"2026-03-15T08:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let session = try await client.pinChatSession(id: "sess-10")
        XCTAssertEqual(session.id, "sess-10")
        XCTAssertEqual(session.title, "Pinned Chat")
        XCTAssertEqual(session.messageCount, 5)
        XCTAssertNotNil(session.pinnedAt)
    }

    func testPinChatSessionReturnsPinnedAtTimestamp() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"sess-abc",
                "title":"Important Thread",
                "message_count":12,
                "pinned_at":"2026-03-17T14:30:00Z",
                "created_at":"2026-03-10T10:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let session = try await client.pinChatSession(id: "sess-abc")
        XCTAssertEqual(session.pinnedAt, "2026-03-17T14:30:00Z")
    }

    // MARK: - Unpin Chat Session

    func testUnpinChatSessionSendsDeleteToCorrectPath() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(request.url?.path, "/api/chat/sessions/sess-10/pin")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"sess-10",
                "title":"Unpinned Chat",
                "message_count":5,
                "pinned_at":null,
                "created_at":"2026-03-15T08:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let session = try await client.unpinChatSession(id: "sess-10")
        XCTAssertEqual(session.id, "sess-10")
        XCTAssertNil(session.pinnedAt)
    }

    func testUnpinChatSessionClearsPinnedAt() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertTrue(request.url?.path.hasSuffix("/pin") == true)

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"sess-xyz",
                "title":"No Longer Pinned",
                "message_count":3,
                "created_at":"2026-03-12T09:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let session = try await client.unpinChatSession(id: "sess-xyz")
        XCTAssertNil(session.pinnedAt)
        XCTAssertEqual(session.messageCount, 3)
    }

    // MARK: - Search Chat Sessions

    func testSearchChatSessionsSendsGetWithQueryItem() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/chat/sessions/search")

            // Verify the query parameter is set via URLQueryItem (not manually encoded)
            let components = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)
            let qItem = components?.queryItems?.first(where: { $0.name == "q" })
            XCTAssertNotNil(qItem, "Expected 'q' query item")
            XCTAssertEqual(qItem?.value, "project roadmap")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            [
                {
                    "id":"sess-1",
                    "title":"Roadmap Discussion",
                    "message_count":8,
                    "created_at":"2026-03-14T10:00:00Z"
                }
            ]
            """.data(using: .utf8)!
            return (response, payload)
        }

        let sessions = try await client.searchChatSessions(query: "project roadmap")
        XCTAssertEqual(sessions.count, 1)
        XCTAssertEqual(sessions[0].id, "sess-1")
        XCTAssertEqual(sessions[0].title, "Roadmap Discussion")
    }

    func testSearchChatSessionsHandlesSpecialCharactersInQuery() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            // URLQueryItem handles encoding — verify the decoded value is correct
            let components = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)
            let qItem = components?.queryItems?.first(where: { $0.name == "q" })
            XCTAssertEqual(qItem?.value, "test & demo / Q&A")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data("[]".utf8))
        }

        let sessions = try await client.searchChatSessions(query: "test & demo / Q&A")
        XCTAssertTrue(sessions.isEmpty)
    }

    func testSearchChatSessionsReturnsEmptyForNoMatches() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.url?.path, "/api/chat/sessions/search")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data("[]".utf8))
        }

        let sessions = try await client.searchChatSessions(query: "nonexistent topic")
        XCTAssertTrue(sessions.isEmpty)
    }

    // MARK: - Export Chat Session

    func testExportChatSessionSendsGetAndReturnsMarkdown() async throws {
        let client = makeClient()
        let expectedMarkdown = """
        # Chat Session: Project Planning

        **User:** What are the key milestones?

        **Assistant:** Here are the key milestones...
        """

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertTrue(request.url?.path.contains("/api/chat/sessions/sess-export/export") == true)

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data(expectedMarkdown.utf8))
        }

        let markdown = try await client.exportChatSession(id: "sess-export")
        XCTAssertEqual(markdown, expectedMarkdown)
    }

    func testExportChatSessionIncludesAuthorizationHeader() async throws {
        let client = makeClient()
        await client.setAccessToken("export-token-123")

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(
                request.value(forHTTPHeaderField: "Authorization"),
                "Bearer export-token-123"
            )

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data("# Exported".utf8))
        }

        let markdown = try await client.exportChatSession(id: "sess-auth")
        XCTAssertEqual(markdown, "# Exported")
    }

    func testExportChatSessionThrowsOnNon200Status() async {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 404,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data())
        }

        do {
            _ = try await client.exportChatSession(id: "sess-missing")
            XCTFail("Expected error for 404 response")
        } catch let error as APIError {
            switch error {
            case .httpError(let statusCode, _):
                XCTAssertEqual(statusCode, 404)
            default:
                XCTFail("Expected httpError, got \(error)")
            }
        } catch {
            XCTFail("Expected APIError, got \(error)")
        }
    }

    // MARK: - Delete Action Item

    func testDeleteActionItemSendsDeleteToCorrectPath() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(request.url?.path, "/api/action-items/ai-55")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 204,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data())
        }

        try await client.deleteActionItem(id: "ai-55")
    }

    func testDeleteActionItemDoesNotIncludeRequestBody() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(request.url?.path, "/api/action-items/ai-99")

            // Verify no request body is sent
            let bodyData: Data?
            if let data = request.httpBody {
                bodyData = data
            } else if let stream = request.httpBodyStream {
                stream.open()
                defer { stream.close() }
                let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 1024)
                defer { buffer.deallocate() }
                let read = stream.read(buffer, maxLength: 1024)
                bodyData = read > 0 ? Data(bytes: buffer, count: read) : nil
            } else {
                bodyData = nil
            }
            XCTAssertNil(bodyData, "DELETE action item should not send a body")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 204,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data())
        }

        try await client.deleteActionItem(id: "ai-99")
    }

    func testDeleteActionItemThrowsOn404() async {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 404,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"detail":"Action item not found"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        do {
            try await client.deleteActionItem(id: "ai-nonexistent")
            XCTFail("Expected httpError for 404")
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
}
