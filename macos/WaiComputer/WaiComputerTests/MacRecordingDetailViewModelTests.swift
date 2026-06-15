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

    func testGenerateSummaryUsesDurableBackgroundSummaryEndpoint() async {
        let recordingId = "summary-background"
        let viewModel = MacRecordingDetailViewModel(
            initialDetail: RecordingDetail(
                id: recordingId,
                title: "Needs Summary",
                type: .meeting,
                status: .ready,
                createdAt: Date(timeIntervalSince1970: 1_709_292_000),
                segments: [
                    Segment(
                        id: "segment-1",
                        speaker: "Speaker 1",
                        content: "Generate a durable summary.",
                        startMs: 0,
                        endMs: 1_000,
                        confidence: 0.98
                    )
                ]
            )
        )

        let apiClient = makeAPIClient { request in
            let path = request.url?.path ?? ""
            if request.httpMethod == "POST", path == "/api/recordings/\(recordingId)/summary-generation" {
                return (
                    202,
                    #"{"job_id":"job-1","recording_id":"summary-background","status":"succeeded","stage":"saving_summary","progress_percent":100,"message":"Summary generation finished."}"#
                )
            }
            return (404, #"{"detail":"Unexpected request"}"#)
        }

        await viewModel.generateSummary(recordingId: recordingId, apiClient: apiClient)

        XCTAssertNil(viewModel.error)
        XCTAssertNil(viewModel.recordingDetail?.summary)
        XCTAssertEqual(viewModel.recordingDetail?.summaryGeneration?.jobId, "job-1")
        XCTAssertEqual(viewModel.recordingDetail?.summaryGeneration?.status, "succeeded")
        XCTAssertFalse(viewModel.isGeneratingSummary(for: recordingId))
    }

    func testStartSummaryAudioGenerationUpdatesStateUntilReady() async {
        let recordingId = "summary-audio-ready"
        let initialDetail = RecordingDetail(
            id: recordingId,
            title: "Needs Audio",
            type: .meeting,
            status: .ready,
            createdAt: Date(timeIntervalSince1970: 1_709_292_000),
            segments: [],
            summary: Summary(summary: "Generated summary.")
        )
        let viewModel = MacRecordingDetailViewModel(initialDetail: initialDetail)
        let readyDetailJSON = makeRecordingDetailJSON(
            id: recordingId,
            status: "ready",
            segments: [],
            summary: ["summary": "Generated summary."],
            summaryAudio: [
                "artifact_id": "audio-1",
                "source_kind": "recording",
                "source_id": recordingId,
                "status": "succeeded",
                "stage": "completed",
                "progress_percent": 100,
                "message": "Summary audio is ready.",
            ]
        )
        let apiClient = makeAPIClient { request in
            let path = request.url?.path ?? ""
            if request.httpMethod == "POST", path == "/api/recordings/\(recordingId)/summary/audio" {
                return (200, """
                {
                  "artifact_id": "audio-1",
                  "source_kind": "recording",
                  "source_id": "\(recordingId)",
                  "status": "queued",
                  "stage": "queued",
                  "progress_percent": 5,
                  "message": "Summary audio generation is queued."
                }
                """)
            }
            if request.httpMethod == "GET", path == "/api/recordings/\(recordingId)" {
                return (200, readyDetailJSON)
            }
            return (404, #"{"detail":"Unexpected request"}"#)
        }

        await viewModel.startSummaryAudioGeneration(recordingId: recordingId, apiClient: apiClient)

        XCTAssertEqual(viewModel.recordingDetail?.summaryAudio?.status, "succeeded")
        XCTAssertFalse(viewModel.isGeneratingSummaryAudio(for: recordingId))
    }

    func testPlaySummaryAudioDownloadsAudioAndTogglesStop() async {
        let recordingId = "summary-audio-play"
        let fakePlayer = FakeMacSummaryAudioPlayer(duration: 20)
        let viewModel = MacRecordingDetailViewModel(
            initialDetail: RecordingDetail(
                id: recordingId,
                title: "Ready Audio",
                type: .meeting,
                status: .ready,
                createdAt: Date(timeIntervalSince1970: 1_709_292_000),
                segments: [],
                summary: Summary(summary: "Generated summary."),
                summaryAudio: SummaryAudioState(
                    artifactId: "audio-1",
                    sourceKind: "recording",
                    sourceId: recordingId,
                    status: "succeeded",
                    stage: "completed",
                    progressPercent: 100,
                    message: "Summary audio is ready."
                )
            ),
            summaryAudioPlayerFactory: { data in
                XCTAssertEqual(String(data: data, encoding: .utf8), "audio-bytes")
                return fakePlayer
            }
        )
        let apiClient = makeAPIClient { request in
            let path = request.url?.path ?? ""
            if request.httpMethod == "GET", path == "/api/recordings/\(recordingId)/summary/audio/file" {
                return (200, "audio-bytes")
            }
            return (404, #"{"detail":"Unexpected request"}"#)
        }

        await viewModel.playOrStopSummaryAudio(recordingId: recordingId, apiClient: apiClient)

        XCTAssertTrue(fakePlayer.didPrepare)
        XCTAssertTrue(fakePlayer.didPlay)
        XCTAssertTrue(viewModel.isPlayingSummaryAudio(for: recordingId))

        await viewModel.playOrStopSummaryAudio(recordingId: recordingId, apiClient: apiClient)

        XCTAssertTrue(fakePlayer.didStop)
        XCTAssertFalse(viewModel.isPlayingSummaryAudio(for: recordingId))
    }

    func testTranscriptTurnsMergeAndMemoizeWithInvalidationOnSpeakerChange() {
        let segments = [
            Segment(id: "s1", speaker: "Speaker 1", rawLabel: "speaker_1", content: "Hello there.", startMs: 0, endMs: 1_000),
            Segment(id: "s2", speaker: "Speaker 1", rawLabel: "speaker_1", content: "How are you?", startMs: 1_000, endMs: 2_000),
            Segment(id: "s3", speaker: "Speaker 2", rawLabel: "speaker_2", content: "I am well.", startMs: 2_000, endMs: 3_000),
        ]
        let detail = RecordingDetail(
            id: "rec-memo",
            title: "Memo",
            type: .meeting,
            status: .ready,
            createdAt: Date(timeIntervalSince1970: 1_709_292_000),
            segments: segments
        )
        let viewModel = MacRecordingDetailViewModel(initialDetail: detail)

        // Consecutive same-speaker utterances merge into one turn → 2 turns.
        let first = viewModel.transcriptTurns(languageCode: "en")
        XCTAssertEqual(first.count, 2)
        XCTAssertEqual(first.first?.text, "Hello there. How are you?")

        // Repeated call (the memoized path) returns identical turns.
        let second = viewModel.transcriptTurns(languageCode: "en")
        XCTAssertEqual(second.map(\.id), first.map(\.id))
        XCTAssertEqual(second.map(\.text), first.map(\.text))

        // Reassigning every utterance to one person must invalidate the cache and
        // regroup into a single turn (guards against stale memoized turns after a
        // speaker assignment).
        let reassigned = segments.map { segment in
            Segment(
                id: segment.id,
                speaker: segment.speaker,
                rawLabel: segment.rawLabel,
                personId: "person-1",
                content: segment.content,
                startMs: segment.startMs,
                endMs: segment.endMs
            )
        }
        viewModel.recordingDetail = RecordingDetail(
            id: "rec-memo",
            title: "Memo",
            type: .meeting,
            status: .ready,
            createdAt: Date(timeIntervalSince1970: 1_709_292_000),
            segments: reassigned
        )

        let afterReassign = viewModel.transcriptTurns(languageCode: "en")
        XCTAssertEqual(afterReassign.count, 1, "cache must invalidate when speaker assignments change")
        XCTAssertEqual(afterReassign.first?.text, "Hello there. How are you? I am well.")
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
        makeAPIClient { _ in (statusCode, body) }
    }

    private func makeAPIClient(
        handler: @escaping @Sendable (URLRequest) throws -> (Int, String)
    ) -> APIClient {
        MacRecordingDetailMockURLProtocol.requestHandler = { request in
            let (statusCode, body) = try handler(request)
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
        segments: [[String: Any]],
        summary: [String: Any]? = nil,
        summaryAudio: [String: Any]? = nil
    ) -> String {
        var payload: [String: Any] = [
            "id": id,
            "title": "Server Detail",
            "type": "meeting",
            "status": status,
            "created_at": "2026-05-26T12:00:00Z",
            "segments": segments,
        ]
        payload["summary"] = summary ?? NSNull()
        payload["summary_audio"] = summaryAudio ?? NSNull()
        let data = try! JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        return String(data: data, encoding: .utf8)!
    }
}

private final class FakeMacSummaryAudioPlayer: MacSummaryAudioPlaying {
    let duration: TimeInterval
    var didPrepare = false
    var didPlay = false
    var didStop = false

    init(duration: TimeInterval) {
        self.duration = duration
    }

    func prepareToPlay() -> Bool {
        didPrepare = true
        return true
    }

    func play() -> Bool {
        didPlay = true
        return true
    }

    func stop() {
        didStop = true
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
