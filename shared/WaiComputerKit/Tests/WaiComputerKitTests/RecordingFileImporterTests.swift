import Foundation
import XCTest

@testable import WaiComputerKit

private final class RecordingFileImporterMockURLProtocol: URLProtocol, @unchecked Sendable {
    static var requestHandler: (@Sendable (URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool {
        true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        guard let handler = Self.requestHandler else {
            XCTFail("RecordingFileImporterMockURLProtocol.requestHandler is not set")
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

private final class RecordingImportRequestRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var requests: [(method: String, path: String)] = []
    private var createBody: Data?

    func record(_ request: URLRequest) {
        lock.lock()
        defer { lock.unlock() }
        requests.append((request.httpMethod ?? "", request.url?.path ?? ""))
        if request.url?.path == "/api/recordings" {
            createBody = Self.bodyData(from: request)
        }
    }

    var snapshot: [(method: String, path: String)] {
        lock.lock()
        defer { lock.unlock() }
        return requests
    }

    var recordedCreateBody: Data? {
        lock.lock()
        defer { lock.unlock() }
        return createBody
    }

    private static func bodyData(from request: URLRequest) -> Data? {
        if let data = request.httpBody {
            return data
        }
        guard let stream = request.httpBodyStream else {
            return nil
        }

        stream.open()
        defer { stream.close() }
        let bufferSize = 4_096
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: bufferSize)
        defer { buffer.deallocate() }
        var data = Data()
        while stream.hasBytesAvailable {
            let count = stream.read(buffer, maxLength: bufferSize)
            if count <= 0 {
                break
            }
            data.append(buffer, count: count)
        }
        return data
    }
}

final class RecordingFileImporterTests: XCTestCase {
    override func tearDown() {
        RecordingFileImporterMockURLProtocol.requestHandler = nil
        super.tearDown()
    }

    func testImportPreservesFilenameWithoutExtension() async throws {
        let file = try makeTemporaryAudioFile(named: "Quarterly review.m4a")
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let recorder = RecordingImportRequestRecorder()
        let client = makeClient()

        RecordingFileImporterMockURLProtocol.requestHandler = { request in
            recorder.record(request)
            switch (request.httpMethod, request.url?.path) {
            case ("POST", "/api/recordings"):
                return Self.response(
                    for: request,
                    status: 200,
                    body: Self.recordingJSON(id: "rec-1", title: "Quarterly review")
                )
            case ("POST", "/api/recordings/rec-1/upload"):
                return Self.response(
                    for: request,
                    status: 200,
                    body: Self.detailJSON(id: "rec-1", title: "Quarterly review")
                )
            default:
                XCTFail("Unexpected request: \(request.httpMethod ?? "") \(request.url?.path ?? "")")
                return Self.response(for: request, status: 500, body: #"{"detail":"Unexpected request"}"#)
            }
        }

        let outcome = await RecordingFileImporter.importFile(
            file,
            apiClient: client,
            processingFailureFallback: "Processing failed."
        )

        guard case .success(let recording) = outcome else {
            return XCTFail("Expected successful import, got \(outcome)")
        }
        XCTAssertEqual(recording.id, "rec-1")

        let body = try XCTUnwrap(recorder.recordedCreateBody)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
        XCTAssertEqual(json["title"] as? String, "Quarterly review")
        XCTAssertEqual(json["title_mode"] as? String, "preserve")
    }

    func testUploadFailureDeletesProvisionalRecording() async throws {
        let file = try makeTemporaryAudioFile(named: "broken.wav")
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let recorder = RecordingImportRequestRecorder()
        let client = makeClient()

        RecordingFileImporterMockURLProtocol.requestHandler = { request in
            recorder.record(request)
            switch (request.httpMethod, request.url?.path) {
            case ("POST", "/api/recordings"):
                return Self.response(
                    for: request,
                    status: 200,
                    body: Self.recordingJSON(id: "rec-broken", title: "broken")
                )
            case ("POST", "/api/recordings/rec-broken/upload"):
                return Self.response(for: request, status: 500, body: #"{"detail":"Upload rejected"}"#)
            case ("DELETE", "/api/recordings/rec-broken"):
                return Self.response(for: request, status: 204, body: "")
            default:
                XCTFail("Unexpected request: \(request.httpMethod ?? "") \(request.url?.path ?? "")")
                return Self.response(for: request, status: 500, body: #"{"detail":"Unexpected request"}"#)
            }
        }

        let outcome = await RecordingFileImporter.importFile(
            file,
            apiClient: client,
            processingFailureFallback: "Processing failed."
        )

        guard case .failure(let failure) = outcome else {
            return XCTFail("Expected failed import, got \(outcome)")
        }
        XCTAssertEqual(failure.filename, "broken.wav")
        XCTAssertTrue(
            recorder.snapshot.contains {
                $0.method == "DELETE" && $0.path == "/api/recordings/rec-broken"
            }
        )
    }

    func testProcessingFailureKeepsFailedRecordingAndReturnsReadableMessage() async throws {
        let file = try makeTemporaryAudioFile(named: "silent.m4a")
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let recorder = RecordingImportRequestRecorder()
        let client = makeClient()

        RecordingFileImporterMockURLProtocol.requestHandler = { request in
            recorder.record(request)
            switch (request.httpMethod, request.url?.path) {
            case ("POST", "/api/recordings"):
                return Self.response(
                    for: request,
                    status: 200,
                    body: Self.recordingJSON(id: "rec-silent", title: "silent")
                )
            case ("POST", "/api/recordings/rec-silent/upload"):
                return Self.response(
                    for: request,
                    status: 200,
                    body: """
                    {
                      "id":"rec-silent",
                      "title":"silent",
                      "automatic_title_pending":false,
                      "type":"note",
                      "status":"failed",
                      "failure_message":"No speech was detected.",
                      "created_at":"2026-07-23T10:00:00Z",
                      "segments":[],
                      "action_items":[],
                      "highlights":[]
                    }
                    """
                )
            default:
                XCTFail("Unexpected request: \(request.httpMethod ?? "") \(request.url?.path ?? "")")
                return Self.response(for: request, status: 500, body: #"{"detail":"Unexpected request"}"#)
            }
        }

        let outcome = await RecordingFileImporter.importFile(
            file,
            apiClient: client,
            processingFailureFallback: "Processing failed."
        )

        guard case .failure(let failure) = outcome else {
            return XCTFail("Expected processing failure, got \(outcome)")
        }
        XCTAssertEqual(failure.filename, "silent.m4a")
        XCTAssertEqual(failure.message, "No speech was detected.")
        XCTAssertFalse(recorder.snapshot.contains { $0.method == "DELETE" })
    }

    private func makeClient() -> APIClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [RecordingFileImporterMockURLProtocol.self]
        return APIClient(
            baseURL: URL(string: "https://api.example.com")!,
            session: URLSession(configuration: configuration)
        )
    }

    private func makeTemporaryAudioFile(named name: String) throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("RecordingFileImporterTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let file = directory.appendingPathComponent(name)
        try Data("audio".utf8).write(to: file)
        return file
    }

    private static func response(
        for request: URLRequest,
        status: Int,
        body: String
    ) -> (HTTPURLResponse, Data) {
        (
            HTTPURLResponse(
                url: request.url!,
                statusCode: status,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!,
            Data(body.utf8)
        )
    }

    private static func recordingJSON(id: String, title: String) -> String {
        """
        {
          "id":"\(id)",
          "title":"\(title)",
          "automatic_title_pending":false,
          "type":"note",
          "status":"pending_upload",
          "created_at":"2026-07-23T10:00:00Z"
        }
        """
    }

    private static func detailJSON(id: String, title: String) -> String {
        """
        {
          "id":"\(id)",
          "title":"\(title)",
          "automatic_title_pending":false,
          "type":"note",
          "status":"processing",
          "created_at":"2026-07-23T10:00:00Z",
          "segments":[],
          "action_items":[],
          "highlights":[]
        }
        """
    }
}
