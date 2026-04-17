import Foundation
import XCTest
@testable import WaiSayKit

private final class RequestCounter: @unchecked Sendable {
    private let lock = NSLock()
    private var value = 0

    func increment() -> Int {
        lock.withLock {
            value += 1
            return value
        }
    }
}

final class PendingRecordingSyncCoordinatorTests: XCTestCase {
    private var backupRoot: URL!

    override func setUp() {
        super.setUp()
        MockURLProtocol.requestHandler = nil
        backupRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("WaiSayKitPendingSyncTests")
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try? FileManager.default.createDirectory(at: backupRoot, withIntermediateDirectories: true)
        RecordingBackupStore.overrideBaseDirectory = backupRoot
    }

    override func tearDown() {
        RecordingBackupStore.overrideBaseDirectory = nil
        if let backupRoot {
            try? FileManager.default.removeItem(at: backupRoot)
        }
        super.tearDown()
    }

    private func makeClient(baseURL: URL = URL(string: "https://api.example.com")!) -> APIClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        return APIClient(baseURL: baseURL, session: session)
    }

    private func responsePayload(
        recordingId: String,
        status: String = "ready"
    ) -> Data {
        """
        {
          "id":"\(recordingId)",
          "type":"note",
          "status":"\(status)",
          "created_at":"2026-04-02T08:00:00Z",
          "segments":[]
        }
        """.data(using: .utf8)!
    }

    private func requestJSON(from request: URLRequest) throws -> [String: Any] {
        let data: Data
        if let body = request.httpBody {
            data = body
        } else if let stream = request.httpBodyStream {
            stream.open()
            defer { stream.close() }

            let bufferSize = 4096
            let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: bufferSize)
            defer { buffer.deallocate() }

            var output = Data()
            while stream.hasBytesAvailable {
                let bytesRead = stream.read(buffer, maxLength: bufferSize)
                if bytesRead <= 0 { break }
                output.append(buffer, count: bytesRead)
            }
            data = output
        } else {
            XCTFail("Expected request body")
            throw APIError.noData
        }

        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    func testPendingRecordingSyncUploadsSegmentBackupAndRemovesLocalCopy() async throws {
        let recordingId = "pending-sync-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Offline note",
            recordingType: .note,
            durationSeconds: 12,
            transcript: "Hello from offline mode",
            segments: [
                LiveTranscriptSegment(
                    text: "Hello from offline mode",
                    speaker: "Speaker 1",
                    isFinal: true,
                    startMs: 0,
                    endMs: 1200,
                    confidence: 0.97
                )
            ]
        )

        let client = makeClient()
        await client.setAccessToken("test-token")

        let synced = expectation(description: "pending sync finished")
        let observer = NotificationCenter.default.addObserver(
            forName: .pendingRecordingSyncDidFinish,
            object: nil,
            queue: nil
        ) { notification in
            if notification.userInfo?["recordingId"] as? String == recordingId {
                synced.fulfill()
            }
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings/\(recordingId)/transcript")

            let json = try self.requestJSON(from: request)
            let segments = try XCTUnwrap(json["segments"] as? [[String: Any]])
            XCTAssertEqual(segments.count, 1)
            XCTAssertEqual(segments.first?["text"] as? String, "Hello from offline mode")

            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, self.responsePayload(recordingId: recordingId))
        }

        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
        await fulfillment(of: [synced], timeout: 2)

        XCTAssertNil(try RecordingBackupStore.existingBackup(recordingId: recordingId))
    }

    func testPendingRecordingSyncSynthesizesSegmentFromTranscriptFallback() async throws {
        let recordingId = "pending-sync-fallback-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Transcript only",
            recordingType: .note,
            durationSeconds: 9,
            transcript: "Recovered transcript text",
            segments: []
        )

        let client = makeClient()
        await client.setAccessToken("test-token")

        let synced = expectation(description: "pending sync finished from fallback")
        let observer = NotificationCenter.default.addObserver(
            forName: .pendingRecordingSyncDidFinish,
            object: nil,
            queue: nil
        ) { notification in
            if notification.userInfo?["recordingId"] as? String == recordingId {
                synced.fulfill()
            }
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings/\(recordingId)/transcript")

            let json = try self.requestJSON(from: request)
            let segments = try XCTUnwrap(json["segments"] as? [[String: Any]])
            XCTAssertEqual(segments.count, 1)
            XCTAssertEqual(segments.first?["text"] as? String, "Recovered transcript text")
            XCTAssertEqual(segments.first?["start_ms"] as? Int, 0)
            XCTAssertEqual(segments.first?["end_ms"] as? Int, 9000)

            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, self.responsePayload(recordingId: recordingId))
        }

        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
        await fulfillment(of: [synced], timeout: 2)

        XCTAssertNil(try RecordingBackupStore.existingBackup(recordingId: recordingId))
    }

    func testPendingRecordingSyncCompletesSilentBackupWithoutSegments() async throws {
        let recordingId = "pending-sync-silent-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Silent note",
            recordingType: .note,
            durationSeconds: 4,
            transcript: nil,
            segments: []
        )

        let client = makeClient()
        await client.setAccessToken("test-token")

        let synced = expectation(description: "pending sync finished for silent recording")
        let observer = NotificationCenter.default.addObserver(
            forName: .pendingRecordingSyncDidFinish,
            object: nil,
            queue: nil
        ) { notification in
            if notification.userInfo?["recordingId"] as? String == recordingId {
                synced.fulfill()
            }
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings/\(recordingId)/transcript")

            let json = try self.requestJSON(from: request)
            let segments = try XCTUnwrap(json["segments"] as? [[String: Any]])
            XCTAssertTrue(segments.isEmpty)
            XCTAssertEqual(json["duration_seconds"] as? Int, 4)

            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, self.responsePayload(recordingId: recordingId))
        }

        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
        await fulfillment(of: [synced], timeout: 2)

        XCTAssertNil(try RecordingBackupStore.existingBackup(recordingId: recordingId))
    }

    func testPendingRecordingSyncPrefersAudioUploadWhenBackupHasAudioFile() async throws {
        let recordingId = "pending-sync-audio-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Audio recovery",
            recordingType: .note,
            durationSeconds: 7,
            transcript: nil,
            segments: []
        )
        try RecordingBackupStore.markHasAudioFile(recordingId: recordingId)
        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Audio recovery",
            recordingType: .note,
            durationSeconds: 7,
            transcript: nil,
            segments: []
        )

        let audioURL = try RecordingBackupStore.audioFileURL(recordingId: recordingId)
        try Data("fake-wav".utf8).write(to: audioURL)

        let client = makeClient()
        await client.setAccessToken("test-token")

        let synced = expectation(description: "pending audio backup synced")
        let observer = NotificationCenter.default.addObserver(
            forName: .pendingRecordingSyncDidFinish,
            object: nil,
            queue: nil
        ) { notification in
            if notification.userInfo?["recordingId"] as? String == recordingId {
                synced.fulfill()
            }
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings/\(recordingId)/upload")
            XCTAssertTrue(request.value(forHTTPHeaderField: "Content-Type")?.contains("multipart/form-data") == true)

            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, self.responsePayload(recordingId: recordingId))
        }

        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
        await fulfillment(of: [synced], timeout: 2)

        XCTAssertNil(try RecordingBackupStore.existingBackup(recordingId: recordingId))
    }

    func testScheduleSyncWakesBackoffImmediatelyAfterConnectivityReturns() async throws {
        let recordingId = "pending-sync-retry-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Retry me",
            recordingType: .note,
            durationSeconds: 5,
            transcript: "Wake the retry loop",
            segments: [
                LiveTranscriptSegment(
                    text: "Wake the retry loop",
                    speaker: nil,
                    isFinal: true,
                    startMs: 0,
                    endMs: 5000,
                    confidence: 1
                )
            ]
        )

        let client = makeClient()
        await client.setAccessToken("test-token")

        let retried = expectation(description: "pending sync retries immediately")
        let synced = expectation(description: "pending sync finishes after retry")
        let requestCounter = RequestCounter()
        let observer = NotificationCenter.default.addObserver(
            forName: .pendingRecordingSyncDidFinish,
            object: nil,
            queue: nil
        ) { notification in
            if notification.userInfo?["recordingId"] as? String == recordingId {
                synced.fulfill()
            }
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        MockURLProtocol.requestHandler = { request in
            let currentRequest = requestCounter.increment()

            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings/\(recordingId)/transcript")

            if currentRequest == 1 {
                throw URLError(.notConnectedToInternet)
            }

            retried.fulfill()
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, self.responsePayload(recordingId: recordingId))
        }

        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)

        try? await Task.sleep(for: .milliseconds(200))
        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)

        await fulfillment(of: [retried, synced], timeout: 1.5)

        XCTAssertNil(try RecordingBackupStore.existingBackup(recordingId: recordingId))
    }

    func testSyncRetriesWithExponentialBackoffAndEventuallySucceeds() async throws {
        let recordingId = "pending-sync-backoff-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Backoff test",
            recordingType: .note,
            durationSeconds: 3,
            transcript: "Exponential backoff",
            segments: [
                LiveTranscriptSegment(
                    text: "Exponential backoff",
                    speaker: nil,
                    isFinal: true,
                    startMs: 0,
                    endMs: 3000,
                    confidence: 1
                )
            ]
        )

        let client = makeClient()
        await client.setAccessToken("test-token")

        let requestCounter = RequestCounter()
        let synced = expectation(description: "sync succeeds after retries")
        let observer = NotificationCenter.default.addObserver(
            forName: .pendingRecordingSyncDidFinish,
            object: nil,
            queue: nil
        ) { notification in
            if notification.userInfo?["recordingId"] as? String == recordingId {
                synced.fulfill()
            }
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        // Fail 3 times, then succeed
        MockURLProtocol.requestHandler = { request in
            let attempt = requestCounter.increment()
            if attempt <= 3 {
                throw URLError(.notConnectedToInternet)
            }

            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, self.responsePayload(recordingId: recordingId))
        }

        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)

        // Wake the backoff delay after each failure to speed up the test
        for _ in 0..<3 {
            try? await Task.sleep(for: .milliseconds(100))
            await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
        }

        await fulfillment(of: [synced], timeout: 3)
        XCTAssertNil(try RecordingBackupStore.existingBackup(recordingId: recordingId))
    }

    func testPermanentFailureSkippedDuringSyncLoop() async throws {
        let permanentId = "pending-permanent-\(UUID().uuidString)"
        let normalId = "pending-normal-\(UUID().uuidString)"
        defer {
            try? RecordingBackupStore.removeRecording(recordingId: permanentId)
            try? RecordingBackupStore.removeRecording(recordingId: normalId)
        }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: permanentId,
            title: "Permanent failure",
            recordingType: .note,
            durationSeconds: 2,
            transcript: nil,
            segments: []
        )
        try RecordingBackupStore.markPermanentFailure(recordingId: permanentId)

        _ = try RecordingBackupStore.saveRecording(
            recordingId: normalId,
            title: "Normal sync",
            recordingType: .note,
            durationSeconds: 2,
            transcript: "Should sync",
            segments: [
                LiveTranscriptSegment(
                    text: "Should sync",
                    speaker: nil,
                    isFinal: true,
                    startMs: 0,
                    endMs: 2000,
                    confidence: 1
                )
            ]
        )

        let client = makeClient()
        await client.setAccessToken("test-token")

        let synced = expectation(description: "normal recording synced")
        let observer = NotificationCenter.default.addObserver(
            forName: .pendingRecordingSyncDidFinish,
            object: nil,
            queue: nil
        ) { notification in
            if notification.userInfo?["recordingId"] as? String == normalId {
                synced.fulfill()
            }
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, self.responsePayload(recordingId: normalId))
        }

        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
        await fulfillment(of: [synced], timeout: 2)

        // Normal recording removed, permanent failure still exists
        XCTAssertNil(try RecordingBackupStore.existingBackup(recordingId: normalId))
        XCTAssertNotNil(try RecordingBackupStore.existingBackup(recordingId: permanentId))
    }

    func testSyncMarks401AsAuthenticationRequired() async throws {
        let recordingId = "pending-sync-401-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Auth failed",
            recordingType: .note,
            durationSeconds: 3,
            transcript: "Unauthorized test",
            segments: [
                LiveTranscriptSegment(
                    text: "Unauthorized test",
                    speaker: nil,
                    isFinal: true,
                    startMs: 0,
                    endMs: 3000,
                    confidence: 1
                )
            ]
        )

        let client = makeClient()
        await client.setAccessToken("expired-token")

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 401,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data())
        }

        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
        // Allow sync loop to process
        try await Task.sleep(for: .milliseconds(500))

        // Backup should still exist, but pause until a valid session returns.
        let backup = try XCTUnwrap(RecordingBackupStore.existingBackup(recordingId: recordingId))
        let manifest = try XCTUnwrap(RecordingBackupStore.manifest(recordingId: recordingId))
        XCTAssertFalse(manifest.isPermanentFailure)
        XCTAssertTrue(manifest.requiresAuthentication)
        XCTAssertNotNil(manifest.lastErrorMessage)
        XCTAssertEqual(backup.recordingId, recordingId)
    }

    func testSyncRecoversAfterReauthentication() async throws {
        let recordingId = "pending-sync-reauth-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Needs reauth",
            recordingType: .note,
            durationSeconds: 4,
            transcript: "Recover me",
            segments: [
                LiveTranscriptSegment(
                    text: "Recover me",
                    speaker: nil,
                    isFinal: true,
                    startMs: 0,
                    endMs: 4000,
                    confidence: 1
                )
            ]
        )

        let client = makeClient()
        await client.setAccessToken("expired-token")

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 401,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data())
        }

        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
        try await Task.sleep(for: .milliseconds(500))

        var manifest = try XCTUnwrap(RecordingBackupStore.manifest(recordingId: recordingId))
        XCTAssertTrue(manifest.requiresAuthentication)
        XCTAssertFalse(manifest.isPermanentFailure)

        let synced = expectation(description: "pending sync finishes after reauth")
        let observer = NotificationCenter.default.addObserver(
            forName: .pendingRecordingSyncDidFinish,
            object: nil,
            queue: nil
        ) { notification in
            if notification.userInfo?["recordingId"] as? String == recordingId {
                synced.fulfill()
            }
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        await client.setAccessToken("fresh-token")
        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, self.responsePayload(recordingId: recordingId))
        }

        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
        await fulfillment(of: [synced], timeout: 2)

        XCTAssertNil(try RecordingBackupStore.existingBackup(recordingId: recordingId))
        XCTAssertNil(try RecordingBackupStore.manifest(recordingId: recordingId))
    }

    func testSyncMarks413AsPermanentFailure() async throws {
        let recordingId = "pending-sync-413-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Too large",
            recordingType: .note,
            durationSeconds: 5,
            transcript: "Large recording",
            segments: [
                LiveTranscriptSegment(
                    text: "Large recording",
                    speaker: nil,
                    isFinal: true,
                    startMs: 0,
                    endMs: 5000,
                    confidence: 1
                )
            ]
        )

        let client = makeClient()
        await client.setAccessToken("test-token")

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 413,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, "File too large".data(using: .utf8)!)
        }

        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
        try await Task.sleep(for: .milliseconds(500))

        let manifest = try XCTUnwrap(RecordingBackupStore.manifest(recordingId: recordingId))
        XCTAssertTrue(manifest.isPermanentFailure)
        XCTAssertTrue(manifest.lastErrorMessage?.contains("too large") == true)
    }

    func testSyncRecordsFailureWhenServerReturnsFailedStatus() async throws {
        let recordingId = "pending-sync-server-fail-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Server processing failed",
            recordingType: .note,
            durationSeconds: 4,
            transcript: "Processing test",
            segments: [
                LiveTranscriptSegment(
                    text: "Processing test",
                    speaker: nil,
                    isFinal: true,
                    startMs: 0,
                    endMs: 4000,
                    confidence: 1
                )
            ]
        )

        let client = makeClient()
        await client.setAccessToken("test-token")

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, self.responsePayload(recordingId: recordingId, status: "failed"))
        }

        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
        try await Task.sleep(for: .milliseconds(500))

        // Backup should still exist (not removed) with error recorded
        XCTAssertNotNil(try RecordingBackupStore.existingBackup(recordingId: recordingId))
        let manifest = try XCTUnwrap(RecordingBackupStore.manifest(recordingId: recordingId))
        XCTAssertFalse(manifest.isPermanentFailure, "Server failure is retryable, not permanent")
        XCTAssertNotNil(manifest.lastErrorMessage)
    }

    func testSyncHandlesMultipleBackupsInOnePass() async throws {
        let id1 = "pending-sync-multi-1-\(UUID().uuidString)"
        let id2 = "pending-sync-multi-2-\(UUID().uuidString)"
        let id3 = "pending-sync-multi-3-\(UUID().uuidString)"
        defer {
            try? RecordingBackupStore.removeRecording(recordingId: id1)
            try? RecordingBackupStore.removeRecording(recordingId: id2)
            try? RecordingBackupStore.removeRecording(recordingId: id3)
        }

        for id in [id1, id2, id3] {
            _ = try RecordingBackupStore.saveRecording(
                recordingId: id,
                title: "Multi \(id)",
                recordingType: .note,
                durationSeconds: 2,
                transcript: "Content for \(id)",
                segments: [
                    LiveTranscriptSegment(
                        text: "Content for \(id)",
                        speaker: nil,
                        isFinal: true,
                        startMs: 0,
                        endMs: 2000,
                        confidence: 1
                    )
                ]
            )
        }

        let client = makeClient()
        await client.setAccessToken("test-token")

        let syncedIds = SendableSet()
        let allSynced = expectation(description: "all three recordings synced")

        let observer = NotificationCenter.default.addObserver(
            forName: .pendingRecordingSyncDidFinish,
            object: nil,
            queue: nil
        ) { notification in
            if let rid = notification.userInfo?["recordingId"] as? String,
               [id1, id2, id3].contains(rid) {
                syncedIds.insert(rid)
                if syncedIds.count == 3 {
                    allSynced.fulfill()
                }
            }
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        MockURLProtocol.requestHandler = { request in
            let path = request.url?.path ?? ""
            // Extract recording ID from path like /api/recordings/{id}/transcript
            let components = path.split(separator: "/")
            let recordingId = components.count >= 4 ? String(components[3]) : "unknown"

            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, self.responsePayload(recordingId: recordingId))
        }

        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
        await fulfillment(of: [allSynced], timeout: 3)

        // All three backups should be removed
        XCTAssertNil(try RecordingBackupStore.existingBackup(recordingId: id1))
        XCTAssertNil(try RecordingBackupStore.existingBackup(recordingId: id2))
        XCTAssertNil(try RecordingBackupStore.existingBackup(recordingId: id3))
    }
}

private final class SendableSet: @unchecked Sendable {
    private var set: Set<String> = []
    private let lock = NSLock()

    func insert(_ value: String) {
        _ = lock.withLock { set.insert(value) }
    }

    var count: Int {
        lock.withLock { set.count }
    }
}
