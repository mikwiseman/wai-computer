import XCTest
@testable import WaiComputerKit

final class CompanionStreamTests: XCTestCase {

    private let parser = CompanionStreamParser()

    func testParsesTurnStartFrame() {
        let frame = """
        event: turn_start
        data: {"message_id":"m1","conversation_id":"c1"}
        """
        let event = parser.parse(frame)
        XCTAssertEqual(event, .turnStart(messageId: "m1", conversationId: "c1"))
    }

    func testParsesToolCallAndResultFrames() {
        let call = parser.parse("event: tool_call\ndata: {\"call_id\":\"t1\",\"tool\":\"search_transcripts\",\"args\":{\"query\":\"x\"}}")
        XCTAssertEqual(call, .toolCall(callId: "t1", tool: "search_transcripts"))

        let result = parser.parse("event: tool_result\ndata: {\"call_id\":\"t1\",\"summary\":\"3 segments\"}")
        XCTAssertEqual(result, .toolResult(callId: "t1", summary: "3 segments"))
    }

    func testParsesTokenFrame() {
        let event = parser.parse("event: token\ndata: {\"text\":\"hello\"}")
        XCTAssertEqual(event, .token(text: "hello"))
    }

    func testParsesCitationFrame() {
        let event = parser.parse("""
        event: citation
        data: {"index":1,"segment_id":"s1","recording_id":"r1","start_ms":1000,"end_ms":2000,"span_start":0,"span_end":5}
        """)
        guard case .citation(let cit) = event else {
            XCTFail("Expected citation event, got \(String(describing: event))")
            return
        }
        XCTAssertEqual(cit.index, 1)
        XCTAssertEqual(cit.segmentId, "s1")
        XCTAssertEqual(cit.recordingId, "r1")
        XCTAssertEqual(cit.startMs, 1000)
        XCTAssertEqual(cit.endMs, 2000)
    }

    func testParsesDoneAndErrorFrames() {
        let done = parser.parse("event: done\ndata: {\"message_id\":\"a1\",\"model\":\"gpt-5.5\",\"latency_ms\":1234}")
        XCTAssertEqual(done, .done(messageId: "a1", model: "gpt-5.5", latencyMs: 1234))

        let err = parser.parse("event: error\ndata: {\"code\":\"boom\",\"message\":\"bad\"}")
        XCTAssertEqual(err, .error(code: "boom", message: "bad"))
    }

    func testReturnsNilForMalformedFrame() {
        XCTAssertNil(parser.parse("no event line at all"))
        XCTAssertNil(parser.parse("event: token\nno data line"))
        XCTAssertNil(parser.parse("event: token\ndata: not valid json"))
    }

    func testStreamingByteSequenceYieldsEventsInOrder() async {
        let raw = """
        event: turn_start
        data: {"message_id":"m1","conversation_id":"c1"}

        event: token
        data: {"text":"hi"}

        event: done
        data: {"message_id":"a1","model":"gpt-5.5","latency_ms":42}


        """
        let bytes = AsyncByteSequence(string: raw)
        var collected: [CompanionStreamEvent] = []
        for await event in companionEvents(bytes: bytes) {
            collected.append(event)
        }
        XCTAssertEqual(collected.count, 3)
        XCTAssertEqual(collected[0], .turnStart(messageId: "m1", conversationId: "c1"))
        XCTAssertEqual(collected[1], .token(text: "hi"))
        XCTAssertEqual(collected[2], .done(messageId: "a1", model: "gpt-5.5", latencyMs: 42))
    }
}

/// Minimal byte-emitting async sequence used to drive companionEvents().
private struct AsyncByteSequence: AsyncSequence {
    typealias Element = UInt8
    let bytes: [UInt8]

    init(string: String) {
        self.bytes = Array(string.utf8)
    }

    func makeAsyncIterator() -> Iterator {
        Iterator(bytes: bytes)
    }

    struct Iterator: AsyncIteratorProtocol {
        var bytes: [UInt8]
        var index = 0

        mutating func next() async -> UInt8? {
            guard index < bytes.count else { return nil }
            defer { index += 1 }
            return bytes[index]
        }
    }
}
