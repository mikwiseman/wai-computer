import Foundation
import XCTest
@testable import WaiComputerKit

final class WebSocketManagerExtendedTests: XCTestCase {

    private let decoder = JSONDecoder()

    // MARK: - collectedSegments empty on init

    func testCollectedSegmentsEmptyOnInit() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        let segments = await manager.collectedSegments
        XCTAssertTrue(segments.isEmpty, "collectedSegments should be empty immediately after init")
    }

    // MARK: - buildElevenLabsURL

    func testBuildElevenLabsURLIncludesRealtimeParams() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient, language: "multi", channels: 1)

        let url = try await manager.buildElevenLabsURL(
            token: "sutkn_123",
            model: "scribe_v2_realtime",
            commitStrategy: "vad"
        )
        let urlString = url.absoluteString

        XCTAssertTrue(urlString.hasPrefix("wss://api.elevenlabs.io/v1/speech-to-text/realtime?"))
        XCTAssertTrue(urlString.contains("model_id=scribe_v2_realtime"))
        XCTAssertTrue(urlString.contains("token=sutkn_123"))
        XCTAssertTrue(urlString.contains("include_timestamps=true"))
        XCTAssertTrue(urlString.contains("audio_format=pcm_16000"))
        XCTAssertTrue(urlString.contains("include_language_detection=true"))
        XCTAssertTrue(urlString.contains("commit_strategy=vad"))
    }

    func testAudioChunkMessageIncludesExplicitCommitFlag() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        let message = await manager.testingMakeElevenLabsAudioChunkMessage(
            data: Data([0x01, 0x02, 0x03]),
            previousText: nil,
            commit: false
        )

        let payload = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: Data(message.utf8)) as? [String: Any]
        )

        XCTAssertEqual(payload["message_type"] as? String, "input_audio_chunk")
        XCTAssertEqual(payload["commit"] as? Bool, false)
        XCTAssertEqual(payload["sample_rate"] as? Int, 16_000)
        XCTAssertNotNil(payload["audio_base_64"] as? String)
    }

    // MARK: - events stream survives disconnects

    func testEventStreamRemainsUsableAfterDisconnect() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        let stream = await manager.events

        let task = Task<[WebSocketEvent], Never> {
            var iterator = stream.makeAsyncIterator()
            var events: [WebSocketEvent] = []
            if let first = await iterator.next() {
                events.append(first)
            }
            if let second = await iterator.next() {
                events.append(second)
            }
            return events
        }

        await manager.disconnect()
        await manager.testingYieldEvent(.reconnected)

        let events = await task.value
        XCTAssertEqual(events.count, 2)
        if case .disconnected = events[0] {} else {
            XCTFail("Expected disconnect event first")
        }
        if case .reconnected = events[1] {} else {
            XCTFail("Expected a later event after disconnect")
        }
    }

    // MARK: - WebSocketEvent pattern matching

    func testWebSocketEventPatternMatching() {
        let segment = LiveTranscriptSegment(
            text: "hello",
            speaker: "Speaker 0",
            isFinal: true,
            startMs: 0,
            endMs: 500,
            confidence: 0.99
        )

        let events: [WebSocketEvent] = [
            .connected,
            .transcript(segment),
            .disconnected(nil),
            .disconnected(URLError(.timedOut)),
            .reconnecting(attempt: 1, maxAttempts: 10),
            .reconnected,
            .reconnectionFailed(nil),
        ]

        // Verify each case matches correctly
        var connectedCount = 0
        var transcriptCount = 0
        var disconnectedCount = 0
        var reconnectingCount = 0
        var reconnectedCount = 0
        var reconnectionFailedCount = 0

        for event in events {
            switch event {
            case .connected:
                connectedCount += 1
            case .transcript(let seg):
                transcriptCount += 1
                XCTAssertEqual(seg.text, "hello")
                XCTAssertEqual(seg.confidence, 0.99)
            case .disconnected(let error):
                disconnectedCount += 1
                if disconnectedCount == 1 {
                    XCTAssertNil(error, "First disconnect should have nil error")
                } else {
                    XCTAssertNotNil(error, "Second disconnect should have an error")
                }
            case .reconnecting(let attempt, let maxAttempts):
                reconnectingCount += 1
                XCTAssertEqual(attempt, 1)
                XCTAssertEqual(maxAttempts, 10)
            case .reconnected:
                reconnectedCount += 1
            case .reconnectionFailed(let error):
                reconnectionFailedCount += 1
                XCTAssertNil(error)
            }
        }

        XCTAssertEqual(connectedCount, 1)
        XCTAssertEqual(transcriptCount, 1)
        XCTAssertEqual(disconnectedCount, 2)
        XCTAssertEqual(reconnectingCount, 1)
        XCTAssertEqual(reconnectedCount, 1)
        XCTAssertEqual(reconnectionFailedCount, 1)
    }

    // MARK: - LiveTranscriptSegment with all nil optional fields

    func testLiveTranscriptSegmentAllNilOptionals() throws {
        // Only 'speaker' is optional in the struct, but test JSON with missing speaker
        let json = """
        {
            "text": "",
            "is_final": false,
            "start_ms": 0,
            "end_ms": 0,
            "confidence": 0.0
        }
        """.data(using: .utf8)!

        let segment = try decoder.decode(LiveTranscriptSegment.self, from: json)
        XCTAssertNil(segment.speaker, "Speaker should be nil when absent from JSON")
        XCTAssertEqual(segment.text, "")
        XCTAssertFalse(segment.isFinal)
        XCTAssertEqual(segment.startMs, 0)
        XCTAssertEqual(segment.endMs, 0)
        XCTAssertEqual(segment.confidence, 0.0)
    }

    func testLiveTranscriptSegmentExplicitNullSpeaker() throws {
        let json = """
        {
            "text": "test",
            "speaker": null,
            "is_final": true,
            "start_ms": 100,
            "end_ms": 200,
            "confidence": 0.5
        }
        """.data(using: .utf8)!

        let segment = try decoder.decode(LiveTranscriptSegment.self, from: json)
        XCTAssertNil(segment.speaker, "Speaker should be nil when explicitly null")
        XCTAssertEqual(segment.text, "test")
        XCTAssertTrue(segment.isFinal)
    }

    // MARK: - WebSocketConnectionError invalidURL

    func testConnectionErrorInvalidURLDescription() {
        let error = WebSocketConnectionError.invalidURL
        XCTAssertNotNil(error.errorDescription)
        XCTAssertTrue(error.errorDescription!.contains("URL"),
                       "invalidURL description should mention URL")
    }

    // MARK: - WebSocketConnectionError disconnected with underlying error message

    func testConnectionErrorDisconnectedWithUnderlyingError() {
        let underlying = URLError(.networkConnectionLost)
        let error = WebSocketConnectionError.disconnected(underlying)
        XCTAssertNotNil(error.errorDescription)
        // The description should come from the underlying error
        XCTAssertEqual(error.errorDescription, underlying.localizedDescription)
    }

    func testConnectionErrorDisconnectedNilUsesDefault() {
        let error = WebSocketConnectionError.disconnected(nil)
        XCTAssertEqual(error.errorDescription, "The WebSocket disconnected.")
    }

    // MARK: - WebSocketConnectionError reconnectionExhausted

    func testConnectionErrorReconnectionExhausted() {
        let error = WebSocketConnectionError.reconnectionExhausted(10)
        XCTAssertNotNil(error.errorDescription)
        XCTAssertTrue(error.errorDescription!.contains("10"),
                       "reconnectionExhausted description should mention attempt count")
        XCTAssertTrue(error.errorDescription!.contains("reconnect"),
                       "reconnectionExhausted description should mention reconnect")
    }

    // MARK: - Reconnection events carry correct data

    func testReconnectingEventData() {
        let event = WebSocketEvent.reconnecting(attempt: 3, maxAttempts: 10)
        if case .reconnecting(let attempt, let maxAttempts) = event {
            XCTAssertEqual(attempt, 3)
            XCTAssertEqual(maxAttempts, 10)
        } else {
            XCTFail("Expected .reconnecting")
        }
    }

    func testReconnectedEvent() {
        let event = WebSocketEvent.reconnected
        if case .reconnected = event {} else {
            XCTFail("Expected .reconnected")
        }
    }

    func testReconnectionFailedWithError() {
        let underlying = WebSocketConnectionError.reconnectionExhausted(10)
        let event = WebSocketEvent.reconnectionFailed(underlying)
        if case .reconnectionFailed(let error) = event {
            XCTAssertNotNil(error)
            XCTAssertTrue(error is WebSocketConnectionError)
        } else {
            XCTFail("Expected .reconnectionFailed")
        }
    }

    func testReconnectionFailedWithNilError() {
        let event = WebSocketEvent.reconnectionFailed(nil)
        if case .reconnectionFailed(let error) = event {
            XCTAssertNil(error)
        } else {
            XCTFail("Expected .reconnectionFailed(nil)")
        }
    }

    // MARK: - collectedSegments preserved (not cleared by default)

    func testCollectedSegmentsEmptyAfterInit() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        let segments = await manager.collectedSegments
        XCTAssertTrue(segments.isEmpty)
    }

    // MARK: - WebSocketManager default init values

    func testWebSocketManagerDefaultLanguageAndChannels() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        let url = try await manager.buildElevenLabsURL(
            token: "tok",
            model: "scribe_v2_realtime",
            commitStrategy: "vad"
        )
        let urlString = url.absoluteString

        XCTAssertTrue(urlString.contains("include_language_detection=true"),
                      "Default language should enable automatic language detection")
        XCTAssertTrue(urlString.contains("commit_strategy=vad"))
    }

    func testBufferedAudioSurvivesReconnectionState() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        await manager.testingBufferAudioChunk(Data("chunk-1".utf8))
        await manager.testingBufferAudioChunk(Data("chunk-2".utf8))
        await manager.testingMarkReconnecting()

        let bufferedCount = await manager.testingBufferedAudioCount()
        XCTAssertEqual(bufferedCount, 2, "Buffered audio should survive the reconnect window")
    }
}
