import Foundation
import XCTest
@testable import WaiComputerKit

final class WebSocketManagerTests: XCTestCase {

    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    // MARK: - LiveTranscriptSegment Tests

    func testLiveTranscriptSegmentEncoding() throws {
        let segment = LiveTranscriptSegment(
            text: "Hello, how are you today?",
            speaker: "Speaker 0",
            isFinal: true,
            startMs: 500,
            endMs: 3200,
            confidence: 0.95
        )

        let jsonData = try encoder.encode(segment)
        let dict = try JSONSerialization.jsonObject(with: jsonData) as! [String: Any]

        XCTAssertEqual(dict["text"] as? String, "Hello, how are you today?")
        XCTAssertEqual(dict["speaker"] as? String, "Speaker 0")
        XCTAssertEqual(dict["is_final"] as? Bool, true)
        XCTAssertEqual(dict["start_ms"] as? Int, 500)
        XCTAssertEqual(dict["end_ms"] as? Int, 3200)
        XCTAssertEqual(dict["confidence"] as? Double, 0.95)
    }

    func testLiveTranscriptSegmentDecoding() throws {
        let json = """
        {
            "text": "Hello, how are you today?",
            "speaker": "Speaker 0",
            "is_final": true,
            "start_ms": 500,
            "end_ms": 3200,
            "confidence": 0.95
        }
        """.data(using: .utf8)!

        let segment = try decoder.decode(LiveTranscriptSegment.self, from: json)
        XCTAssertEqual(segment.text, "Hello, how are you today?")
        XCTAssertEqual(segment.speaker, "Speaker 0")
        XCTAssertTrue(segment.isFinal)
        XCTAssertEqual(segment.startMs, 500)
        XCTAssertEqual(segment.endMs, 3200)
        XCTAssertEqual(segment.confidence, 0.95)
    }

    func testLiveTranscriptSegmentWithNullSpeaker() throws {
        let json = """
        {
            "text": "Partial result",
            "is_final": false,
            "start_ms": 3200,
            "end_ms": 4000,
            "confidence": 0.8
        }
        """.data(using: .utf8)!

        let segment = try decoder.decode(LiveTranscriptSegment.self, from: json)
        XCTAssertNil(segment.speaker)
        XCTAssertFalse(segment.isFinal)
        XCTAssertEqual(segment.startMs, 3200)
    }

    // MARK: - WebSocketEvent Tests

    func testWebSocketEventEnum() throws {
        // .connected
        let connected = WebSocketEvent.connected
        if case .connected = connected {} else {
            XCTFail("Expected .connected")
        }

        // .transcript
        let segment = LiveTranscriptSegment(
            text: "Test",
            speaker: nil,
            isFinal: true,
            startMs: 0,
            endMs: 1000,
            confidence: 0.9
        )
        let transcriptEvent = WebSocketEvent.transcript(segment)
        if case .transcript(let seg) = transcriptEvent {
            XCTAssertEqual(seg.text, "Test")
            XCTAssertTrue(seg.isFinal)
        } else {
            XCTFail("Expected .transcript")
        }

        // .disconnected with nil error
        let disconnectedNil = WebSocketEvent.disconnected(nil)
        if case .disconnected(let error) = disconnectedNil {
            XCTAssertNil(error)
        } else {
            XCTFail("Expected .disconnected(nil)")
        }

        // .disconnected with an error
        let testError = URLError(.notConnectedToInternet)
        let disconnectedErr = WebSocketEvent.disconnected(testError)
        if case .disconnected(let error) = disconnectedErr {
            XCTAssertNotNil(error)
            XCTAssertTrue(error is URLError)
        } else {
            XCTFail("Expected .disconnected with error")
        }

        // .reconnecting
        let reconnecting = WebSocketEvent.reconnecting(attempt: 2, maxAttempts: 10)
        if case .reconnecting(let attempt, let max) = reconnecting {
            XCTAssertEqual(attempt, 2)
            XCTAssertEqual(max, 10)
        } else {
            XCTFail("Expected .reconnecting")
        }

        // .reconnected
        let reconnected = WebSocketEvent.reconnected
        if case .reconnected = reconnected {} else {
            XCTFail("Expected .reconnected")
        }

        // .reconnectionFailed
        let reconnectionFailed = WebSocketEvent.reconnectionFailed(
            WebSocketConnectionError.reconnectionExhausted(10)
        )
        if case .reconnectionFailed(let error) = reconnectionFailed {
            XCTAssertNotNil(error)
        } else {
            XCTFail("Expected .reconnectionFailed")
        }
    }

