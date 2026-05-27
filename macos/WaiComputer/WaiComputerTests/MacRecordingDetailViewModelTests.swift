import XCTest
@testable import WaiComputerKit

@MainActor
final class MacRecordingDetailViewModelTests: XCTestCase {
    private var backupRoot: URL!

    override func setUp() {
        super.setUp()
        backupRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("MacRecordingDetailViewModelTests")
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try? FileManager.default.createDirectory(at: backupRoot, withIntermediateDirectories: true)
        RecordingBackupStore.overrideBaseDirectory = backupRoot
    }

    override func tearDown() {
        MacRecordingDetailMockURLProtocol.requestHandler = nil
        RecordingBackupStore.overrideBaseDirectory = nil
        if let backupRoot {
            try? FileManager.default.removeItem(at: backupRoot)
        }
        super.tearDown()
    }

    func testFailedLoadForNewRecordingClearsPreviousDetail() async {
        let previousDetail = makeDetail(id: "previous-recording", title: "Previous Recording")
        let viewModel = MacRecordingDetailViewModel(initialDetail: previousDetail)
        let apiClient = makeAPIClient(statusCode: 500, body: #"{"detail":"Latest recording is not ready"}"#)

        await viewModel.load(recordingId: "latest-recording", apiClient: apiClient)

        XCTAssertNil(viewModel.recordingDetail)
        XCTAssertNotNil(viewModel.error)
        XCTAssertFalse(viewModel.isLoading)
    }

    func testFailedRefreshForCurrentRecordingKeepsDetailAndSurfacesError() async {
        let currentDetail = makeDetail(id: "current-recording", title: "Current Recording")
        let viewModel = MacRecordingDetailViewModel(initialDetail: currentDetail)
        let apiClient = makeAPIClient(statusCode: 503, body: #"{"detail":"Temporary outage"}"#)

        await viewModel.load(recordingId: "current-recording", apiClient: apiClient, showLoading: false)

        XCTAssertEqual(viewModel.recordingDetail?.id, currentDetail.id)
        XCTAssertNotNil(viewModel.error)
        XCTAssertFalse(viewModel.isLoading)
    }

    func testLoadUsesLocalRecoveryTranscriptWhenServerDetailHasNoSegments() async throws {
        let recordingId = "local-recovery-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            recordingType: .meeting,
            durationSeconds: 4,
            segments: [
                LiveTranscriptSegment(
                    text: "Recovered local transcript.",
                    speaker: "speaker_1",
                    isFinal: true,
                    startMs: 0,
                    endMs: 4_000,
                    confidence: 0.93
                )
            ]
        )
        _ = try RecordingBackupStore.recordSaveFailure(
            recordingId: recordingId,
            message: "Saved locally and waiting to sync."
        )

        let viewModel = MacRecordingDetailViewModel()
        let apiClient = makeAPIClient(
            statusCode: 200,
            body: makeRecordingDetailJSON(id: recordingId, status: "processing", segments: [])
        )

        await viewModel.load(recordingId: recordingId, apiClient: apiClient)

        XCTAssertEqual(viewModel.localRecoveryManifest?.recordingId, recordingId)
        XCTAssertEqual(viewModel.recordingDetail?.status, .processing)
        XCTAssertEqual(viewModel.recordingDetail?.segments.map(\.content), ["Recovered local transcript."])
        XCTAssertEqual(viewModel.recordingDetail?.segments.first?.rawLabel, "speaker_1")
        XCTAssertFalse(viewModel.isLoading)
    }

    func testServerProcessingLocalAudioBackupUsesSavedLocallyAvailability() async throws {
        let recordingId = "server-processing-local-audio-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        try RecordingBackupStore.markHasAudioFile(recordingId: recordingId)
        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            recordingType: .meeting,
            durationSeconds: 4,
            segments: []
        )
        try RecordingBackupStore.markServerProcessing(recordingId: recordingId)

        let viewModel = MacRecordingDetailViewModel()
        let apiClient = makeAPIClient(
            statusCode: 200,
            body: makeRecordingDetailJSON(id: recordingId, status: "processing", segments: [])
        )

        await viewModel.load(recordingId: recordingId, apiClient: apiClient)

        XCTAssertEqual(viewModel.localRecoveryManifest?.syncState, .serverProcessing)
        XCTAssertEqual(viewModel.recordingDetail?.segments.count, 0)
        XCTAssertEqual(viewModel.transcriptAvailability, .savedLocally)
        XCTAssertFalse(viewModel.isLoading)
    }

    private func makeDetail(id: String, title: String) -> RecordingDetail {
        RecordingDetail(
            id: id,
            title: title,
            type: .meeting,
            status: .ready,
            durationSeconds: 60,
            language: "en",
            createdAt: Date(timeIntervalSince1970: 1_709_292_000),
            segments: []
        )
    }

    private func makeAPIClient(statusCode: Int, body: String) -> APIClient {
        MacRecordingDetailMockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: statusCode,
                httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, Data(body.utf8))
        }

        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [MacRecordingDetailMockURLProtocol.self]
        let session = URLSession(configuration: configuration)
        return APIClient(baseURL: URL(string: "https://example.test")!, session: session)
    }

    private func makeRecordingDetailJSON(
        id: String,
        status: String,
        segments: [[String: Any]]
    ) -> String {
        let payload: [String: Any] = [
            "id": id,
            "title": "Server Detail",
            "type": "meeting",
            "status": status,
            "created_at": "2026-05-26T12:00:00Z",
            "segments": segments,
        ]
        let data = try! JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        return String(data: data, encoding: .utf8)!
    }
}

private final class MacRecordingDetailMockURLProtocol: URLProtocol, @unchecked Sendable {
    static var requestHandler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool {
        true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        guard let requestHandler = Self.requestHandler else {
            XCTFail("MacRecordingDetailMockURLProtocol.requestHandler is not set")
            client?.urlProtocol(self, didFailWithError: APIError.noData)
            return
        }

        do {
            let (response, data) = try requestHandler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}
