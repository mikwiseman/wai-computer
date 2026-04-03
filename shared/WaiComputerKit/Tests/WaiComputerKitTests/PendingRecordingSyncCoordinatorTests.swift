import Foundation
import XCTest
@testable import WaiComputerKit

private final class RequestCounter: @unchecked Sendable {
    private let lock = NSLock()
    private var value = 0

    func increment() -> Int {
        lock.lock()
        defer { lock.unlock() }
        value += 1
        return value
    }
}

final class PendingRecordingSyncCoordinatorTests: XCTestCase {
    private var backupRoot: URL!

    override func setUp() {
        super.setUp()
        MockURLProtocol.requestHandler = nil
        backupRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("WaiComputerKitPendingSyncTests")
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
}
