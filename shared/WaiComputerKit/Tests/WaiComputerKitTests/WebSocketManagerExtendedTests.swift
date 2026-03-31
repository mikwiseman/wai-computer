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

    // MARK: - buildDeepgramURL with single channel

    func testBuildDeepgramURLSingleChannel() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient, language: "en", channels: 1)

        let url = try await manager.buildDeepgramURL(token: "test-token-123")
        let urlString = url.absoluteString

        // Should contain base Deepgram URL
        XCTAssertTrue(urlString.hasPrefix("wss://api.deepgram.com/v1/listen?"))

        // Should contain standard params
        XCTAssertTrue(urlString.contains("model=nova-3"))
        XCTAssertTrue(urlString.contains("language=en"))
        XCTAssertTrue(urlString.contains("punctuate=true"))
        XCTAssertTrue(urlString.contains("diarize=true"))
        XCTAssertTrue(urlString.contains("interim_results=true"))
        XCTAssertTrue(urlString.contains("utterance_end_ms=1000"))
        XCTAssertTrue(urlString.contains("vad_events=true"))
        XCTAssertTrue(urlString.contains("encoding=linear16"))
        XCTAssertTrue(urlString.contains("sample_rate=16000"))
        XCTAssertTrue(urlString.contains("token=test-token-123"))

        // Single channel should NOT have multichannel or channels params
        XCTAssertFalse(urlString.contains("multichannel=true"),
                       "Single channel should not include multichannel param")
        XCTAssertFalse(urlString.contains("channels="),
                       "Single channel should not include channels param")
    }

    // MARK: - buildDeepgramURL with 2 channels (multichannel)

    func testBuildDeepgramURLMultichannel() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient, language: "en", channels: 2)

        let url = try await manager.buildDeepgramURL(token: "mc-token")
        let urlString = url.absoluteString

        XCTAssertTrue(urlString.contains("channels=2"),
                       "Should include channels=2 for multichannel")
        XCTAssertTrue(urlString.contains("multichannel=true"),
                       "Should include multichannel=true when channels > 1")
        XCTAssertTrue(urlString.contains("token=mc-token"))
    }

    // MARK: - buildDeepgramURL with multi language includes endpointing

    func testBuildDeepgramURLMultiLanguageEndpointing() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient, language: "multi", channels: 1)

        let url = try await manager.buildDeepgramURL(token: "t")
        let urlString = url.absoluteString

        XCTAssertTrue(urlString.contains("language=multi"))
        XCTAssertTrue(urlString.contains("endpointing=100"),
                       "Multi language should include endpointing=100")
    }

    // MARK: - buildDeepgramURL non-multi language excludes endpointing

    func testBuildDeepgramURLNonMultiLanguageNoEndpointing() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient, language: "en", channels: 1)

        let url = try await manager.buildDeepgramURL(token: "t")
        let urlString = url.absoluteString

        XCTAssertFalse(urlString.contains("endpointing="),
                        "Non-multi language should not include endpointing param")
    }

    // MARK: - events property returns same stream on repeated access

    func testEventsReturnsSameStreamOnRepeatedAccess() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        // Access events twice -- withUnsafeContinuation trick to compare identity
        // Since AsyncStream is a struct, we verify the continuation is only created once
        // by checking that both calls return without error (the internal _eventStream is reused).
        // We use a proxy: yield an event and confirm it arrives on the first stream reference.
        let stream1 = await manager.events
        let stream2 = await manager.events

        // Disconnect to finish the stream so iteration completes
        await manager.disconnect()

        // Both should be iterable (the same underlying stream)
        var events1: [WebSocketEvent] = []
        for await event in stream1 {
            events1.append(event)
        }

        // stream2 should be exhausted too since it's the same stream
        var events2: [WebSocketEvent] = []
        for await event in stream2 {
            events2.append(event)
        }

        // stream1 consumed the disconnect event, stream2 gets nothing (same stream, already consumed)
        XCTAssertEqual(events1.count, 1, "First accessor should get the disconnected event")
        XCTAssertEqual(events2.count, 0, "Second accessor should get nothing (same stream, already consumed)")
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

    // MARK: - DeepgramTokenResponse forward compatibility (extra fields)

    func testDeepgramTokenResponseExtraFields() throws {
        let json = """
        {
            "access_token": "dg-jwt-abc",
            "expires_in": 600,
            "token_type": "Bearer",
            "scope": "listen"
        }
        """.data(using: .utf8)!

        // Should decode without error even though extra fields are present
        let response = try decoder.decode(DeepgramTokenResponse.self, from: json)
        XCTAssertEqual(response.accessToken, "dg-jwt-abc")
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
        // Default: language="multi", channels=1
        let manager = WebSocketManager(apiClient: apiClient)

        let url = try await manager.buildDeepgramURL(token: "tok")
        let urlString = url.absoluteString

        XCTAssertTrue(urlString.contains("language=multi"),
                       "Default language should be 'multi'")
        XCTAssertFalse(urlString.contains("channels="),
                        "Default single channel should not include channels param")
        XCTAssertTrue(urlString.contains("endpointing=100"),
                       "Default 'multi' language should include endpointing")
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
