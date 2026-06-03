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

private final class RequestPathRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var paths: [String] = []

    func append(_ path: String) {
        lock.lock()
        defer { lock.unlock() }
        paths.append(path)
    }

    var snapshot: [String] {
        lock.lock()
        defer { lock.unlock() }
        return paths
    }
}

final class APIClientTests: XCTestCase {
    private let paymentModeDefaultsKey = "paymentModeEnabled"

    override func setUp() {
        super.setUp()
        MockURLProtocol.requestHandler = nil
        SentryHelper.resetCapturedFingerprints()
        UserDefaults.standard.removeObject(forKey: paymentModeDefaultsKey)
    }

    override func tearDown() {
        UserDefaults.standard.removeObject(forKey: paymentModeDefaultsKey)
        MockURLProtocol.requestHandler = nil
        super.tearDown()
    }

    private func makeClient(baseURL: URL = URL(string: "https://api.example.com")!) -> APIClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        return APIClient(baseURL: baseURL, session: session)
    }

    /// Reads the body from a URLRequest, checking both httpBody and httpBodyStream.
    private func bodyData(from request: URLRequest) -> Data? {
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

    private func bodyJSON(from request: URLRequest) -> [String: Any]? {
        guard let data = bodyData(from: request) else {
            return nil
        }
        return try? JSONSerialization.jsonObject(with: data) as? [String: Any]
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

    func testRequestsDoNotSendPaymentModeHeaderByDefault() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertNil(request.value(forHTTPHeaderField: "X-WaiComputer-Payment-Mode"))
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data("[]".utf8))
        }

        _ = try await client.listRecordings()
    }

    func testPaymentModeHeaderIsDebugOnly() async throws {
        UserDefaults.standard.set(true, forKey: paymentModeDefaultsKey)
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            #if DEBUG
            XCTAssertEqual(request.value(forHTTPHeaderField: "X-WaiComputer-Payment-Mode"), "enforce")
            #else
            XCTAssertNil(request.value(forHTTPHeaderField: "X-WaiComputer-Payment-Mode"))
            #endif
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data("[]".utf8))
        }

        _ = try await client.listRecordings()
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
        XCTAssertTrue(user.hasPassword)
    }

    func testTelegramLinkEndpoints() async throws {
        let client = makeClient()
        let seenPaths = RequestPathRecorder()

        MockURLProtocol.requestHandler = { request in
            seenPaths.append(request.url!.path)
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: request.url!.path == "/api/telegram/link" && request.httpMethod == "DELETE" ? 204 : 200,
                httpVersion: nil,
                headerFields: nil
            )!
            if request.url!.path == "/api/telegram/link/start" {
                return (response, Data("""
                {
                  "bot_username": "waicomputer_bot",
                  "deep_link": "tg://resolve?domain=waicomputer_bot&start=link_token",
                  "web_link": "https://t.me/waicomputer_bot?start=link_token",
                  "expires_at": "2026-05-22T09:00:00Z"
                }
                """.utf8))
            }
            if request.url!.path == "/api/telegram/link" && request.httpMethod == "GET" {
                return (response, Data("""
                {
                  "linked": true,
                  "bot_username": "waicomputer_bot",
                  "telegram_user_id": 123,
                  "username": "mik",
                  "first_name": "Mik",
                  "last_name": null,
                  "linked_at": "2026-05-22T08:00:00Z"
                }
                """.utf8))
            }
            if request.url!.path == "/api/telegram/link/claim" {
                let body = self.bodyJSON(from: request)!
                XCTAssertEqual(body["code"] as? String, "ABCD-2345")
                return (response, Data("""
                {
                  "linked": true,
                  "bot_username": "waicomputer_bot",
                  "telegram_user_id": 456,
                  "username": "anna",
                  "first_name": "Anna",
                  "last_name": null,
                  "linked_at": "2026-05-22T08:30:00Z"
                }
                """.utf8))
            }
            return (response, Data())
        }

        let status = try await client.getTelegramLinkStatus()
        XCTAssertTrue(status.linked)
        XCTAssertEqual(status.botUsername, "waicomputer_bot")
        XCTAssertEqual(status.telegramUserID, 123)
        XCTAssertEqual(status.username, "mik")

        let pairing = try await client.startTelegramLink()
        XCTAssertEqual(pairing.botUsername, "waicomputer_bot")
        XCTAssertTrue(pairing.webLink.contains("waicomputer_bot"))

        let claimed = try await client.claimTelegramLinkCode("ABCD-2345")
        XCTAssertEqual(claimed.telegramUserID, 456)
        XCTAssertEqual(claimed.username, "anna")

        try await client.unlinkTelegram()
        XCTAssertEqual(
            seenPaths.snapshot,
            [
                "/api/telegram/link",
                "/api/telegram/link/start",
                "/api/telegram/link/claim",
                "/api/telegram/link",
            ]
        )
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
            XCTAssertEqual(body?["accepted_legal_terms"] as? Bool, true)
            XCTAssertEqual(body?["legal_terms_version"] as? String, "2026-05-22")
            XCTAssertEqual(body?["legal_privacy_version"] as? String, "2026-05-22")

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

        let result = try await client.register(
            email: "test@example.com",
            password: "secret123",
            acceptedLegalTerms: true
        )
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

    func testRequestPasswordResetSendsLocaleHint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/auth/forgot-password")

            let body = bodyJSON(from: request)
            XCTAssertEqual(body?["email"] as? String, "user@example.com")
            XCTAssertEqual(body?["locale"] as? String, "ru")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"message":"If this email is registered, we sent a password reset link."}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let result = try await client.requestPasswordReset(email: "user@example.com", locale: "ru")
        XCTAssertEqual(
            result.message,
            "If this email is registered, we sent a password reset link."
        )
    }

    func testRequestMagicLinkSendsClientRegionAndLocaleHint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/auth/magic-link")

            let body = bodyJSON(from: request)
            XCTAssertEqual(body?["email"] as? String, "user@example.com")
            XCTAssertEqual(body?["client"] as? String, "macos")
            XCTAssertEqual(body?["region"] as? String, "ru")
            XCTAssertEqual(body?["locale"] as? String, "ru")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"message":"Мы отправили ссылку для входа на твою почту."}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let result = try await client.requestMagicLink(
            email: "user@example.com",
            client: "macos",
            region: "ru",
            locale: "ru"
        )
        XCTAssertEqual(result.message, "Мы отправили ссылку для входа на твою почту.")
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

    func testListRecordingsIncludesFolderAndTrashFilters() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/recordings")
            let query = request.url?.query ?? ""
            XCTAssertTrue(query.contains("folder_id=folder-1"))
            XCTAssertTrue(query.contains("trashed=true"))

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data("[]".utf8))
        }

        _ = try await client.listRecordings(folderId: "folder-1", trashed: true)
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
            {"id":"rec-new","title":"My Meeting","type":"meeting","status":"pending_upload","created_at":"2026-01-15T10:00:00Z"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recording = try await client.createRecording(title: "My Meeting", type: .meeting)
        XCTAssertEqual(recording.id, "rec-new")
        XCTAssertEqual(recording.title, "My Meeting")
        XCTAssertEqual(recording.type, .meeting)
        XCTAssertEqual(recording.status, .pendingUpload)
    }

    func testRecordingDefaultsStatusWhenResponseOmitsIt() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"id":"rec-default","title":"Notes","type":"note","created_at":"2026-01-15T10:00:00Z"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recording = try await client.getRecording(id: "rec-default")
        XCTAssertEqual(recording.status, .pendingUpload)
    }

    func testUploadAudioRejectsOversizedFileBeforeRequest() async throws {
        let client = makeClient()
        let fileURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("oversized-\(UUID().uuidString).wav")
        FileManager.default.createFile(atPath: fileURL.path, contents: nil)
        let handle = try FileHandle(forWritingTo: fileURL)
        try handle.truncate(atOffset: UInt64(APIClient.maxRecordingUploadSizeBytes + 1))
        try handle.close()
        defer { try? FileManager.default.removeItem(at: fileURL) }

        MockURLProtocol.requestHandler = { _ in
            XCTFail("Oversized uploads should fail before making a request")
            throw URLError(.badServerResponse)
        }

        do {
            _ = try await client.uploadAudio(recordingId: "rec-oversized", fileURL: fileURL)
            XCTFail("Expected file-too-large error")
        } catch let error as APIError {
            switch error {
            case .httpError(let statusCode, let message):
                XCTAssertEqual(statusCode, 413)
                XCTAssertEqual(error.uploadFailureCode, "file_too_large")
                XCTAssertEqual(message, "File too large. Maximum size is 200MB.")
                XCTAssertEqual(error.localizedDescription, "File too large. Maximum size is 200MB.")
            default:
                XCTFail("Expected 413 httpError, got \(error)")
            }
        }
    }

    func testSaveLiveTranscriptUsesTranscriptEndpoint() async throws {
        let client = makeClient()
        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-live/transcript")
            let body = bodyJSON(from: request)
            XCTAssertEqual(body?["duration_seconds"] as? Int, 7)
            let segments = body?["segments"] as? [[String: Any]]
            XCTAssertEqual(segments?.count, 1)

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"id":"rec-live","title":"Live","type":"note","status":"ready","duration_seconds":7,"segments":[{"id":"seg-1","content":"Hello","start_ms":0,"end_ms":1000}],"action_items":[],"created_at":"2026-03-10T10:00:00Z"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let detail = try await client.saveLiveTranscript(
            recordingId: "rec-live",
            segments: [
                LiveTranscriptSegment(
                    text: "Hello",
                    speaker: "Speaker 1",
                    isFinal: true,
                    startMs: 0,
                    endMs: 1000,
                    confidence: 0.98
                )
            ],
            durationSeconds: 7
        )

        XCTAssertEqual(detail.status, .ready)
        XCTAssertEqual(detail.segments.count, 1)
    }

    func testUploadAudioRetriesAfterRefreshOnUnauthorized() async throws {
        let client = makeClient()
        await client.setAccessToken("expired-access")
        await client.setRefreshToken("refresh-1")

        let fileURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("retry-upload-\(UUID().uuidString).wav")
        try Data("wav-data".utf8).write(to: fileURL)
        defer { try? FileManager.default.removeItem(at: fileURL) }

        final class RequestCounter: @unchecked Sendable {
            var value = 0
        }
        let counter = RequestCounter()

        MockURLProtocol.requestHandler = { request in
            counter.value += 1
            switch counter.value {
            case 1:
                XCTAssertEqual(request.url?.path, "/api/recordings/rec-upload/upload")
                XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer expired-access")
                let response = HTTPURLResponse(
                    url: request.url!,
                    statusCode: 401,
                    httpVersion: nil,
                    headerFields: nil
                )!
                return (response, Data())
            case 2:
                XCTAssertEqual(request.url?.path, "/api/auth/refresh")
                let response = HTTPURLResponse(
                    url: request.url!,
                    statusCode: 200,
                    httpVersion: nil,
                    headerFields: nil
                )!
                let payload = """
                {"access_token":"fresh-access","refresh_token":"fresh-refresh","token_type":"bearer"}
                """.data(using: .utf8)!
                return (response, payload)
            default:
                XCTAssertEqual(request.url?.path, "/api/recordings/rec-upload/upload")
                XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer fresh-access")
                let response = HTTPURLResponse(
                    url: request.url!,
                    statusCode: 200,
                    httpVersion: nil,
                    headerFields: nil
                )!
                let payload = """
                {"id":"rec-upload","title":"Recovered","type":"note","status":"ready","segments":[],"action_items":[],"created_at":"2026-03-10T10:00:00Z"}
                """.data(using: .utf8)!
                return (response, payload)
            }
        }

        let detail = try await client.uploadAudio(
            recordingId: "rec-upload",
            fileURL: fileURL,
            clientDurationSeconds: 1800,
            clientFileSizeBytes: 8
        )
        XCTAssertEqual(detail.id, "rec-upload")
        XCTAssertEqual(counter.value, 3)
    }

    func testUploadAudioIncludesClientDurationAndFileSizeMetadata() async throws {
        let client = makeClient()
        await client.setAccessToken("access-token")

        let fileURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("metadata-upload-\(UUID().uuidString).wav")
        try Data("wav-data".utf8).write(to: fileURL)
        defer { try? FileManager.default.removeItem(at: fileURL) }

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-upload/upload")
            let body = try XCTUnwrap(bodyData(from: request))
            let bodyString = String(decoding: body, as: UTF8.self)
            XCTAssertTrue(bodyString.contains("name=\"client_duration_seconds\""))
            XCTAssertTrue(bodyString.contains("\r\n1800\r\n"))
            XCTAssertTrue(bodyString.contains("name=\"client_file_size_bytes\""))
            XCTAssertTrue(bodyString.contains("\r\n8\r\n"))
            XCTAssertTrue(bodyString.contains("name=\"file\"; filename=\"\(fileURL.lastPathComponent)\""))

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"id":"rec-upload","title":"Accepted","type":"note","status":"processing","segments":[],"action_items":[],"created_at":"2026-03-10T10:00:00Z"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let detail = try await client.uploadAudio(
            recordingId: "rec-upload",
            fileURL: fileURL,
            clientDurationSeconds: 1800,
            clientFileSizeBytes: 8
        )

        XCTAssertEqual(detail.status, RecordingStatus.processing)
    }

    func testUploadAudioIncludesMeasuredFileSizeWhenClientFileSizeIsOmitted() async throws {
        let client = makeClient()
        await client.setAccessToken("access-token")

        let fileURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("measured-size-upload-\(UUID().uuidString).wav")
        try Data("0123456789".utf8).write(to: fileURL)
        defer { try? FileManager.default.removeItem(at: fileURL) }

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-upload/upload")
            let body = try XCTUnwrap(bodyData(from: request))
            let bodyString = String(decoding: body, as: UTF8.self)
            XCTAssertTrue(bodyString.contains("name=\"client_duration_seconds\""))
            XCTAssertTrue(bodyString.contains("\r\n9\r\n"))
            XCTAssertTrue(bodyString.contains("name=\"client_file_size_bytes\""))
            XCTAssertTrue(bodyString.contains("\r\n10\r\n"))

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"id":"rec-upload","title":"Accepted","type":"note","status":"processing","segments":[],"action_items":[],"created_at":"2026-03-10T10:00:00Z"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let detail = try await client.uploadAudio(
            recordingId: "rec-upload",
            fileURL: fileURL,
            clientDurationSeconds: 9
        )

        XCTAssertEqual(detail.status, RecordingStatus.processing)
    }

    func testRefreshServerFailureCapturesRefreshFingerprint() async {
        let client = makeClient()
        await client.setAccessToken("expired-access")
        await client.setRefreshToken("refresh-1")

        final class RequestCounter: @unchecked Sendable {
            var value = 0
        }
        let counter = RequestCounter()

        MockURLProtocol.requestHandler = { request in
            counter.value += 1
            switch counter.value {
            case 1:
                XCTAssertEqual(request.url?.path, "/api/auth/me")
                let response = HTTPURLResponse(
                    url: request.url!,
                    statusCode: 401,
                    httpVersion: nil,
                    headerFields: nil
                )!
                return (response, Data())
            default:
                XCTAssertEqual(request.url?.path, "/api/auth/refresh")
                let response = HTTPURLResponse(
                    url: request.url!,
                    statusCode: 503,
                    httpVersion: nil,
                    headerFields: nil
                )!
                return (response, Data("upstream unavailable".utf8))
            }
        }

        do {
            _ = try await client.getCurrentUser()
            XCTFail("Expected unauthorized after failed refresh")
        } catch let error as APIError {
            guard case .unauthorized = error else {
                return XCTFail("Expected unauthorized, got \(error)")
            }
        } catch {
            XCTFail("Expected APIError, got \(error)")
        }

        XCTAssertFalse(
            SentryHelper.shouldCaptureFingerprint(
                "request:POST:/api/auth/refresh:http_503"
            )
        )
    }

    func testCleanupDictationUsesCleanupEndpoint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/dictation/cleanup")
            XCTAssertEqual(request.timeoutInterval, 60)
            let body = bodyJSON(from: request)
            XCTAssertEqual(body?["text"] as? String, "raw dictated text")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data("{\"text\":\"Cleaned\"}".utf8))
        }

        let text = try await client.cleanupDictation(text: "raw dictated text")
        XCTAssertEqual(text, "Cleaned")
    }

    func testCleanupDictationSendsContextWhenProvided() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/dictation/cleanup")
            let body = bodyJSON(from: request)
            let context = body?["context"] as? [String: Any]
            let app = context?["app"] as? [String: Any]
            let textbox = context?["textbox"] as? [String: Any]
            XCTAssertEqual(app?["name"] as? String, "Cursor")
            XCTAssertEqual(app?["bundle_id"] as? String, "com.todesktop.230313mzl4w4u92")
            XCTAssertEqual(app?["category"] as? String, "engineering")
            XCTAssertEqual(textbox?["before_text"] as? String, "func test() {")
            XCTAssertEqual(textbox?["selected_text"] as? String, "TODO")
            XCTAssertEqual(textbox?["after_text"] as? String, "}")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data("{\"text\":\"Cleaned\"}".utf8))
        }

        let context = DictationCleanupContext(
            app: DictationCleanupAppContext(
                name: "Cursor",
                bundleID: "com.todesktop.230313mzl4w4u92",
                category: "engineering"
            ),
            textbox: DictationCleanupTextboxContext(
                beforeText: "func test() {",
                selectedText: "TODO",
                afterText: "}"
            )
        )
        let text = try await client.cleanupDictation(
            text: "raw dictated text",
            context: context
        )
        XCTAssertEqual(text, "Cleaned")
    }

    func testStreamCleanupDictationUsesStreamEndpoint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/dictation/cleanup/stream")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Accept"), "text/event-stream")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Cache-Control"), "no-cache")
            XCTAssertEqual(request.timeoutInterval, 60)
            let body = bodyJSON(from: request)
            XCTAssertEqual(body?["text"] as? String, "raw dictated text")
            XCTAssertEqual(body?["vocabulary"] as? [String], ["WaiComputer"])
            let context = body?["context"] as? [String: Any]
            let app = context?["app"] as? [String: Any]
            XCTAssertEqual(app?["name"] as? String, "Gmail")
            XCTAssertEqual(app?["category"] as? String, "email")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "text/event-stream"]
            )!
            let streamBody = """
            event: token
            data: {"text":"Cleaned"}

            event: token
            data: {"text":" text."}

            event: done
            data: {"text":"Cleaned text.","model":"gpt-5.5","latency_ms":12,"input_tokens":111,"output_tokens":7,"cached_tokens":64}


            """
            return (response, Data(streamBody.utf8))
        }

        let context = DictationCleanupContext(
            app: DictationCleanupAppContext(name: "Gmail", category: "email")
        )
        let stream = try await client.streamCleanupDictation(
            text: "raw dictated text",
            vocabulary: ["WaiComputer", "waicomputer", ""],
            context: context
        )

        var events: [DictationCleanupStreamEvent] = []
        for await event in stream {
            events.append(event)
        }

        XCTAssertEqual(
            events,
            [
                .token(text: "Cleaned"),
                .token(text: " text."),
                .done(
                    text: "Cleaned text.",
                    model: "gpt-5.5",
                    latencyMs: 12,
                    inputTokens: 111,
                    outputTokens: 7,
                    cachedTokens: 64
                ),
            ]
        )
    }

    func testTranslateDictationUsesTranslationEndpoint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/dictation/translate")
            XCTAssertEqual(request.timeoutInterval, 60)
            let body = bodyJSON(from: request)
            XCTAssertEqual(body?["text"] as? String, "hello team")
            XCTAssertEqual(body?["target_language_code"] as? String, "ru")
            XCTAssertEqual(body?["target_language_name"] as? String, "Russian")
            XCTAssertEqual(body?["vocabulary"] as? [String], ["WaiComputer"])
            let context = body?["context"] as? [String: Any]
            let app = context?["app"] as? [String: Any]
            XCTAssertEqual(app?["name"] as? String, "Slack")
            XCTAssertEqual(app?["category"] as? String, "chat")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data("{\"text\":\"Привет, команда\"}".utf8))
        }

        let translated = try await client.translateDictation(
            text: "hello team",
            targetLanguageCode: "ru",
            targetLanguageName: "Russian",
            vocabulary: ["WaiComputer", "waiComputer", " "],
            context: DictationCleanupContext(
                app: DictationCleanupAppContext(name: "Slack", category: "chat")
            )
        )
        XCTAssertEqual(translated, "Привет, команда")
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

    func testDeleteRecordingPermanentAddsQueryFlag() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-del")
            XCTAssertTrue(request.url?.query?.contains("permanent=true") == true)

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 204,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data())
        }

        try await client.deleteRecording(id: "rec-del", permanent: true)
    }

    func testBulkRecordingOperationUsesSingleBulkEndpoint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings/bulk")

            let body = self.bodyJSON(from: request)
            XCTAssertEqual(body?["action"] as? String, "delete")
            XCTAssertEqual(body?["recording_ids"] as? [String], ["rec-1", "rec-2", "rec-3"])
            XCTAssertNil(body?["folder_id"] as? String)

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data(#"{"processed":3,"failed":0}"#.utf8))
        }

        let result = try await client.bulkRecordingOperation(
            recordingIds: ["rec-1", "rec-2", "rec-3"],
            action: .delete
        )
        XCTAssertEqual(result.processed, 3)
        XCTAssertEqual(result.failed, 0)
    }

    func testBulkRecordingMoveIncludesFolderId() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings/bulk")

            let body = self.bodyJSON(from: request)
            XCTAssertEqual(body?["action"] as? String, "move")
            XCTAssertEqual(body?["recording_ids"] as? [String], ["rec-1"])
            XCTAssertEqual(body?["folder_id"] as? String, "folder-42")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data(#"{"processed":1,"failed":0}"#.utf8))
        }

        let result = try await client.bulkRecordingOperation(
            recordingIds: ["rec-1"],
            action: .move,
            folderId: "folder-42"
        )
        XCTAssertEqual(result.processed, 1)
        XCTAssertEqual(result.failed, 0)
    }

    func testCreateRecordingShareLinkUsesShareEndpoint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-share/share")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 201,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "recording_id":"rec-share",
              "token":"share-token",
              "url":"https://wai.computer/share/share-token",
              "created_at":"2026-05-04T12:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let share = try await client.createRecordingShareLink(id: "rec-share")
        XCTAssertEqual(share.recordingId, "rec-share")
        XCTAssertEqual(share.url.absoluteString, "https://wai.computer/share/share-token")
    }

    func testExportRecordingServerFailureCapturesFingerprint() async {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-export/export")
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 502,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data("bad gateway".utf8))
        }

        do {
            _ = try await client.exportRecording(id: "rec-export", format: "markdown")
            XCTFail("Expected export failure")
        } catch let error as APIError {
            guard case let .httpError(statusCode, _) = error else {
                return XCTFail("Expected HTTP error, got \(error)")
            }
            XCTAssertEqual(statusCode, 502)
        } catch {
            XCTFail("Expected APIError, got \(error)")
        }

        XCTAssertFalse(
            SentryHelper.shouldCaptureFingerprint(
                "request:GET:/api/recordings/rec-export/export:http_502"
            )
        )
    }

    func testRestoreRecordingUsesRestoreEndpoint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-del/restore")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"id":"rec-del","title":"Restored","type":"note","deleted_at":null,"created_at":"2026-01-15T10:00:00Z"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let restored = try await client.restoreRecording(id: "rec-del")
        XCTAssertEqual(restored.id, "rec-del")
        XCTAssertNil(restored.deletedAt)
    }

    func testFolderEndpointsUseExpectedPaths() async throws {
        let client = makeClient()
        final class RequestCounter: @unchecked Sendable {
            var value = 0
        }
        let counter = RequestCounter()

        MockURLProtocol.requestHandler = { request in
            counter.value += 1
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: request.httpMethod == "DELETE" ? 204 : 200,
                httpVersion: nil,
                headerFields: nil
            )!

            switch counter.value {
            case 1:
                XCTAssertEqual(request.httpMethod, "GET")
                XCTAssertEqual(request.url?.path, "/api/folders")
                return (response, Data("[]".utf8))
            case 2:
                XCTAssertEqual(request.httpMethod, "POST")
                XCTAssertEqual(request.url?.path, "/api/folders")
                return (response, Data("{\"id\":\"folder-1\",\"name\":\"Projects\",\"created_at\":\"2026-01-01T00:00:00Z\"}".utf8))
            case 3:
                XCTAssertEqual(request.httpMethod, "PATCH")
                XCTAssertEqual(request.url?.path, "/api/folders/folder-1")
                return (response, Data("{\"id\":\"folder-1\",\"name\":\"Renamed\",\"created_at\":\"2026-01-01T00:00:00Z\"}".utf8))
            default:
                XCTAssertEqual(request.httpMethod, "DELETE")
                XCTAssertEqual(request.url?.path, "/api/folders/folder-1")
                return (response, Data())
            }
        }

        let listed = try await client.listFolders()
        XCTAssertTrue(listed.isEmpty)

        let created = try await client.createFolder(name: "Projects")
        XCTAssertEqual(created.name, "Projects")

        let updated = try await client.updateFolder(id: "folder-1", name: "Renamed")
        XCTAssertEqual(updated.name, "Renamed")

        try await client.deleteFolder(id: "folder-1")
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
            {"id":"u1","email":"user@example.com","created_at":"2026-01-01T00:00:00Z","has_password":false}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let user = try await client.getCurrentUser()
        XCTAssertEqual(user.id, "u1")
        XCTAssertFalse(user.hasPassword)
    }

    func testUploadItemPostsMultipartAndDecodesItem() async throws {
        let client = makeClient()
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("wai-test-\(UUID().uuidString).txt")
        try "hello upload body".data(using: .utf8)!.write(to: tmp)
        defer { try? FileManager.default.removeItem(at: tmp) }

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/items/upload")
            XCTAssertTrue(
                request.value(forHTTPHeaderField: "Content-Type")?
                    .contains("multipart/form-data") ?? false
            )
            let response = HTTPURLResponse(
                url: request.url!, statusCode: 201, httpVersion: nil, headerFields: nil
            )!
            let payload = """
            {"id":"itm-1","source":"upload","source_ref":null,"url":null,"kind":"note",\
            "title":"wai-test","body":"hello upload body","occurred_at":null,"state":"raw",\
            "status":"summarizing","error":null,"folder_id":null,\
            "created_at":"2026-06-01T00:00:00Z","summary":null}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let outcome = try await client.uploadItem(fileURL: tmp)
        guard case let .item(item) = outcome else {
            return XCTFail("expected .item outcome for a document upload")
        }
        XCTAssertEqual(item.id, "itm-1")
        XCTAssertEqual(item.kind, "note")
    }

    func testUploadMediaReturnsRecordingOutcome() async throws {
        let client = makeClient()
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("wai-test-\(UUID().uuidString).mp4")
        try Data("fake video bytes".utf8).write(to: tmp)
        defer { try? FileManager.default.removeItem(at: tmp) }

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.url?.path, "/api/items/upload")
            // Audio/video are accepted asynchronously: 202 + a processing marker,
            // NOT an Item — the client must not try to decode an Item here.
            let response = HTTPURLResponse(
                url: request.url!, statusCode: 202, httpVersion: nil, headerFields: nil
            )!
            let payload = #"{"kind":"recording","status":"processing","recording_id":"rec-media"}"#.data(using: .utf8)!
            return (response, payload)
        }

        let outcome = try await client.uploadItem(fileURL: tmp)
        guard case let .recording(status: status, recordingId: recordingId) = outcome else {
            return XCTFail("expected .recording outcome for an audio/video upload")
        }
        XCTAssertEqual(status, "processing")
        XCTAssertEqual(recordingId, "rec-media")
    }

    func testUploadMediaRequiresRecordingId() async throws {
        let client = makeClient()
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("wai-test-\(UUID().uuidString).mp4")
        try Data("fake video bytes".utf8).write(to: tmp)
        defer { try? FileManager.default.removeItem(at: tmp) }

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: request.url!, statusCode: 202, httpVersion: nil, headerFields: nil
            )!
            let payload = #"{"kind":"recording","status":"processing"}"#.data(using: .utf8)!
            return (response, payload)
        }

        do {
            _ = try await client.uploadItem(fileURL: tmp)
            XCTFail("Expected media upload decoding to require recording_id")
        } catch APIError.decodingError {
            return
        } catch {
            XCTFail("Expected decodingError, got \(error)")
        }
    }

    func testGetBrainGraphDecodes() async throws {
        let client = makeClient()
        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/brain/graph")
            let response = HTTPURLResponse(
                url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil
            )!
            let payload = """
            {"nodes":[{"id":"e1","label":"Anna","kind":"person","degree":2}],\
            "edges":[{"source":"e1","target":"e2","type":"cooccurrence","weight":2.0}],\
            "stats":{"entities":1,"people":1},\
            "overview":{"recordings":{"total":2,"summarized":1,"organized":1,"unorganized":1},\
            "materials":{"total":1,"summarized":1,"organized":1,"unorganized":0},\
            "pending_review_count":1,\
            "top_entities":[{"id":"e1","name":"Anna","type":"person","source_count":2,"recording_count":1,"material_count":1}],\
            "recent_sources":[{"id":"recording:r1","source_kind":"recording","source_id":"r1","title":"Launch sync","entity_count":2,"organized_at":null}],\
            "llm_requests":0}}
            """.data(using: .utf8)!
            return (response, payload)
        }
        let g = try await client.getBrainGraph()
        XCTAssertEqual(g.nodes.count, 1)
        XCTAssertEqual(g.nodes[0].label, "Anna")
        XCTAssertEqual(g.edges[0].type, "cooccurrence")
        XCTAssertEqual(g.stats["people"], 1)
        XCTAssertEqual(g.overview?.recordings.unorganized, 1)
        XCTAssertEqual(g.overview?.pendingReviewCount, 1)
        XCTAssertEqual(g.overview?.topEntities.first?.recordingCount, 1)
    }

    func testGetEntityPageDecodes() async throws {
        let client = makeClient()
        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.url?.path, "/api/entities/abc/page")
            let response = HTTPURLResponse(
                url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil
            )!
            let payload = """
            {"id":"abc","name":"GPU","type":"topic","mention_count":3,\
            "sources":[{"source_kind":"item","source_id":"i1","title":"Note","context":"ctx","occurred_at":null}],\
            "related":[{"id":"e2","name":"Anna","type":"person","shared":2}],\
            "overview":"GPU appears in 1 source.",\
            "facts":[{"id":"fact-1","text":"GPU launch is owned by Anna.","citation_ids":["item:i1"]}],\
            "citations":[{"id":"item:i1","source_kind":"item","source_id":"i1","title":"Note","context":"ctx","occurred_at":null}],\
            "timeline":[{"id":"event-1","title":"GPU launch","description":"Anna owns it.","occurred_at":null,"citation_ids":["item:i1"]}],\
            "related_explanations":[{"id":"e2","name":"Anna","type":"person","shared":2,"explanation":"Shares 2 sources.","citation_ids":["item:i1"]}],\
            "questions":[{"id":"question-1","text":"What ships first?","citation_ids":["item:i1"]}],\
            "actions":[{"id":"action-1","text":"Ask Anna","owner":"Mik","due_date":null,"status":"pending","citation_ids":["item:i1"]}],\
            "cache_status":"hit"}
            """.data(using: .utf8)!
            return (response, payload)
        }
        let p = try await client.getEntityPage(id: "abc")
        XCTAssertEqual(p.name, "GPU")
        XCTAssertEqual(p.mentionCount, 3)
        XCTAssertEqual(p.sources[0].title, "Note")
        XCTAssertEqual(p.related[0].name, "Anna")
        XCTAssertEqual(p.overview, "GPU appears in 1 source.")
        XCTAssertEqual(p.facts[0].text, "GPU launch is owned by Anna.")
        XCTAssertEqual(p.timeline[0].title, "GPU launch")
        XCTAssertEqual(p.relatedExplanations[0].explanation, "Shares 2 sources.")
        XCTAssertEqual(p.questions[0].text, "What ships first?")
        XCTAssertEqual(p.actions[0].text, "Ask Anna")
        XCTAssertEqual(p.cacheStatus, "hit")
    }
}