    // MARK: - WebSocketConnectionError Tests

    func testConnectionErrorDescriptions() {
        let disconnected = WebSocketConnectionError.disconnected(nil)
        XCTAssertNotNil(disconnected.errorDescription)

        let tokenFailed = WebSocketConnectionError.tokenFetchFailed("timeout")
        XCTAssertTrue(tokenFailed.errorDescription!.contains("timeout"))

        let serverError = WebSocketConnectionError.serverError("bad request")
        XCTAssertTrue(serverError.errorDescription!.contains("bad request"))

        let superseded = WebSocketConnectionError.superseded
        XCTAssertNotNil(superseded.errorDescription)

        let exhausted = WebSocketConnectionError.reconnectionExhausted(10)
        XCTAssertNotNil(exhausted.errorDescription)
        XCTAssertTrue(exhausted.errorDescription!.contains("10"))
    }

    // MARK: - cappedKeyTerms (ElevenLabs limits: 50 entries / 20 chars each)

    func testCappedKeyTermsRespectsCountLimit() {
        let input = (1...100).map { "term\($0)" }
        let output = WebSocketManager.cappedKeyTerms(input)
        XCTAssertEqual(output.count, WebSocketManager.elevenLabsKeyTermsLimit)
        XCTAssertEqual(output.first, "term1")
        XCTAssertEqual(output.last, "term50")
    }

    func testCappedKeyTermsTruncatesLongEntries() {
        let long = String(repeating: "a", count: 50)
        let output = WebSocketManager.cappedKeyTerms([long])
        XCTAssertEqual(output.first?.count, WebSocketManager.elevenLabsKeyTermCharLimit)
    }

    func testCappedKeyTermsTrimsAndDropsEmpties() {
        let output = WebSocketManager.cappedKeyTerms(["", "  ", "\nWaiComputer\t", "Anthropic"])
        XCTAssertEqual(output, ["WaiComputer", "Anthropic"])
    }

    // MARK: - buildElevenLabsURL with keyTerms

    func testBuildElevenLabsURLAppendsKeyTerms() async throws {
        let manager = WebSocketManager(
            apiClient: APIClient(baseURL: URL(string: "https://example.test")!),
            language: "en",
            channels: 1,
            keyTerms: ["WaiComputer", "Anthropic", "Mikhail"]
        )
        let url = try await manager.buildElevenLabsURL(
            token: "tok",
            model: "scribe_v2_realtime",
            commitStrategy: nil
        )
        let comps = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        let keytermsValues = (comps.queryItems ?? [])
            .filter { $0.name == "keyterms" }
            .compactMap { $0.value }
        XCTAssertEqual(keytermsValues, ["WaiComputer", "Anthropic", "Mikhail"])
    }

    func testBuildElevenLabsURLOmitsKeyTermsWhenEmpty() async throws {
        let manager = WebSocketManager(
            apiClient: APIClient(baseURL: URL(string: "https://example.test")!),
            language: "en",
            channels: 1,
            keyTerms: []
        )
        let url = try await manager.buildElevenLabsURL(
            token: "tok",
            model: "scribe_v2_realtime",
            commitStrategy: nil
        )
        let comps = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        let keytermsValues = (comps.queryItems ?? []).filter { $0.name == "keyterms" }
        XCTAssertTrue(keytermsValues.isEmpty)
    }
}
