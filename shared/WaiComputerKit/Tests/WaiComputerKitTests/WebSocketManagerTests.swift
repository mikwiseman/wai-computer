import Foundation
import XCTest
@testable import WaiComputerKit

final class WebSocketManagerTests: XCTestCase {

    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    // MARK: - AudioMessage Tests

    func testAudioMessageEncoding() throws {
        let base64Data = "SGVsbG8gV29ybGQ="
        let timestamp: Int64 = 1706745600000
        let message = AudioMessage(data: base64Data, timestamp: timestamp)

        let jsonData = try encoder.encode(message)
        let dict = try JSONSerialization.jsonObject(with: jsonData) as! [String: Any]

        XCTAssertEqual(dict["type"] as? String, "audio")
        XCTAssertEqual(dict["data"] as? String, "SGVsbG8gV29ybGQ=")
        XCTAssertEqual(dict["timestamp"] as? Int64, 1706745600000)
    }

    // MARK: - TranscriptMessage Tests

    func testTranscriptMessageDecoding() throws {
        let json = """
        {
            "type": "transcript",
            "text": "Hello, how are you today?",
            "speaker": "Alice",
            "is_final": true,
            "start_ms": 500,
            "end_ms": 3200
        }
        """.data(using: .utf8)!

        let message = try decoder.decode(TranscriptMessage.self, from: json)
        XCTAssertEqual(message.type, "transcript")
        XCTAssertEqual(message.text, "Hello, how are you today?")
        XCTAssertEqual(message.speaker, "Alice")
        XCTAssertTrue(message.isFinal)
        XCTAssertEqual(message.startMs, 500)
        XCTAssertEqual(message.endMs, 3200)

        // Test without optional speaker
        let noSpeakerJSON = """
        {
            "type": "transcript",
            "text": "Partial result",
            "is_final": false,
            "start_ms": 3200,
            "end_ms": 4000
        }
        """.data(using: .utf8)!

        let noSpeaker = try decoder.decode(TranscriptMessage.self, from: noSpeakerJSON)
        XCTAssertNil(noSpeaker.speaker)
        XCTAssertFalse(noSpeaker.isFinal)
        XCTAssertEqual(noSpeaker.startMs, 3200)
    }

    // MARK: - StatusMessage Tests

    func testStatusMessageDecoding() throws {
        let json = """
        {
            "type": "status",
            "status": "processing",
            "message": "Transcription in progress"
        }
        """.data(using: .utf8)!

        let message = try decoder.decode(StatusMessage.self, from: json)
        XCTAssertEqual(message.type, "status")
        XCTAssertEqual(message.status, "processing")
        XCTAssertEqual(message.message, "Transcription in progress")

        // Status without message
        let noMsgJSON = """
        {
            "type": "status",
            "status": "ready"
        }
        """.data(using: .utf8)!

        let noMsg = try decoder.decode(StatusMessage.self, from: noMsgJSON)
        XCTAssertEqual(noMsg.status, "ready")
        XCTAssertNil(noMsg.message)
    }

    // MARK: - WebSocketEvent Tests

    func testWebSocketEventEnum() throws {
        // .connected
        let connected = WebSocketEvent.connected
        if case .connected = connected {} else {
            XCTFail("Expected .connected")
        }

        // .transcript
        let transcriptJSON = """
        {
            "type": "transcript",
            "text": "Test",
            "is_final": true,
            "start_ms": 0,
            "end_ms": 1000
        }
        """.data(using: .utf8)!
        let transcriptMsg = try decoder.decode(TranscriptMessage.self, from: transcriptJSON)
        let transcriptEvent = WebSocketEvent.transcript(transcriptMsg)
        if case .transcript(let msg) = transcriptEvent {
            XCTAssertEqual(msg.text, "Test")
            XCTAssertTrue(msg.isFinal)
        } else {
            XCTFail("Expected .transcript")
        }

        // .status
        let statusJSON = """
        {"type": "status", "status": "connected"}
        """.data(using: .utf8)!
        let statusMsg = try decoder.decode(StatusMessage.self, from: statusJSON)
        let statusEvent = WebSocketEvent.status(statusMsg)
        if case .status(let msg) = statusEvent {
            XCTAssertEqual(msg.status, "connected")
        } else {
            XCTFail("Expected .status")
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
    }
}
